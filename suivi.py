"""
Suivi des performances : les scores produits valent-ils quelque chose ?

Principe : à chaque analyse, on enregistre une photographie de tous les scores
dans un classeur Excel. Chaque relevé porte une ÉCHÉANCE (l'horodatage plus
quelques bougies). Lors d'une analyse ultérieure, tous les relevés dont
l'échéance est passée sont confrontés au prix réellement observé, et le résultat
est classé « Correct », « Incorrect » ou « Indécis ».

Le classeur compte quatre onglets, pour ne pas surcharger le premier :

  Relevés        journal brut, une ligne par crypto et par analyse ;
  Vérifications  les relevés arrivés à échéance, avec leur résultat ;
  Performance    les taux de réussite agrégés — l'onglet qui répond à la question ;
  Évolution      le score global au fil du temps, en tableau croisé prêt à tracer.

Le prix d'échéance est retrouvé dans l'historique OHLCV déjà téléchargé par
l'analyse : on lit la bougie correspondant à l'échéance, et non le prix du
moment. La vérification est donc exacte, même longtemps après coup.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pandas as pd

import config
from indicateurs import Categorie

# --- Colonnes des trois onglets -------------------------------------------
COLONNES_RELEVES = [
    "id", "horodatage", "symbole", "nom", "intervalle", "horizon_minutes", "echeance",
    "prix", "score", "synthese", "sens_predit",
    "score_tendance", "score_momentum", "score_volatilite", "score_volume",
    "nb_indicateurs", "indicateurs",
    "criteres_positifs", "criteres_neutres", "criteres_negatifs",
    "origine", "statut",
]

COLONNES_VERIFICATIONS = [
    "id", "horodatage", "symbole", "intervalle", "horizon_minutes",
    "score", "sens_predit", "prix_initial",
    "verifie_le", "prix_final", "rendement_pct",
    "rendement_marche_pct", "rendement_relatif_pct",
    "sens_reel", "resultat", "precision_prix",
]

# Les scores traçables : le score global et les quatre scores de famille.
# Les clés sont les libellés affichés, les valeurs les colonnes du journal.
TYPES_SCORE = {
    "Global": "score",
    "Tendance": "score_tendance",
    "Momentum": "score_momentum",
    "Volatilité": "score_volatilite",
    "Volume": "score_volume",
}

STATUT_ATTENTE = "En attente"
STATUT_VERIFIE = "Vérifié"
STATUT_EXPIRE = "Expiré"

# Tranches de score utilisées par l'onglet Performance. C'est LE découpage qui
# répond à « un score élevé prédit-il mieux qu'un score faible ? ».
TRANCHES_SCORE = [
    (-1.01, -0.50, "Fortement négatif (≤ -0.50)"),
    (-0.50, -0.15, "Négatif (-0.50 à -0.15)"),
    (-0.15, 0.15, "Neutre (-0.15 à +0.15)"),
    (0.15, 0.50, "Positif (+0.15 à +0.50)"),
    (0.50, 1.01, "Fortement positif (≥ +0.50)"),
]


# ===========================================================================
# QUALIFICATION
# ===========================================================================
def sens_du_score(score: float) -> str:
    """Direction annoncée par un score. En deçà du seuil, l'application ne dit rien."""
    if score >= config.SEUIL_PREDICTION:
        return "Hausse"
    if score <= -config.SEUIL_PREDICTION:
        return "Baisse"
    return "Neutre"


def sens_du_rendement(rendement: float) -> str:
    """Direction réellement observée. Un micro-mouvement est traité comme du bruit."""
    if rendement >= config.SEUIL_MOUVEMENT:
        return "Hausse"
    if rendement <= -config.SEUIL_MOUVEMENT:
        return "Baisse"
    return "Stable"


