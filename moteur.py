"""
Moteur d'analyse : orchestre données + indicateurs pour produire le tableau de bord.

Chaîne complète :
    Top N CoinGecko -> historique OHLCV -> N indicateurs -> critères qualitatifs
                    -> scores agrégés -> tableaux prêts à afficher

Le moteur ne sait rien de l'affichage : il expose des DataFrames et des dicts,
libre à l'interface (Streamlit, Tkinter, web...) de les mettre en forme.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

import config
from donnees import SourceDonnees
from indicateurs import Categorie, Indicateur, ResultatIndicateur, creer, qualifier_score


# ===========================================================================
# RÉSULTAT PAR CRYPTO
# ===========================================================================
@dataclass
class ResultatCrypto:
    """Photographie complète d'une crypto à un instant donné."""

    symbole: str
    nom: str = ""
    rang: int | None = None
    prix: float | None = None
    capitalisation: float | None = None
    variation_24h: float | None = None
    resultats: dict[str, ResultatIndicateur] = field(default_factory=dict)
    erreur: str | None = None

    # -- Agrégations --------------------------------------------------------
    @property
    def indicateurs_valides(self) -> list[ResultatIndicateur]:
        """Indicateurs ayant produit au moins un critère exploitable (affichage)."""
        return [r for r in self.resultats.values() if not r.erreur and r.criteres]

    @property
    def indicateurs_notes(self) -> list[ResultatIndicateur]:
        """
        Sous-ensemble entrant dans le score : les indicateurs purement contextuels
        (ATR) sont affichés mais ne sont pas notés, leur score étant toujours nul.
        """
        return [r for r in self.indicateurs_valides if r.porte_une_direction]

    @property
    def score_global(self) -> float:
        """
        Score dans [-1, 1] : moyenne des scores d'indicateurs.

        Moyenne par INDICATEUR et non par critère : sans cela, Ichimoku (5
        critères) pèserait deux fois et demie plus lourd que le stochastique
        (2 critères) sans raison.
        """
        notes = self.indicateurs_notes
        if not notes:
            return 0.0
        return sum(r.score for r in notes) / len(notes)

    @property
    def synthese(self) -> str:
        return qualifier_score(self.score_global) if self.indicateurs_notes else "Non disponible"

    def score_categorie(self, categorie: Categorie) -> float | None:
        """Score moyen d'une famille d'indicateurs (None si aucune donnée)."""
        concernes = [r for r in self.indicateurs_notes if r.categorie == categorie]
        if not concernes:
            return None
        return sum(r.score for r in concernes) / len(concernes)

    @property
    def raison_indisponible(self) -> str:
        """
        Explique pourquoi une crypto n'a aucun score, pour l'afficher plutôt que
        de la masquer.

        Trois cas se distinguent :
          - le téléchargement a échoué      -> l'erreur de la source ;
          - les données sont là mais courtes -> l'erreur la plus fréquente des
            indicateurs, du type « Historique insuffisant (12 bougies, 210 requises) » ;
          - tout a échoué sans message      -> un libellé générique.
        """
        if self.erreur:
            return self.erreur
        if self.indicateurs_notes:
            return ""
        erreurs = [r.erreur for r in self.resultats.values() if r.erreur]
        if erreurs:
            return max(set(erreurs), key=erreurs.count)
        return "Aucun indicateur exploitable"

    def compter_signaux(self) -> dict[str, int]:
        """Répartition positifs / neutres / négatifs sur tous les critères directionnels."""
        compte = {"positifs": 0, "neutres": 0, "negatifs": 0}
        for resultat in self.indicateurs_valides:
            for critere in resultat.criteres:
                if not critere.directionnel:
                    continue
                if critere.signal.value > 0:
                    compte["positifs"] += 1
                elif critere.signal.value < 0:
                    compte["negatifs"] += 1
                else:
                    compte["neutres"] += 1
        return compte

    def to_dict(self) -> dict:
        return {
            "symbole": self.symbole,
            "nom": self.nom,
            "rang": self.rang,
            "prix": self.prix,
            "capitalisation": self.capitalisation,
            "variation_24h": self.variation_24h,
            "score_global": round(self.score_global, 3),
            "synthese": self.synthese,
            "erreur": self.erreur,
            "indicateurs": {code: r.to_dict() for code, r in self.resultats.items()},
        }


