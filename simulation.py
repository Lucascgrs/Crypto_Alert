"""
Simulation historique : qu'aurait rapporté une stratégie fondée sur les scores ?

Différence essentielle avec `suivi.py` : celui-ci enregistre les scores au fil de
l'eau et attend que le temps passe. Ici on remonte le temps — on recalcule les
scores à chaque barre du passé et on rejoue les allers-retours qu'ils auraient
déclenchés.

Règle du jeu :

  1. à chaque barre de la fenêtre simulée, le score est recalculé avec les
     seules données disponibles à cet instant ;
  2. si |score| tombe entre le seuil minimum et le seuil maximum et que son sens
     est autorisé, une position s'ouvre au cours de clôture ;
  3. elle se referme dès qu'une condition de sortie est remplie — stop de perte,
     objectif de gain, retournement du score, ou durée maximale atteinte ;
  4. aucune position ne se chevauche : tant qu'une est ouverte, les signaux
     suivants sont ignorés — c'est ce qui permet de faire travailler un capital
     unique et d'obtenir un « combien j'aurais gagné » qui ait un sens.

**Aucune information future n'intervient** : les indicateurs sont causaux et
l'interprétation à la barre t ne voit que les barres antérieures (voir
`Indicateur.analyser_serie`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

import presentation as pr
from donnees import SourceDonnees
from indicateurs import Categorie, creer, periodes_requises
from moteur import ResultatCrypto

# Sens de position autorisés.
SENS_CROISSANT = "Croissant (achat)"
SENS_DECROISSANT = "Décroissant (vente à découvert)"
SENS_LES_DEUX = "Les deux"
SENS_POSSIBLES = [SENS_LES_DEUX, SENS_CROISSANT, SENS_DECROISSANT]

# Types de score simulables : le score global, ou l'une des quatre familles.
CATEGORIES_SCORE = {
    "Tendance": Categorie.TENDANCE,
    "Momentum": Categorie.MOMENTUM,
    "Volatilité": Categorie.VOLATILITE,
    "Volume": Categorie.VOLUME,
}
TYPES_SCORE = ["Global"] + list(CATEGORIES_SCORE)

# Motifs de sortie. Les distinguer n'est pas cosmétique : une stratégie qui ne
# gagne que par son stop et une autre qui gagne par son signal se lisent de la
# même façon sur le capital final, et ne valent pas la même chose.
MOTIF_DUREE = "Durée"
MOTIF_OBJECTIF = "Objectif"
MOTIF_STOP = "Stop"
MOTIF_RETOURNEMENT = "Retournement"
MOTIFS = [MOTIF_DUREE, MOTIF_OBJECTIF, MOTIF_STOP, MOTIF_RETOURNEMENT]


# ===========================================================================
# PARAMÈTRES
# ===========================================================================
@dataclass
class ParametresSimulation:
    """Tous les réglages d'une simulation."""

    mise: float = 1000.0              # capital de départ, par crypto
    intervalle: str = "1d"
    periodes: int = 150               # nombre de barres passées simulées
    duree_position: int = 6           # durée de détention MAXIMALE, en bougies
    symboles: list[str] = field(default_factory=list)
    type_score: str = "Global"
    seuil_min: float = 0.30           # sur la VALEUR ABSOLUE du score
    seuil_max: float = 1.00
    sens: str = SENS_LES_DEUX
    codes: list[str] | None = None    # indicateurs retenus (None = tous)
    # Frais par transaction, en pourcentage. Comptés à l'entrée ET à la sortie.
    # Sans eux, une stratégie qui multiplie les allers-retours paraît toujours
    # rentable : c'est le biais le plus courant d'un backtest naïf.
    frais_pct: float = 0.10

    # --- Sorties anticipées. 0 (ou None) désactive la condition. ---
    # Retournement : nombre de POINTS de score dont le score doit se retourner
    # contre la position, par rapport à sa valeur d'entrée, pour la couper. Le
    # score vivant dans [-1, 1], 0,30 est déjà un franc changement d'avis.
    # Constaté à la clôture de chaque bougie, comme le score lui-même.
    retournement: float | None = None
    # Objectif de gain et stop de perte, en pourcentage du prix d'entrée. Ils
    # peuvent se déclencher EN COURS de bougie : on les cherche dans le haut et
    # le bas, pas seulement à la clôture.
    objectif_pct: float | None = None
    stop_pct: float | None = None

    def description_sorties(self) -> str:
        """Les conditions de sortie actives, en une ligne lisible."""
        morceaux = [f"durée max {self.duree_position} bougies"]
        if self.retournement:
            morceaux.append(f"retournement de {self.retournement:.2f} pt")
        if self.objectif_pct:
            morceaux.append(f"objectif +{self.objectif_pct:.1f} %")
        if self.stop_pct:
            morceaux.append(f"stop -{self.stop_pct:.1f} %")
        return " · ".join(morceaux)

    def autorise(self, score: float) -> str | None:
        """Sens de la position à ouvrir pour ce score, ou None s'il ne déclenche rien."""
        if not (self.seuil_min <= abs(score) <= self.seuil_max):
            return None
        if score > 0 and self.sens in (SENS_CROISSANT, SENS_LES_DEUX):
            return "Achat"
        if score < 0 and self.sens in (SENS_DECROISSANT, SENS_LES_DEUX):
            return "Vente à découvert"
        return None