def qualifier_resultat(sens_predit: str, sens_reel: str) -> str:
    """
    Confronte l'annonce et la réalité.

    « Non prédictif » et « Indécis » sont volontairement distincts de l'échec :
    compter comme une erreur un score neutre, ou un marché qui n'a pas bougé,
    fausserait le taux de réussite dans les deux sens.
    """
    if sens_predit == "Neutre":
        return "Non prédictif"
    if sens_reel == "Stable":
        return "Indécis"
    return "Correct" if sens_predit == sens_reel else "Incorrect"


def horizon_minutes(intervalle: str, bougies: int | None = None) -> int:
    """Durée après laquelle un score est évalué, en minutes."""
    bougies = config.HORIZON_BOUGIES if bougies is None else bougies
    return int(config.MINUTES_PAR_INTERVALLE.get(intervalle, 1440) * bougies)


# ===========================================================================
# JOURNAL
# ===========================================================================
class JournalSuivi:
    """
    Le classeur de suivi et les opérations qui l'alimentent.

        journal = JournalSuivi()
        journal.enregistrer(resultats, "1d", codes, origine="analyse")
        journal.verifier(historiques=analyseur.historiques)
        journal.sauvegarder()
    """

    def __init__(self, chemin: str | None = None):
        self.chemin = chemin or config.FICHIER_SUIVI
        self.releves = pd.DataFrame(columns=COLONNES_RELEVES)
        self.verifications = pd.DataFrame(columns=COLONNES_VERIFICATIONS)
        self.charger()

    # -- Lecture / écriture -------------------------------------------------
    def charger(self) -> bool:
        """Relit le classeur s'il existe. Un fichier absent n'est pas une erreur."""
        if not os.path.exists(self.chemin):
            return False
        try:
            classeur = pd.read_excel(self.chemin, sheet_name=None)
        except Exception:
            return False  # classeur illisible : on repart d'un journal vide

        for nom, colonnes, attribut in (
            ("Relevés", COLONNES_RELEVES, "releves"),
            ("Vérifications", COLONNES_VERIFICATIONS, "verifications"),
        ):
            table = classeur.get(nom)
            if table is None:
                continue
            # Les colonnes manquantes sont recréées : le format peut avoir
            # évolué depuis la création du fichier.
            for colonne in colonnes:
                if colonne not in table.columns:
                    table[colonne] = pd.NA
            for colonne in ("horodatage", "echeance", "verifie_le"):
                if colonne in table.columns:
                    table[colonne] = pd.to_datetime(table[colonne], errors="coerce")
            setattr(self, attribut, table[colonnes])
        return True

    def sauvegarder(self) -> tuple[bool, str]:
        """
        Écrit les trois onglets. L'échec le plus courant est un classeur resté
        ouvert dans Excel : on le dit explicitement plutôt que de lever.
        """
        try:
            with pd.ExcelWriter(self.chemin, engine="openpyxl") as writer:
                self.releves.to_excel(writer, sheet_name="Relevés", index=False)
                self.verifications.to_excel(writer, sheet_name="Vérifications", index=False)
                self.performance().to_excel(writer, sheet_name="Performance", index=False)
                self.evolution_pour_excel().to_excel(
                    writer, sheet_name="Évolution", index=False
                )
                _ajuster_colonnes(writer)
        except PermissionError:
            return False, (
                f"{self.chemin} est ouvert dans Excel : fermez-le puis relancez "
                "pour que le suivi soit enregistré."
            )
        except Exception as e:
            return False, f"Écriture impossible : {type(e).__name__} — {e}"
        return True, f"Suivi enregistré ({len(self.releves)} relevés) dans {self.chemin}."

    # -- 1. Enregistrement --------------------------------------------------
    def enregistrer(self, resultats, intervalle: str, codes: list[str] | None = None,
                    origine: str = "analyse", horodatage: datetime | None = None) -> int:
        """
        Ajoute une photographie des scores. Renvoie le nombre de relevés ajoutés.

        Les cryptos sans score exploitable sont ignorées : les enregistrer
        polluerait le journal de lignes invérifiables.
        """
        horodatage = (horodatage or datetime.now()).replace(microsecond=0)
        duree = horizon_minutes(intervalle)
        echeance = horodatage + timedelta(minutes=duree)
        liste_codes = ",".join(codes) if codes else ""

        lignes = []
        for resultat in resultats:
            if not resultat.indicateurs_notes or not resultat.prix:
                continue
            compte = resultat.compter_signaux()
            score = round(resultat.score_global, 4)
            scores_familles = {
                f"score_{_cle(categorie)}": _arrondir(resultat.score_categorie(categorie))
                for categorie in Categorie
            }
            lignes.append(
                {
                    # L'identifiant reste lisible dans Excel et garantit l'unicité
                    # d'un relevé (une crypto ne peut apparaître qu'une fois par analyse).
                    "id": f"{horodatage:%Y%m%d-%H%M%S}-{resultat.symbole}",
                    "horodatage": horodatage,
                    "symbole": resultat.symbole,
                    "nom": resultat.nom,
                    "intervalle": intervalle,
                    "horizon_minutes": duree,
                    "echeance": echeance,
                    "prix": resultat.prix,
                    "score": score,
                    "synthese": resultat.synthese,
                    "sens_predit": sens_du_score(score),
                    **scores_familles,
                    "nb_indicateurs": len(resultat.indicateurs_notes),
                    "indicateurs": liste_codes,
                    "criteres_positifs": compte["positifs"],
                    "criteres_neutres": compte["neutres"],
                    "criteres_negatifs": compte["negatifs"],
                    "origine": origine,
                    "statut": STATUT_ATTENTE,
                }
            )

        if not lignes:
            return 0

        nouveaux = pd.DataFrame(lignes, columns=COLONNES_RELEVES)
        self.releves = (
            nouveaux if self.releves.empty
            else pd.concat([self.releves, nouveaux], ignore_index=True)
        )
        # Un même identifiant ne doit exister qu'une fois (double clic sur
        # « Analyser » dans la même seconde).
        self.releves = self.releves.drop_duplicates(subset="id", keep="last")
        return len(lignes)

    # -- 2. Vérification ----------------------------------------------------
    def verifier(self, historiques: dict[str, pd.DataFrame] | None = None,
                 source=None, maintenant: datetime | None = None) -> dict:
        """
        Confronte les relevés arrivés à échéance au prix réellement observé.

        `historiques` : les DataFrames déjà téléchargés par l'analyse (gratuits).
        `source`      : permet de récupérer ce qui manque, si on l'autorise.

        Renvoie un petit bilan {verifies, expires, en_attente}.
        """
        historiques = historiques or {}
        maintenant = maintenant or datetime.now()
        bilan = {"verifies": 0, "expires": 0, "en_attente": 0}

        if self.releves.empty:
            return bilan

        en_attente = self.releves[self.releves["statut"] == STATUT_ATTENTE]
        nouvelles = []

        for index, releve in en_attente.iterrows():
            echeance = releve["echeance"]
            if pd.isna(echeance) or echeance > maintenant:
                bilan["en_attente"] += 1
                continue

            df = self._historique_pour(releve, historiques, source)
            duree = int(releve["horizon_minutes"] or 0)
            prix_final, precision = _prix_a_echeance(df, echeance, duree, releve["intervalle"])

            if prix_final is None:
                # Soit l'historique ne remonte pas encore jusqu'à l'échéance,
                # soit sa fenêtre l'a définitivement dépassée.
                limite = echeance + timedelta(minutes=duree * config.FACTEUR_EXPIRATION)
                if maintenant > limite or precision == "hors fenêtre":
                    self.releves.at[index, "statut"] = STATUT_EXPIRE
                    bilan["expires"] += 1
                else:
                    bilan["en_attente"] += 1
                continue

            prix_initial = float(releve["prix"])
            rendement = (prix_final - prix_initial) / prix_initial
            sens_reel = sens_du_rendement(rendement)

            nouvelles.append(
                {
                    "id": releve["id"],
                    "horodatage": releve["horodatage"],
                    "symbole": releve["symbole"],
                    "intervalle": releve["intervalle"],
                    "horizon_minutes": duree,
                    "score": releve["score"],
                    "sens_predit": releve["sens_predit"],
                    "prix_initial": prix_initial,
                    "verifie_le": maintenant.replace(microsecond=0),
                    "prix_final": prix_final,
                    "rendement_pct": round(rendement * 100, 4),
                    "rendement_marche_pct": None,   # calculé juste après, par lot
                    "rendement_relatif_pct": None,
                    "sens_reel": sens_reel,
                    "resultat": qualifier_resultat(releve["sens_predit"], sens_reel),
                    "precision_prix": precision,
                }
            )
            self.releves.at[index, "statut"] = STATUT_VERIFIE
            bilan["verifies"] += 1

        if nouvelles:
            ajout = pd.DataFrame(nouvelles, columns=COLONNES_VERIFICATIONS)
            self.verifications = (
                ajout if self.verifications.empty
                else pd.concat([self.verifications, ajout], ignore_index=True)
            )
            self.verifications = self.verifications.drop_duplicates(subset="id", keep="last")
            self._calculer_rendements_relatifs()

        return bilan

    def _historique_pour(self, releve, historiques, source):
        """
        Retrouve les bougies permettant de dater le prix d'échéance.

        Les bougies déjà en mémoire sont prioritaires (gratuites), mais elles ne
        conviennent que si leur fenêtre COUVRE réellement l'échéance. Sans cette
        vérification, un relevé journalier serait confronté aux 1000 dernières
        bougies d'une minute — soit 17 heures d'historique — et déclaré
        invérifiable alors que la donnée existe.
        """
        symbole, echeance = releve["symbole"], releve["echeance"]
        df = historiques.get(symbole)
        if df is not None and not df.empty and df.index[0] <= echeance <= df.index[-1]:
            return df

        if source is None:
            return df  # au mieux ce dont on dispose
        try:
            # On redescend à la source dans l'intervalle D'ORIGINE du relevé.
            recharge = source.historique(symbole, releve["intervalle"])
            return recharge if recharge is not None and not recharge.empty else df
        except Exception:
            return df

    def _calculer_rendements_relatifs(self):
        """
        Situe chaque rendement par rapport à celui de son lot d'analyse.

        C'est le test le plus honnête : si tout le marché a pris 3 %, une crypto
        bien notée qui prend 3 % n'a rien démontré. Le rendement relatif isole ce
        que le score a réellement apporté.
        """
        if self.verifications.empty:
            return
        lots = self.verifications.groupby(["horodatage", "intervalle"])["rendement_pct"]
        moyennes = lots.transform("mean")
        self.verifications["rendement_marche_pct"] = moyennes.round(4)
        self.verifications["rendement_relatif_pct"] = (
            self.verifications["rendement_pct"] - moyennes
        ).round(4)

    # -- 3. Performance -----------------------------------------------------
    def performance(self) -> pd.DataFrame:
        """
        Agrège les vérifications en un tableau unique, découpé par regroupement.

        Un seul tableau plutôt que plusieurs blocs : c'est filtrable directement
        dans Excel, et la structure reste lisible.
        """
        colonnes = [
            "Regroupement", "Catégorie", "Vérifications", "Corrects", "Incorrects",
            "Indécis", "Non prédictifs", "Taux de réussite %",
            "Rendement moyen %", "Rendement relatif moyen %",
        ]
        if self.verifications.empty:
            return pd.DataFrame(columns=colonnes)

        table = self.verifications

        # Le rendement relatif mesure l'écart à la moyenne du lot d'analyse. Sur
        # un regroupement qui contient des lots ENTIERS (le bilan global, ou un
        # intervalle donné), cette moyenne d'écarts vaut zéro par construction :
        # l'afficher laisserait croire à un résultat, alors qu'elle ne mesure
        # rien. On ne la calcule donc que là où elle a un sens.
        lignes = [_agreger(table, "Global", "Toutes vérifications", relatif=False)]

        # Par tranche de score : la question centrale du suivi.
        for borne_basse, borne_haute, libelle in TRANCHES_SCORE:
            sous = table[(table["score"] >= borne_basse) & (table["score"] < borne_haute)]
            if not sous.empty:
                lignes.append(_agreger(sous, "Tranche de score", libelle))

        # Intervalles puis cryptos, les plus souvent vérifiés en tête.
        for colonne, regroupement, relatif in (
            ("intervalle", "Intervalle", False),
            ("symbole", "Crypto", True),
        ):
            groupes = sorted(table.groupby(colonne), key=lambda g: -len(g[1]))
            lignes += [
                _agreger(sous, regroupement, str(valeur), relatif=relatif)
                for valeur, sous in groupes
            ]

        # Aucun tri global ensuite : l'ordre de construction est déjà le bon
        # (les tranches de score doivent se lire du plus baissier au plus haussier,
        # un tri par volume les mélangerait).
        return pd.DataFrame(lignes, columns=colonnes)

    # -- 4. Évolution des scores -------------------------------------------
    def intervalles_suivis(self) -> list[str]:
        """Intervalles présents dans le journal, le plus fréquent en premier."""
        if self.releves.empty:
            return []
        return list(self.releves["intervalle"].value_counts().index)

    def symboles_suivis(self, intervalle: str | None = None) -> list[str]:
        """Cryptos présentes dans le journal, les plus souvent relevées d'abord."""
        table = self.releves
        if table.empty:
            return []
        if intervalle:
            table = table[table["intervalle"] == intervalle]
        return list(table["symbole"].value_counts().index)

    def evolution(self, type_score: str = "Global", symboles: list[str] | None = None,
                  intervalle: str | None = None) -> pd.DataFrame:
        """
        Tableau croisé de l'évolution d'un score : une ligne par horodatage,
        une colonne par crypto.

        Un intervalle doit être choisi : superposer des scores journaliers et des
        scores en 5 minutes sur un même axe mélangerait deux échelles de temps,
        et deux relevés simultanés de la même crypto se marcheraient dessus.
        """
        colonne = TYPES_SCORE.get(type_score, "score")
        table = self.releves
        if table.empty or colonne not in table.columns:
            return pd.DataFrame()

        if intervalle:
            table = table[table["intervalle"] == intervalle]
        if symboles:
            table = table[table["symbole"].isin(symboles)]
        table = table.dropna(subset=["horodatage", colonne])
        if table.empty:
            return pd.DataFrame()

        # `last` et non `mean` : deux relevés d'une même crypto au même instant
        # seraient un doublon d'exécution, pas deux mesures à moyenner.
        croise = table.pivot_table(
            index="horodatage", columns="symbole", values=colonne, aggfunc="last"
        )
        return croise.sort_index()

    def evolution_pour_excel(self) -> pd.DataFrame:
        """
        Version à plat du score global pour l'onglet Excel : horodatage et
        intervalle en colonnes, une colonne par crypto. Prête à être
        sélectionnée d'un bloc pour insérer un graphique dans Excel.
        """
        if self.releves.empty:
            return pd.DataFrame(columns=["horodatage", "intervalle"])

        table = self.releves.dropna(subset=["horodatage"])
        croise = table.pivot_table(
            index=["horodatage", "intervalle"], columns="symbole",
            values="score", aggfunc="last",
        )
        return croise.sort_index().reset_index()

    # -- Raccourcis ---------------------------------------------------------
    def resume(self) -> str:
        """Phrase d'état, affichable dans une barre de statut."""
        attente = int((self.releves["statut"] == STATUT_ATTENTE).sum()) if not self.releves.empty else 0
        if self.verifications.empty:
            return f"Suivi : {len(self.releves)} relevés, {attente} en attente d'échéance."
        global_ = _agreger(self.verifications, "Global", "Toutes")
        taux = global_["Taux de réussite %"]
        return (
            f"Suivi : {len(self.verifications)} vérifications, "
            f"{taux if taux is not None else '—'} % de réussite, {attente} en attente."
        )


