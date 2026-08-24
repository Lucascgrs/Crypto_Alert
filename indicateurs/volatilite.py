"""
Indicateurs de VOLATILITÉ : le marché est-il calme ou agité, comprimé ou étendu ?

4 indicateurs : bandes de Bollinger, ATR, canaux de Keltner, canal de Donchian.

Particularité de cette famille : beaucoup de ses critères sont NON DIRECTIONNELS
(`directionnel=False`). Savoir que les bandes sont resserrées est une information
de contexte capitale, mais elle ne dit pas si le marché va monter ou baisser.
Ces critères sont donc affichés sans peser sur le score.
"""

from __future__ import annotations

import math

import pandas as pd

from .base import (
    Categorie,
    Indicateur,
    Signal,
    critere_choix,
    critere_paliers,
)
from .outils import (
    atr,
    bandes_bollinger,
    derniere,
    ecart_relatif,
    ema,
    pente,
    rang_percentile,
)

# Grille commune aux critères « largeur / niveau de volatilité », exprimée en
# rang-percentile (0 = le plus calme de l'historique, 1 = le plus agité).
# Un rang est indispensable ici : il n'existe aucun seuil universel de largeur
# de bande valable à la fois pour le BTC et pour un altcoin volatil.
PALIERS_RANG_VOLATILITE = [
    (0.15, "Compression extrême (les plus calmes de l'historique)", Signal.NEUTRE),
    (0.35, "Resserrement marqué", Signal.NEUTRE),
    (0.65, "Amplitude normale", Signal.NEUTRE),
    (0.85, "Expansion marquée", Signal.NEUTRE),
    (math.inf, "Expansion extrême (les plus agités de l'historique)", Signal.NEUTRE),
]


# ===========================================================================
# 1. BANDES DE BOLLINGER
# ===========================================================================
class Bollinger(Indicateur):
    """Enveloppe statistique autour d'une moyenne mobile. Deux lectures
    complémentaires : OÙ est le prix dans les bandes, et QUELLE est leur largeur."""

    code = "BOLLINGER"
    nom = "Bandes de Bollinger (20, 2)"
    categorie = Categorie.VOLATILITE
    description = (
        "Position du prix dans les bandes (au-dessus, au milieu, en dessous), "
        "largeur des bandes (resserrement / expansion) et sens de cette largeur."
    )
    periodes_min = 60
    PARAMETRES_DEFAUT = {
        "periode": 20,
        "ecarts": 2.0,
        "fenetre_rang": 250,  # historique de référence pour juger « resserré »
        "fenetre_pente": 5,
    }

    def calculer(self, df):
        basse, mediane, haute = bandes_bollinger(df["Close"], self.p("periode"), self.p("ecarts"))
        amplitude = (haute - basse).replace(0, float("nan"))

        # %B : 0 = sur la bande basse, 0,5 = sur la médiane, 1 = sur la bande haute.
        pourcent_b = (df["Close"] - basse) / amplitude
        # Largeur rapportée à la médiane, donc comparable entre cryptos.
        largeur = amplitude / mediane

        return pd.DataFrame(
            {
                "BB_basse": basse,
                "BB_mediane": mediane,
                "BB_haute": haute,
                "BB_pourcent_b": pourcent_b,
                "BB_largeur": largeur,
                "BB_largeur_rang": rang_percentile(largeur, self.p("fenetre_rang")),
            },
            index=df.index,
        )

    def interpreter(self, df, calc):
        return [
            # 1. LA question posée au tableau de bord : le prix est-il au-dessus,
            #    au milieu, ou en dessous des bandes ?
            #    Nuance importante : TOUCHER une bande, c'est du momentum (le prix
            #    « longe » la bande dans une tendance saine) ; seule une clôture
            #    À L'EXTÉRIEUR des bandes constitue un excès statistique et
            #    bascule donc en lecture contrarienne.
            critere_paliers(
                "BB_POSITION",
                "Position dans les bandes",
                derniere(calc["BB_pourcent_b"]),
                [
                    (0.0, "Sous la bande inférieure (excès baissier, rebond probable)", Signal.POSITIF),
                    (0.20, "Contre la bande inférieure", Signal.TRES_NEGATIF),
                    (0.45, "Moitié basse des bandes", Signal.NEGATIF),
                    (0.55, "Au milieu des bandes", Signal.NEUTRE),
                    (0.80, "Moitié haute des bandes", Signal.POSITIF),
                    (1.0, "Contre la bande supérieure", Signal.TRES_POSITIF),
                    (math.inf, "Au-dessus de la bande supérieure (excès haussier, reflux probable)", Signal.NEGATIF),
                ],
            ),
            # 2. Position vis-à-vis de la médiane, lue en tendance cette fois.
            critere_paliers(
                "BB_MEDIANE",
                "Prix vs bande médiane",
                ecart_relatif(derniere(df["Close"]), derniere(calc["BB_mediane"])),
                [
                    (-0.04, "Nettement sous la médiane", Signal.TRES_NEGATIF),
                    (-0.004, "Sous la médiane", Signal.NEGATIF),
                    (0.004, "Sur la médiane", Signal.NEUTRE),
                    (0.04, "Au-dessus de la médiane", Signal.POSITIF),
                    (math.inf, "Nettement au-dessus de la médiane", Signal.TRES_POSITIF),
                ],
            ),
            # 3. Resserrement / expansion : contexte, pas direction.
            critere_paliers(
                "BB_LARGEUR",
                "Largeur des bandes",
                derniere(calc["BB_largeur_rang"]),
                PALIERS_RANG_VOLATILITE,
                directionnel=False,
            ),
            # 4. Sens de variation de la largeur : une compression qui s'ouvre
            #    annonce souvent le départ d'un mouvement.
            critere_paliers(
                "BB_DYNAMIQUE",
                "Évolution de la largeur",
                derniere(pente(calc["BB_largeur"], self.p("fenetre_pente"))),
                [
                    (-0.15, "Bandes en forte contraction", Signal.NEUTRE),
                    (-0.03, "Bandes en contraction", Signal.NEUTRE),
                    (0.03, "Largeur stable", Signal.NEUTRE),
                    (0.15, "Bandes en expansion", Signal.NEUTRE),
                    (math.inf, "Bandes en forte expansion (mouvement en cours)", Signal.NEUTRE),
                ],
                directionnel=False,
            ),
        ]