# ===========================================================================
# MOTEUR
# ===========================================================================
class AnalyseurMarche:
    """
    Point d'entrée du projet.

        analyseur = AnalyseurMarche(codes=["BOLLINGER", "RSI", "MACD"])
        resultats = analyseur.analyser_top(20)
        tableau   = analyseur.tableau_criteres(resultats)
    """

    def __init__(self, codes: list[str] | None = None, reglages: dict | None = None,
                 source: SourceDonnees | None = None,
                 intervalle: str = config.INTERVALLE_DEFAUT,
                 nb_bougies: int = config.NB_BOUGIES_DEFAUT,
                 verbeux: bool = True):
        self.indicateurs: list[Indicateur] = creer(codes, reglages)
        self.source = source or SourceDonnees(verbeux=verbeux)
        self.intervalle = intervalle
        self.nb_bougies = nb_bougies
        self.verbeux = verbeux
        # Historiques téléchargés lors de la dernière analyse, conservés pour le
        # module de suivi : il en a besoin pour retrouver le prix exact d'une
        # échéance passée, plutôt que de re-télécharger les mêmes bougies.
        self.historiques: dict[str, pd.DataFrame] = {}

    def _log(self, message: str):
        if self.verbeux:
            print(message)

    # -- Analyse ------------------------------------------------------------
    def analyser_historique(self, symbole: str, df: pd.DataFrame, **infos) -> ResultatCrypto:
        """
        Applique les indicateurs sélectionnés à un historique déjà chargé.
        Utile pour tester sans réseau ou pour rejouer des données locales.
        """
        resultat = ResultatCrypto(symbole=symbole, **infos)
        if df is None or df.empty:
            resultat.erreur = "Aucune donnée de prix"
            return resultat
        for indicateur in self.indicateurs:
            resultat.resultats[indicateur.code] = indicateur.analyser(df)
        return resultat

    def analyser_crypto(self, symbole: str, **infos) -> ResultatCrypto:
        """Télécharge l'historique d'une crypto puis l'analyse."""
        df = self.source.historique(symbole, self.intervalle, self.nb_bougies)
        if df is None or df.empty:
            self._log(f"   {symbole} : historique indisponible, ignorée.")
            return ResultatCrypto(symbole=symbole, erreur="Historique indisponible", **infos)
        self.historiques[symbole] = df
        return self.analyser_historique(symbole, df, **infos)

    def analyser_top(self, n: int = config.NB_CRYPTOS_DEFAUT) -> list[ResultatCrypto]:
        """
        Pipeline complet : classement par capitalisation puis analyse de chacune.
        Les cryptos sans historique exploitable sont conservées avec leur erreur,
        pour que le tableau de bord puisse l'afficher plutôt que de les masquer.
        """
        self.historiques.clear()
        classement = self.source.top_cryptos(n)
        self._log(f"\nAnalyse de {len(classement)} cryptos "
                  f"avec {len(self.indicateurs)} indicateurs ({self.intervalle})...")

        resultats = []
        for symbole, ligne in classement.iterrows():
            self._log(f" - {symbole}")
            resultats.append(
                self.analyser_crypto(
                    symbole,
                    nom=ligne.get("nom", ""),
                    rang=int(ligne["rang"]) if pd.notna(ligne.get("rang")) else None,
                    prix=ligne.get("prix"),
                    capitalisation=ligne.get("capitalisation"),
                    variation_24h=ligne.get("variation_24h"),
                )
            )
        return resultats

    # -- Mise en forme pour l'affichage -------------------------------------
    @staticmethod
    def tableau_synthese(resultats: list[ResultatCrypto]) -> pd.DataFrame:
        """
        Vue d'ensemble : une ligne par crypto, une colonne par indicateur
        (avec sa synthèse qualitative). C'est le tableau de bord principal.
        """
        lignes = []
        for resultat in resultats:
            ligne = {
                "Symbole": resultat.symbole,
                "Nom": resultat.nom,
                "Rang": resultat.rang,
                "Prix": resultat.prix,
                "Var 24h %": resultat.variation_24h,
                "Score": round(resultat.score_global, 3),
                "Synthèse": resultat.synthese,
            }
            for categorie in Categorie:
                score = resultat.score_categorie(categorie)
                ligne[categorie.value] = None if score is None else round(score, 3)
            for code, indicateur in resultat.resultats.items():
                ligne[code] = indicateur.synthese
            lignes.append(ligne)
        return pd.DataFrame(lignes)

    @staticmethod
    def tableau_criteres(resultats: list[ResultatCrypto]) -> pd.DataFrame:
        """
        Vue détaillée au format long : une ligne par critère qualitatif.
        Format idéal pour filtrer, grouper ou alimenter un composant d'UI.
        """
        lignes = []
        for resultat in resultats:
            for indicateur in resultat.resultats.values():
                if indicateur.erreur:
                    lignes.append(
                        {
                            "Symbole": resultat.symbole,
                            "Catégorie": indicateur.categorie.value,
                            "Indicateur": indicateur.nom,
                            "Code indicateur": indicateur.code,
                            "Critère": "—",
                            "Code critère": "—",
                            "Valeur qualitative": indicateur.erreur,
                            "Signal": "Non disponible",
                            "Score": 0,
                            "Valeur numérique": None,
                            "Directionnel": False,
                        }
                    )
                    continue
                for critere in indicateur.criteres:
                    lignes.append(
                        {
                            "Symbole": resultat.symbole,
                            "Catégorie": indicateur.categorie.value,
                            "Indicateur": indicateur.nom,
                            "Code indicateur": indicateur.code,
                            "Critère": critere.libelle,
                            "Code critère": critere.code,
                            "Valeur qualitative": critere.valeur,
                            "Signal": critere.signal.libelle,
                            "Score": critere.signal.value,
                            "Valeur numérique": critere.valeur_num,
                            "Directionnel": critere.directionnel,
                        }
                    )
        return pd.DataFrame(lignes)

    @staticmethod
    def classement(resultats: list[ResultatCrypto]) -> pd.DataFrame:
        """Cryptos triées du plus haussier au plus baissier, avec le décompte de signaux."""
        lignes = []
        for resultat in resultats:
            if not resultat.indicateurs_notes:
                continue
            compte = resultat.compter_signaux()
            lignes.append(
                {
                    "Symbole": resultat.symbole,
                    "Nom": resultat.nom,
                    "Score": round(resultat.score_global, 3),
                    "Synthèse": resultat.synthese,
                    "Critères positifs": compte["positifs"],
                    "Critères neutres": compte["neutres"],
                    "Critères négatifs": compte["negatifs"],
                }
            )
        tableau = pd.DataFrame(lignes)
        if tableau.empty:
            return tableau
        return tableau.sort_values("Score", ascending=False).reset_index(drop=True)