# ===========================================================================
# OUTILS INTERNES
# ===========================================================================
def _cle(categorie: Categorie) -> str:
    """Nom de colonne sans accent ni majuscule pour une catégorie."""
    return {
        Categorie.TENDANCE: "tendance",
        Categorie.MOMENTUM: "momentum",
        Categorie.VOLATILITE: "volatilite",
        Categorie.VOLUME: "volume",
    }[categorie]


def _arrondir(valeur):
    return None if valeur is None else round(valeur, 4)


def _prix_a_echeance(df, echeance, duree_minutes: int, intervalle: str):
    """
    Clôture de la première bougie située à ou après l'échéance.

    Renvoie (prix, précision) où précision vaut :
      "exacte"       la bougie tombe pile sur l'échéance (à une bougie près) ;
      "approchée"    la bougie suivante est un peu tardive, mais utilisable ;
      "hors fenêtre" l'historique commence après l'échéance : inexploitable ;
      None + "attente" l'historique ne va pas encore jusqu'à l'échéance.
    """
    if df is None or df.empty:
        return None, "attente"

    posterieures = df.index[df.index >= echeance]
    if len(posterieures) == 0:
        return None, "attente"  # l'échéance est postérieure à la dernière bougie

    date = posterieures[0]
    retard = date - echeance
    pas = timedelta(minutes=config.MINUTES_PAR_INTERVALLE.get(intervalle, 1440))

    if retard <= pas:
        return float(df.loc[date, "Close"]), "exacte"
    if retard <= timedelta(minutes=max(duree_minutes, 1)):
        # Bougie manquante ou historique légèrement tronqué : acceptable, mais signalé.
        return float(df.loc[date, "Close"]), "approchée"
    # La fenêtre téléchargée a dépassé l'échéance (typique des bougies d'une
    # minute : 1000 bougies ne couvrent que 17 heures).
    return None, "hors fenêtre"