# ===========================================================================
# 2. ATR
# ===========================================================================
class AtrIndicateur(Indicateur):
    """Amplitude moyenne réelle : la mesure de référence du risque d'un actif.
    Rapportée au prix, elle se compare d'une crypto à l'autre."""

    code = "ATR"
    nom = "ATR (14)"
    categorie = Categorie.VOLATILITE
    description = (
        "Volatilité moyenne exprimée en pourcentage du prix, située dans son "
        "propre historique (marché calme ou agité) et son sens d'évolution."
    )
    periodes_min = 60
    PARAMETRES_DEFAUT = {"periode": 14, "fenetre_rang": 250, "fenetre_pente": 10}

    def calculer(self, df):
        atr_pourcent = atr(df, self.p("periode")) / df["Close"]
        return pd.DataFrame(
            {
                "ATR_pourcent": atr_pourcent,
                "ATR_rang": rang_percentile(atr_pourcent, self.p("fenetre_rang")),
            },
            index=df.index,
        )

    def interpreter(self, df, calc):
        return [
            # Niveau absolu : parle immédiatement à l'utilisateur ("3 % par jour").
            critere_paliers(
                "ATR_NIVEAU",
                "Volatilité quotidienne moyenne",
                derniere(calc["ATR_pourcent"]),
                [
                    (0.015, "Volatilité faible (moins de 1,5 % par bougie)", Signal.NEUTRE),
                    (0.03, "Volatilité modérée", Signal.NEUTRE),
                    (0.06, "Volatilité élevée", Signal.NEUTRE),
                    (math.inf, "Volatilité très élevée (plus de 6 % par bougie)", Signal.NEUTRE),
                ],
                directionnel=False,
            ),
            # Niveau relatif : où se situe cette volatilité dans son historique.
            critere_paliers(
                "ATR_REGIME",
                "Régime de volatilité",
                derniere(calc["ATR_rang"]),
                PALIERS_RANG_VOLATILITE,
                directionnel=False,
            ),
            critere_paliers(
                "ATR_DYNAMIQUE",
                "Évolution de la volatilité",
                derniere(pente(calc["ATR_pourcent"], self.p("fenetre_pente"))),
                [
                    (-0.25, "Volatilité en net repli (marché qui se calme)", Signal.NEUTRE),
                    (-0.05, "Volatilité en repli", Signal.NEUTRE),
                    (0.05, "Volatilité stable", Signal.NEUTRE),
                    (0.25, "Volatilité en hausse", Signal.NEUTRE),
                    (math.inf, "Volatilité en forte hausse (tension)", Signal.NEUTRE),
                ],
                directionnel=False,
            ),
        ]