# ===========================================================================
# RÉSULTATS
# ===========================================================================
@dataclass
class Trade:
    """Un aller-retour simulé."""

    symbole: str
    sens: str
    score: float
    entree: datetime
    sortie: datetime
    prix_entree: float
    prix_sortie: float
    rendement_brut_pct: float
    rendement_net_pct: float
    capital_avant: float
    capital_apres: float
    motif: str = MOTIF_DUREE          # ce qui a refermé la position

    @property
    def gagnant(self) -> bool:
        return self.rendement_net_pct > 0

    def to_dict(self) -> dict:
        return {
            "Crypto": self.symbole,
            "Sens": self.sens,
            "Score": round(self.score, 3),
            "Entrée": self.entree,
            "Sortie": self.sortie,
            "Motif": self.motif,
            "Prix entrée": self.prix_entree,
            "Prix sortie": self.prix_sortie,
            "Rendement brut %": round(self.rendement_brut_pct, 3),
            "Rendement net %": round(self.rendement_net_pct, 3),
            "Capital après": round(self.capital_apres, 2),
        }


@dataclass
class ResultatSimulation:
    """Ce qu'a donné la stratégie sur une crypto."""

    symbole: str
    capital_initial: float
    capital_final: float = 0.0
    trades: list[Trade] = field(default_factory=list)
    courbe: pd.Series | None = None
    rendement_marche_pct: float | None = None   # achat-conservation, la référence
    debut: datetime | None = None
    fin: datetime | None = None
    erreur: str | None = None

    @property
    def gain(self) -> float:
        return self.capital_final - self.capital_initial

    @property
    def gain_pct(self) -> float:
        if not self.capital_initial:
            return 0.0
        return 100 * self.gain / self.capital_initial

    @property
    def nb_trades(self) -> int:
        return len(self.trades)

    @property
    def gagnants(self) -> int:
        return sum(1 for t in self.trades if t.gagnant)

    @property
    def taux_reussite(self) -> float | None:
        return 100 * self.gagnants / self.nb_trades if self.trades else None

    @property
    def rendement_moyen_pct(self) -> float | None:
        if not self.trades:
            return None
        return sum(t.rendement_net_pct for t in self.trades) / self.nb_trades

    @property
    def surperformance_pct(self) -> float | None:
        """
        Écart à l'achat-conservation : la seule mesure qui dise si la stratégie
        a servi à quelque chose. Gagner 8 % quand le marché en a pris 20, c'est
        avoir perdu 12 points à s'agiter.
        """
        if self.rendement_marche_pct is None:
            return None
        return self.gain_pct - self.rendement_marche_pct