def _agreger(table: pd.DataFrame, regroupement: str, categorie: str,
             relatif: bool = True) -> dict:
    """
    Statistiques d'un sous-ensemble de vérifications.

    `relatif=False` masque le rendement relatif, sans objet lorsque le
    regroupement contient des lots d'analyse entiers (cf. performance()).
    """
    corrects = int((table["resultat"] == "Correct").sum())
    incorrects = int((table["resultat"] == "Incorrect").sum())
    indecis = int((table["resultat"] == "Indécis").sum())
    non_predictifs = int((table["resultat"] == "Non prédictif").sum())

    # Le taux ne se calcule que sur les cas tranchés : inclure les indécis et
    # les scores neutres le tirerait mécaniquement vers le bas.
    tranches = corrects + incorrects
    taux = round(100 * corrects / tranches, 1) if tranches else None

    return {
        "Regroupement": regroupement,
        "Catégorie": categorie,
        "Vérifications": len(table),
        "Corrects": corrects,
        "Incorrects": incorrects,
        "Indécis": indecis,
        "Non prédictifs": non_predictifs,
        "Taux de réussite %": taux,
        "Rendement moyen %": round(table["rendement_pct"].mean(), 3),
        "Rendement relatif moyen %": (
            round(table["rendement_relatif_pct"].mean(), 3)
            if relatif and table["rendement_relatif_pct"].notna().any() else None
        ),
    }


def _ajuster_colonnes(writer):
    """Largeur de colonne lisible à l'ouverture, sans avoir à tout redimensionner."""
    for feuille in writer.book.worksheets:
        for colonnes in feuille.columns:
            lettre = colonnes[0].column_letter
            largeur = max(
                (len(str(cellule.value)) for cellule in colonnes if cellule.value is not None),
                default=10,
            )
            feuille.column_dimensions[lettre].width = min(max(largeur + 2, 10), 34)
        feuille.freeze_panes = "A2"
