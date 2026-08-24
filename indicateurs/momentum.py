"""
Indicateurs de MOMENTUM : le mouvement est-il vigoureux, essoufflé, ou excessif ?

5 indicateurs : RSI, Stochastique, CCI, Williams %R, ROC multi-horizons.

Convention de lecture retenue pour les oscillateurs bornés (RSI, Stochastique,
Williams %R, MFI) : ils sont lus en MOYENNE-REVERSION. Une zone de surachat est
donc un critère NÉGATIF (risque de reflux) et une zone de survente un critère
POSITIF (potentiel de rebond). La zone intermédiaire, elle, se lit en tendance
(au-dessus de la ligne médiane = momentum haussier).
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
from .outils import derniere, detecter_divergence, rsi, sma, valide


# Grille commune aux oscillateurs bornés 0-100 (RSI, MFI, Stochastique).
# Les bornes sont passées en paramètre car chaque oscillateur a ses usages.
#
# Choix de pondération important : les zones d'excès valent un simple POSITIF /
# NEGATIF, jamais un TRES_. Deux raisons :
#   - une lecture contrarienne est par nature moins fiable qu'une lecture de
#     tendance : en crypto, un RSI à 85 peut le rester des semaines ;
#   - un excès doublement pondéré annulerait mécaniquement les autres critères
#     du même indicateur, qui pointent forcément dans le sens inverse.
# L'intensité de l'excès reste portée par le LIBELLÉ, qui est de toute façon
# l'information réellement affichée dans le tableau de bord.
def _paliers_oscillateur(survente_extreme, survente, milieu_bas, milieu_haut, surachat, surachat_extreme):
    return [
        (survente_extreme, "Survente extrême (rebond probable)", Signal.POSITIF),
        (survente, "Zone de survente", Signal.POSITIF),
        (milieu_bas, "Momentum baissier", Signal.NEGATIF),
        (milieu_haut, "Zone neutre", Signal.NEUTRE),
        (surachat, "Momentum haussier", Signal.POSITIF),
        (surachat_extreme, "Zone de surachat", Signal.NEGATIF),
        (math.inf, "Surachat extrême (reflux probable)", Signal.NEGATIF),
    ]


# ===========================================================================
# 1. RSI
# ===========================================================================
class Rsi(Indicateur):
    """L'oscillateur le plus utilisé : compare l'ampleur des hausses et des
    baisses récentes pour situer le marché entre survente et surachat."""

    code = "RSI"
    nom = "RSI (14)"
    categorie = Categorie.MOMENTUM
    description = (
        "Zone de surachat / survente (qui intègre la position vis-à-vis de la "
        "ligne 50), orientation de l'oscillateur et divergences avec le prix."
    )
    periodes_min = 60
    PARAMETRES_DEFAUT = {"periode": 14, "fenetre_pente": 5, "fenetre_divergence": 40}

    def calculer(self, df):
        return pd.DataFrame({"RSI": rsi(df["Close"], self.p("periode"))}, index=df.index)

    def interpreter(self, df, calc):
        valeur = derniere(calc["RSI"])
        divergence = detecter_divergence(df["Close"], calc["RSI"], self.p("fenetre_divergence"))

        return [
            critere_paliers(
                "RSI_ZONE",
                "Zone du RSI",
                valeur,
                _paliers_oscillateur(20, 30, 45, 55, 70, 80),
            ),
            # Pas de critère « RSI vs 50 » séparé : il lirait exactement le même
            # nombre que RSI_ZONE, avec une convention inverse dans les extrêmes.
            # Les deux critères s'annuleraient alors systématiquement.
            critere_paliers(
                "RSI_DYNAMIQUE",
                "Orientation du RSI",
                derniere(calc["RSI"].diff(self.p("fenetre_pente"))),
                [
                    (-10, "RSI en forte baisse", Signal.TRES_NEGATIF),
                    (-2, "RSI en baisse", Signal.NEGATIF),
                    (2, "RSI stable", Signal.NEUTRE),
                    (10, "RSI en hausse", Signal.POSITIF),
                    (math.inf, "RSI en forte hausse", Signal.TRES_POSITIF),
                ],
            ),
            critere_choix(
                "RSI_DIVERGENCE",
                "Divergence prix / RSI",
                divergence,
                {
                    1: ("Divergence haussière (prix plus bas, RSI non)", Signal.TRES_POSITIF),
                    -1: ("Divergence baissière (prix plus haut, RSI non)", Signal.TRES_NEGATIF),
                    0: ("Pas de divergence détectée", Signal.NEUTRE),
                },
                valeur_num=divergence,
            ),
        ]


# ===========================================================================
# 2. STOCHASTIQUE
# ===========================================================================
class Stochastique(Indicateur):
    """Situe la clôture dans le range haut/bas de la période : très réactif,
    idéal pour repérer les excès de court terme."""

    code = "STOCH"
    nom = "Stochastique (14, 3, 3)"
    categorie = Categorie.MOMENTUM
    description = (
        "Position de la clôture dans le range récent (%K) et croisement avec sa "
        "ligne de signal (%D) : repère les excès et les retournements courts."
    )
    periodes_min = 40
    PARAMETRES_DEFAUT = {"periode": 14, "lissage_k": 3, "lissage_d": 3}

    def calculer(self, df):
        periode = self.p("periode")
        plus_bas = df["Low"].rolling(periode).min()
        plus_haut = df["High"].rolling(periode).max()
        amplitude = (plus_haut - plus_bas).replace(0, float("nan"))

        k_brut = 100 * (df["Close"] - plus_bas) / amplitude
        k = sma(k_brut, self.p("lissage_k"))
        return pd.DataFrame({"K": k, "D": sma(k, self.p("lissage_d"))}, index=df.index)

    def interpreter(self, df, calc):
        k = derniere(calc["K"])
        d = derniere(calc["D"])

        return [
            critere_paliers(
                "STOCH_ZONE",
                "Zone du stochastique",
                k,
                _paliers_oscillateur(10, 20, 45, 55, 80, 90),
            ),
            critere_paliers(
                "STOCH_CROISEMENT",
                "%K vs %D",
                k - d if valide(k, d) else float("nan"),
                [
                    (-8, "%K nettement sous %D (pression vendeuse)", Signal.TRES_NEGATIF),
                    (-1, "%K sous %D", Signal.NEGATIF),
                    (1, "%K et %D confondus", Signal.NEUTRE),
                    (8, "%K au-dessus de %D", Signal.POSITIF),
                    (math.inf, "%K nettement au-dessus de %D (pression acheteuse)", Signal.TRES_POSITIF),
                ],
            ),
        ]


# ===========================================================================
# 3. CCI
# ===========================================================================
class Cci(Indicateur):
    """Écart du prix typique à sa moyenne, normalisé par la déviation moyenne :
    non borné, il distingue bien l'impulsion de l'excès."""

    code = "CCI"
    nom = "CCI (20)"
    categorie = Categorie.MOMENTUM
    description = (
        "Écart normalisé du prix typique à sa moyenne : au-delà de ±100 il y a "
        "impulsion, au-delà de ±200 il y a excès."
    )
    periodes_min = 50
    PARAMETRES_DEFAUT = {"periode": 20, "fenetre_pente": 5}

    def calculer(self, df):
        periode = self.p("periode")
        prix_typique = (df["High"] + df["Low"] + df["Close"]) / 3
        moyenne = sma(prix_typique, periode)
        # Déviation moyenne absolue (et non écart-type) : c'est la formule d'origine.
        deviation = (prix_typique - moyenne).abs().rolling(periode).mean()
        return pd.DataFrame(
            {"CCI": (prix_typique - moyenne) / (0.015 * (deviation + 1e-12))},
            index=df.index,
        )

    def interpreter(self, df, calc):
        valeur = derniere(calc["CCI"])
        return [
            critere_paliers(
                "CCI_ZONE",
                "Zone du CCI",
                valeur,
                [
                    (-200, "Survente extrême (au-delà de -200)", Signal.POSITIF),
                    (-100, "Impulsion baissière marquée", Signal.NEGATIF),
                    (-30, "Biais baissier", Signal.NEGATIF),
                    (30, "Zone neutre", Signal.NEUTRE),
                    (100, "Biais haussier", Signal.POSITIF),
                    (200, "Impulsion haussière marquée", Signal.POSITIF),
                    (math.inf, "Surachat extrême (au-delà de +200)", Signal.NEGATIF),
                ],
            ),
            critere_paliers(
                "CCI_DYNAMIQUE",
                "Orientation du CCI",
                derniere(calc["CCI"].diff(self.p("fenetre_pente"))),
                [
                    (-80, "CCI en forte baisse", Signal.TRES_NEGATIF),
                    (-15, "CCI en baisse", Signal.NEGATIF),
                    (15, "CCI stable", Signal.NEUTRE),
                    (80, "CCI en hausse", Signal.POSITIF),
                    (math.inf, "CCI en forte hausse", Signal.TRES_POSITIF),
                ],
            ),
        ]


# ===========================================================================
# 4. WILLIAMS %R
# ===========================================================================
class WilliamsR(Indicateur):
    """Cousin inversé du stochastique, gradué de -100 (plus bas) à 0 (plus haut).
    Réputé pour anticiper légèrement les retournements."""

    code = "WILLIAMS_R"
    nom = "Williams %R (14)"
    categorie = Categorie.MOMENTUM
    description = (
        "Distance de la clôture au plus haut de la période, graduée de -100 à 0 : "
        "au-dessus de -20 le marché est en surachat, sous -80 en survente."
    )
    periodes_min = 40
    PARAMETRES_DEFAUT = {"periode": 14, "fenetre_pente": 5}

    def calculer(self, df):
        periode = self.p("periode")
        plus_haut = df["High"].rolling(periode).max()
        plus_bas = df["Low"].rolling(periode).min()
        amplitude = (plus_haut - plus_bas).replace(0, float("nan"))
        return pd.DataFrame(
            {"Williams_R": -100 * (plus_haut - df["Close"]) / amplitude}, index=df.index
        )

    def interpreter(self, df, calc):
        valeur = derniere(calc["Williams_R"])
        return [
            critere_paliers(
                "WR_ZONE",
                "Zone du Williams %R",
                valeur,
                [
                    (-90, "Survente extrême (rebond probable)", Signal.POSITIF),
                    (-80, "Zone de survente", Signal.POSITIF),
                    (-55, "Momentum baissier", Signal.NEGATIF),
                    (-45, "Zone neutre", Signal.NEUTRE),
                    (-20, "Momentum haussier", Signal.POSITIF),
                    (-10, "Zone de surachat", Signal.NEGATIF),
                    (math.inf, "Surachat extrême (reflux probable)", Signal.NEGATIF),
                ],
            ),
            critere_paliers(
                "WR_DYNAMIQUE",
                "Orientation du Williams %R",
                derniere(calc["Williams_R"].diff(self.p("fenetre_pente"))),
                [
                    (-20, "Repli rapide vers les plus bas", Signal.TRES_NEGATIF),
                    (-4, "Repli vers les plus bas", Signal.NEGATIF),
                    (4, "Position stable dans le range", Signal.NEUTRE),
                    (20, "Progression vers les plus hauts", Signal.POSITIF),
                    (math.inf, "Progression rapide vers les plus hauts", Signal.TRES_POSITIF),
                ],
            ),
        ]


# ===========================================================================
# 5. ROC MULTI-HORIZONS
# ===========================================================================
class RocMultiHorizons(Indicateur):
    """Performance brute sur plusieurs horizons : le critère le plus simple à
    lire dans un tableau de bord, et un excellent révélateur de momentum."""

    code = "ROC"
    nom = "Performance multi-horizons (7 / 30 / 90)"
    categorie = Categorie.MOMENTUM
    description = (
        "Variation de prix sur un horizon court, moyen et long, plus la cohérence "
        "entre ces trois horizons (momentum aligné ou contradictoire)."
    )
    periodes_min = 100
    # Horizons pensés pour une bougie journalière : semaine, mois, trimestre.
    PARAMETRES_DEFAUT = {"horizons": {"court": 7, "moyen": 30, "long": 90}}

    def calculer(self, df):
        cloture = df["Close"]
        return pd.DataFrame(
            {nom: cloture.pct_change(n) for nom, n in self.p("horizons").items()},
            index=df.index,
        )

    def interpreter(self, df, calc):
        horizons = self.p("horizons")

        def paliers_perf(seuil_fort, seuil_faible):
            return [
                (-seuil_fort, "Forte baisse", Signal.TRES_NEGATIF),
                (-seuil_faible, "Baisse", Signal.NEGATIF),
                (seuil_faible, "Quasi stable", Signal.NEUTRE),
                (seuil_fort, "Hausse", Signal.POSITIF),
                (math.inf, "Forte hausse", Signal.TRES_POSITIF),
            ]

        # Les seuils s'élargissent avec l'horizon : +5 % en une semaine n'a pas
        # le même poids que +5 % en un trimestre.
        seuils = {"court": (0.10, 0.02), "moyen": (0.20, 0.05), "long": (0.40, 0.10)}

        criteres = []
        valeurs = {}
        for nom, nb_periodes in horizons.items():
            valeur = derniere(calc[nom])
            valeurs[nom] = valeur
            fort, faible = seuils.get(nom, (0.20, 0.05))
            criteres.append(
                critere_paliers(
                    f"ROC_{nom.upper()}",
                    f"Performance sur {nb_periodes} bougies",
                    valeur,
                    paliers_perf(fort, faible),
                )
            )

        # Cohérence : les trois horizons pointent-ils dans le même sens ?
        connues = [v for v in valeurs.values() if valide(v)]
        coherence = None
        if len(connues) == len(horizons):
            if all(v > 0 for v in connues):
                coherence = "haussier"
            elif all(v < 0 for v in connues):
                coherence = "baissier"
            else:
                coherence = "mixte"
        criteres.append(
            critere_choix(
                "ROC_COHERENCE",
                "Cohérence des horizons",
                coherence,
                {
                    "haussier": ("Momentum haussier sur tous les horizons", Signal.TRES_POSITIF),
                    "baissier": ("Momentum baissier sur tous les horizons", Signal.TRES_NEGATIF),
                    "mixte": ("Horizons contradictoires (phase de transition)", Signal.NEUTRE),
                },
            )
        )
        return criteres