# ===========================================================================
# SIMULATEUR
# ===========================================================================
class Simulateur:
    """
        simulateur = Simulateur()
        resultats = simulateur.simuler(ParametresSimulation(symboles=["BTC", "ETH"]))
        Simulateur.tableau(resultats)
    """

    def __init__(self, source: SourceDonnees | None = None, verbeux: bool = False):
        self.source = source or SourceDonnees(verbeux=verbeux)
        self.verbeux = verbeux

    # -- Pilotage -----------------------------------------------------------
    def simuler(self, parametres: ParametresSimulation, progression=None
                ) -> list[ResultatSimulation]:
        """
        Rejoue la stratégie sur chaque crypto. `progression(fait, total, symbole)`
        est appelée avant chaque crypto, pour alimenter une barre d'avancement.
        """
        indicateurs = creer(parametres.codes)

        # Simuler le score « Momentum » sans aucun indicateur de momentum
        # sélectionné ne produirait aucun trade, sans rien expliquer.
        #
        # Les indicateurs CONTEXTUELS (ATR, compression, efficience) ne comptent
        # pas ici : ils appartiennent bien à la famille, mais ne produisent aucun
        # critère directionnel, donc aucun score. Les accepter laisserait la
        # simulation tourner à vide en annonçant zéro trade sans raison visible.
        categorie = CATEGORIES_SCORE.get(parametres.type_score)
        notants = [i for i in indicateurs if i.categorie == categorie and not i.contextuel]
        if categorie and not notants:
            presents = any(i.categorie == categorie for i in indicateurs)
            manque = (
                f"Les indicateurs de la famille « {parametres.type_score} » "
                "sélectionnés sont tous contextuels : ils ne produisent pas de score."
                if presents else
                f"Aucun indicateur de la famille « {parametres.type_score} » "
                "n'est sélectionné : ce score ne peut pas être calculé."
            )
            return [
                ResultatSimulation(symbole=s, capital_initial=parametres.mise, erreur=manque)
                for s in parametres.symboles
            ]

        echauffement = periodes_requises(indicateurs)

        # Il faut de quoi « chauffer » les indicateurs, puis la fenêtre simulée,
        # puis de quoi refermer la dernière position. Pas de plafond ici :
        # `SourceDonnees._binance` pagine au-delà de 1000 bougies.
        nb_bougies = echauffement + parametres.periodes + parametres.duree_position

        resultats = []
        for rang, symbole in enumerate(parametres.symboles):
            if progression:
                progression(rang, len(parametres.symboles), symbole)
            resultats.append(
                self._simuler_crypto(symbole, parametres, indicateurs, echauffement, nb_bougies)
            )
        if progression:
            progression(len(parametres.symboles), len(parametres.symboles), "")
        return resultats

    def _simuler_crypto(self, symbole, parametres, indicateurs, echauffement, nb_bougies):
        resultat = ResultatSimulation(symbole=symbole, capital_initial=parametres.mise)

        df = self.source.historique(symbole, parametres.intervalle, nb_bougies)
        if df is None or df.empty:
            resultat.erreur = "Historique indisponible"
            return resultat

        # Dernière barre exploitable : il faut pouvoir refermer la position.
        derniere_entree = len(df) - 1 - parametres.duree_position
        premiere_entree = max(echauffement - 1, derniere_entree - parametres.periodes + 1)
        if derniere_entree < premiere_entree:
            resultat.erreur = (
                f"Historique trop court ({len(df)} bougies) : il en faut "
                f"{echauffement + parametres.duree_position} au minimum."
            )
            return resultat

        positions = list(range(premiere_entree, derniere_entree + 1))

        # Le retournement se juge pendant la détention : il faut alors les scores
        # au-delà de la dernière entrée possible. On ne les calcule que dans ce
        # cas — chaque position supplémentaire coûte une interprétation.
        fin_scores = len(df) - 1 if parametres.retournement else derniere_entree
        scores = self._scores(
            df, list(range(premiere_entree, fin_scores + 1)),
            indicateurs, parametres, symbole,
        )
        self._rejouer(df, positions, scores, parametres, resultat)
        return resultat

    # -- Calcul des scores passés -------------------------------------------
    def _scores(self, df, positions, indicateurs, parametres, symbole) -> dict:
        """
        Score de chaque barre de la fenêtre simulée.

        Les indicateurs sont calculés UNE fois sur toute la série puis
        interprétés à chaque position (cf. `Indicateur.analyser_serie`) : c'est
        ce qui rend la simulation praticable.
        """
        par_indicateur = {
            indicateur.code: indicateur.analyser_serie(df, positions)
            for indicateur in indicateurs
        }
        categorie = CATEGORIES_SCORE.get(parametres.type_score)

        scores = {}
        for position in positions:
            # On réutilise l'agrégation exacte du tableau de bord : le score
            # simulé et le score affiché doivent être le même nombre.
            photo = ResultatCrypto(symbole=symbole)
            photo.resultats = {code: res[position] for code, res in par_indicateur.items()}
            valeur = photo.score_categorie(categorie) if categorie else photo.score_global
            scores[position] = valeur
        return scores

    # -- Déroulé des trades -------------------------------------------------
    @staticmethod
    def _rejouer(df, positions, scores, parametres, resultat):
        """Ouvre et referme les positions, et tient le capital à jour."""
        cloture = df["Close"]
        frais = parametres.frais_pct / 100
        capital = parametres.mise

        points = [(df.index[positions[0]], capital)]
        libre_a_partir_de = positions[0]

        for position in positions:
            if position < libre_a_partir_de:
                continue   # une position est encore ouverte
            score = scores.get(position)
            if score is None:
                continue
            sens = parametres.autorise(score)
            if sens is None:
                continue

            prix_entree = float(cloture.iloc[position])
            sortie, prix_sortie, motif = Simulateur._denouer(
                df, scores, position, sens, prix_entree, score, parametres
            )
            variation = (prix_sortie - prix_entree) / prix_entree

            # À découvert, on gagne quand le prix baisse.
            brut = variation if sens == "Achat" else -variation
            net = brut - 2 * frais   # frais à l'entrée et à la sortie

            avant = capital
            capital *= 1 + net
            resultat.trades.append(
                Trade(
                    symbole=resultat.symbole, sens=sens, score=score,
                    entree=df.index[position], sortie=df.index[sortie],
                    prix_entree=prix_entree, prix_sortie=prix_sortie,
                    rendement_brut_pct=brut * 100, rendement_net_pct=net * 100,
                    capital_avant=avant, capital_apres=capital, motif=motif,
                )
            )
            points.append((df.index[sortie], capital))
            libre_a_partir_de = sortie + 1

        resultat.capital_final = capital
        resultat.debut = df.index[positions[0]]
        resultat.fin = df.index[min(positions[-1] + parametres.duree_position, len(df) - 1)]

        # Achat-conservation sur exactement la même fenêtre : la référence.
        depart = float(cloture.iloc[positions[0]])
        arrivee = float(cloture.loc[resultat.fin])
        resultat.rendement_marche_pct = 100 * (arrivee - depart) / depart

        # La courbe se prolonge jusqu'à la fin de la fenêtre, même sans trade,
        # sinon elle s'arrêterait au dernier aller-retour.
        if points[-1][0] != resultat.fin:
            points.append((resultat.fin, capital))
        horodatages, valeurs = zip(*points)
        resultat.courbe = pd.Series(valeurs, index=pd.DatetimeIndex(horodatages))

    @staticmethod
    def _denouer(df, scores, entree, sens, prix_entree, score_entree, parametres):
        """
        Cherche où et à quel prix une position se referme.

        Renvoie `(barre de sortie, prix de sortie, motif)`.

        Quatre conditions sont examinées à chaque bougie qui suit l'entrée, dans
        cet ordre :

          - le STOP et l'OBJECTIF portent sur le prix. Ils peuvent se déclencher
            en cours de bougie : on les cherche dans le haut et le bas, sinon un
            stop posé à -3 % ne servirait à rien sur une bougie qui plonge de
            10 % avant de revenir clôturer à -1 % ;
          - le RETOURNEMENT porte sur le score, qui n'existe qu'à la clôture ;
          - la DURÉE maximale referme ce qui reste ouvert.

        Le stop est examiné avant l'objectif : quand la même bougie touche les
        deux, on ne sait pas lequel a été atteint en premier, et retenir le pire
        des deux ne fait jamais paraître la stratégie meilleure qu'elle n'est.
        """
        achat = sens == "Achat"
        signe = 1 if achat else -1        # sens dans lequel on veut voir le prix aller

        prix_objectif = prix_stop = None
        if parametres.objectif_pct:
            prix_objectif = prix_entree * (1 + signe * parametres.objectif_pct / 100)
        if parametres.stop_pct:
            prix_stop = prix_entree * (1 - signe * parametres.stop_pct / 100)

        derniere = min(entree + parametres.duree_position, len(df) - 1)

        for barre in range(entree + 1, derniere + 1):
            haut = float(df["High"].iloc[barre])
            bas = float(df["Low"].iloc[barre])
            ouverture = float(df["Open"].iloc[barre])

            if prix_stop is not None and (bas <= prix_stop if achat else haut >= prix_stop):
                # Si la bougie ouvre déjà au-delà du stop, le prix demandé
                # n'existait plus : on sort à l'ouverture, moins bien.
                prix = min(prix_stop, ouverture) if achat else max(prix_stop, ouverture)
                return barre, prix, MOTIF_STOP

            if prix_objectif is not None and (
                haut >= prix_objectif if achat else bas <= prix_objectif
            ):
                prix = max(prix_objectif, ouverture) if achat else min(prix_objectif, ouverture)
                return barre, prix, MOTIF_OBJECTIF

            if parametres.retournement:
                score = scores.get(barre)
                # Écart au score d'entrée, compté dans le sens qui nous dessert.
                if score is not None and signe * (score - score_entree) <= -parametres.retournement:
                    return barre, float(df["Close"].iloc[barre]), MOTIF_RETOURNEMENT

        return derniere, float(df["Close"].iloc[derniere]), MOTIF_DUREE

    # -- Mise en forme ------------------------------------------------------
    @staticmethod
    def tableau(resultats: list[ResultatSimulation]) -> pd.DataFrame:
        """Une ligne par crypto, plus une ligne « Ensemble »."""
        lignes = []
        for resultat in resultats:
            if resultat.erreur:
                lignes.append({
                    "Crypto": resultat.symbole, "Trades": 0, "Réussite %": None,
                    "Capital final": None, "Gain": None, "Gain %": None,
                    "Marché %": None, "Écart %": None, "Détail": resultat.erreur,
                })
                continue
            lignes.append({
                "Crypto": resultat.symbole,
                "Trades": resultat.nb_trades,
                "Réussite %": (round(resultat.taux_reussite, 1)
                               if resultat.taux_reussite is not None else None),
                "Capital final": round(resultat.capital_final, 2),
                "Gain": round(resultat.gain, 2),
                "Gain %": round(resultat.gain_pct, 2),
                "Marché %": round(resultat.rendement_marche_pct, 2),
                "Écart %": (round(resultat.surperformance_pct, 2)
                            if resultat.surperformance_pct is not None else None),
                "Détail": "",
            })

        valides = [r for r in resultats if not r.erreur]
        if len(valides) > 1:
            initial = sum(r.capital_initial for r in valides)
            final = sum(r.capital_final for r in valides)
            marche = sum(r.rendement_marche_pct for r in valides) / len(valides)
            gain_pct = 100 * (final - initial) / initial if initial else 0
            trades = sum(r.nb_trades for r in valides)
            gagnants = sum(r.gagnants for r in valides)
            lignes.append({
                "Crypto": "Ensemble",
                "Trades": trades,
                "Réussite %": round(100 * gagnants / trades, 1) if trades else None,
                "Capital final": round(final, 2),
                "Gain": round(final - initial, 2),
                "Gain %": round(gain_pct, 2),
                "Marché %": round(marche, 2),
                "Écart %": round(gain_pct - marche, 2),
                "Détail": "",
            })
        return pd.DataFrame(lignes)

    @staticmethod
    def tableau_trades(resultats: list[ResultatSimulation]) -> pd.DataFrame:
        """
        Le détail de tous les allers-retours, du plus récent au plus ancien.

        Entrée et Sortie sont converties en heure de Paris : en interne
        (`Trade.entree` / `sortie`), tout reste en UTC, comme l'historique
        Binance dont elles proviennent. Le tri par « plus récent » se fait AVANT
        la conversion, sur les valeurs UTC — le résultat est identique dans les
        deux fuseaux, mais autant trier sur le référentiel natif.
        """
        lignes = [t.to_dict() for r in resultats for t in r.trades]
        if not lignes:
            return pd.DataFrame()
        table = pd.DataFrame(lignes).sort_values("Entrée", ascending=False).reset_index(drop=True)
        table["Entrée"] = pr.heure_fr(table["Entrée"])
        table["Sortie"] = pr.heure_fr(table["Sortie"])
        return table

    @staticmethod
    def repartition_sorties(resultats: list[ResultatSimulation]) -> dict:
        """Combien de positions chaque motif a refermées. Vide s'il n'y a rien."""
        comptes = {}
        for resultat in resultats:
            for trade in resultat.trades:
                comptes[trade.motif] = comptes.get(trade.motif, 0) + 1
        return {motif: comptes[motif] for motif in MOTIFS if motif in comptes}

    @staticmethod
    def courbes(resultats: list[ResultatSimulation]) -> pd.DataFrame:
        """
        Courbes de capital alignées sur un index commun, en pourcentage du
        capital initial — sinon deux cryptos de mises identiques mais de dates
        différentes ne seraient pas comparables.

        L'index (UTC en interne, comme `resultat.courbe`) est converti en heure
        de Paris avant de renvoyer : c'est ce tableau qui alimente directement
        le graphique de capital.
        """
        series = {}
        for resultat in resultats:
            if resultat.erreur or resultat.courbe is None or resultat.courbe.empty:
                continue
            series[resultat.symbole] = 100 * (resultat.courbe / resultat.capital_initial - 1)
        if not series:
            return pd.DataFrame()
        # Le capital ne change qu'aux sorties de position : entre deux, il reste
        # à son niveau, d'où le remplissage vers l'avant.
        table = pd.DataFrame(series).sort_index().ffill()
        table.index = pr.heure_fr(table.index)
        return table


def resume(resultats: list[ResultatSimulation], parametres: ParametresSimulation) -> str:
    """Phrase de synthèse affichable sous le tableau."""
    valides = [r for r in resultats if not r.erreur]
    if not valides:
        return "Aucune crypto n'a pu être simulée."

    initial = sum(r.capital_initial for r in valides)
    final = sum(r.capital_final for r in valides)
    trades = sum(r.nb_trades for r in valides)
    marche = sum(r.rendement_marche_pct for r in valides) / len(valides)
    gain_pct = 100 * (final - initial) / initial if initial else 0

    return (
        f"{pr.formater_prix(initial)} misés sur {len(valides)} crypto(s) seraient devenus "
        f"{pr.formater_prix(final)} ({gain_pct:+.2f} %) en {trades} allers-retours. "
        f"Achat-conservation sur la même période : {marche:+.2f} %."
    )