# ===========================================================================
# 3. CANAUX DE KELTNER
# ===========================================================================
class Keltner(Indicateur):
    """Canal basé sur l'ATR (et non l'écart-type). Croisé avec Bollinger, il
    donne le « squeeze », l'une des configurations de compression les plus suivies."""

    code = "KELTNER"
    nom = "Canaux de Keltner (20, 2×ATR)"
    categorie = Categorie.VOLATILITE
    description = (
        "Position du prix dans le canal ATR, sorties de canal (accélération) et "
        "détection du squeeze (bandes de Bollinger contenues dans le canal)."
    )
    periodes_min = 70
    PARAMETRES_DEFAUT = {
        "periode": 20,
        "periode_atr": 10,
        "multiplicateur": 2.0,
        "periode_bollinger": 20,
        "ecarts_bollinger": 2.0,
    }

    def calculer(self, df):
        milieu = ema(df["Close"], self.p("periode"))
        marge = self.p("multiplicateur") * atr(df, self.p("periode_atr"))
        haute, basse = milieu + marge, milieu - marge

        # Bollinger recalculé ici pour rendre l'indicateur autonome (le squeeze
        # a besoin des deux enveloppes en même temps).
        bb_basse, _, bb_haute = bandes_bollinger(
            df["Close"], self.p("periode_bollinger"), self.p("ecarts_bollinger")
        )

        return pd.DataFrame(
            {
                "KC_basse": basse,
                "KC_milieu": milieu,
                "KC_haute": haute,
                "KC_position": (df["Close"] - basse) / ((haute - basse).replace(0, float("nan"))),
                # Squeeze : les bandes de Bollinger rentrent dans le canal de Keltner.
                "Squeeze": (bb_haute < haute) & (bb_basse > basse),
            },
            index=df.index,
        )

    def interpreter(self, df, calc):
        squeeze_actif = bool(calc["Squeeze"].iloc[-1])
        # Depuis combien de bougies le squeeze dure-t-il / est-il retombé ?
        serie_squeeze = calc["Squeeze"].iloc[-10:]
        squeeze_relache = (not squeeze_actif) and bool(serie_squeeze.iloc[:-1].any())

        if squeeze_actif:
            etat_squeeze = "actif"
        elif squeeze_relache:
            etat_squeeze = "relache"
        else:
            etat_squeeze = "absent"

        return [
            critere_paliers(
                "KC_POSITION",
                "Position dans le canal de Keltner",
                derniere(calc["KC_position"]),
                [
                    (0.0, "Sous le canal (accélération baissière)", Signal.TRES_NEGATIF),
                    (0.35, "Partie basse du canal", Signal.NEGATIF),
                    (0.65, "Centre du canal", Signal.NEUTRE),
                    (1.0, "Partie haute du canal", Signal.POSITIF),
                    (math.inf, "Au-dessus du canal (accélération haussière)", Signal.TRES_POSITIF),
                ],
            ),
            critere_choix(
                "KC_SQUEEZE",
                "Squeeze Bollinger / Keltner",
                etat_squeeze,
                {
                    "actif": ("Squeeze actif : compression, sortie de range à venir", Signal.NEUTRE),
                    "relache": ("Squeeze relâché : mouvement en train de démarrer", Signal.NEUTRE),
                    "absent": ("Pas de compression particulière", Signal.NEUTRE),
                },
                directionnel=False,
            ),
        ]


# ===========================================================================
# 4. CANAL DE DONCHIAN
# ===========================================================================
class Donchian(Indicateur):
    """Le plus haut et le plus bas de N périodes. Base historique des systèmes
    de cassure (« turtle trading ») et lecture immédiate de la position."""

    code = "DONCHIAN"
    nom = "Canal de Donchian (20)"
    categorie = Categorie.VOLATILITE
    description = (
        "Position du prix entre le plus haut et le plus bas de la période, et "
        "détection des cassures de range (nouveaux extrêmes)."
    )
    periodes_min = 60
    PARAMETRES_DEFAUT = {"periode": 20, "fenetre_cassure": 3}

    def calculer(self, df):
        periode = self.p("periode")
        haut = df["High"].rolling(periode).max()
        bas = df["Low"].rolling(periode).min()
        return pd.DataFrame(
            {
                "DC_haut": haut,
                "DC_bas": bas,
                "DC_position": (df["Close"] - bas) / ((haut - bas).replace(0, float("nan"))),
                # Extrêmes de la période PRÉCÉDENTE : sinon la bougie du jour
                # fait partie du maximum et aucune cassure n'est jamais détectée.
                "DC_haut_ref": haut.shift(1),
                "DC_bas_ref": bas.shift(1),
            },
            index=df.index,
        )

    def interpreter(self, df, calc):
        fenetre = self.p("fenetre_cassure")
        recents = df.iloc[-fenetre:]
        ref = calc.iloc[-fenetre:]

        cassure_haute = bool((recents["High"] > ref["DC_haut_ref"]).any())
        cassure_basse = bool((recents["Low"] < ref["DC_bas_ref"]).any())
        if cassure_haute and not cassure_basse:
            cassure = "haute"
        elif cassure_basse and not cassure_haute:
            cassure = "basse"
        elif cassure_haute and cassure_basse:
            cassure = "double"
        else:
            cassure = "aucune"

        return [
            critere_paliers(
                "DC_POSITION",
                "Position dans le range",
                derniere(calc["DC_position"]),
                [
                    (0.10, "Sur les plus bas de la période", Signal.TRES_NEGATIF),
                    (0.35, "Partie basse du range", Signal.NEGATIF),
                    (0.65, "Milieu du range", Signal.NEUTRE),
                    (0.90, "Partie haute du range", Signal.POSITIF),
                    (math.inf, "Sur les plus hauts de la période", Signal.TRES_POSITIF),
                ],
            ),
            critere_choix(
                "DC_CASSURE",
                "Cassure de range",
                cassure,
                {
                    "haute": (f"Nouveau plus haut sur {self.p('periode')} bougies", Signal.TRES_POSITIF),
                    "basse": (f"Nouveau plus bas sur {self.p('periode')} bougies", Signal.TRES_NEGATIF),
                    "double": ("Range élargi dans les deux sens (forte instabilité)", Signal.NEUTRE),
                    "aucune": ("Prix contenu dans le range", Signal.NEUTRE),
                },
            ),
        ]
