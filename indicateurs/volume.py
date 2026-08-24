"""
Indicateurs de VOLUME : le mouvement de prix est-il soutenu par des échanges ?

4 indicateurs : OBV, volume relatif (RVOL), Chaikin Money Flow, Money Flow Index.

Le volume ne donne jamais une direction à lui seul : il CONFIRME ou INFIRME le
mouvement de prix. Les critères de cette famille sont donc majoritairement
construits comme des croisements « sens du prix × intensité du volume ».
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .base import (
    Categorie,
    Indicateur,
    Signal,
    critere_choix,
    critere_paliers,
)
from .outils import derniere, ema, rang_percentile, sma, valide


# ===========================================================================
# 1. OBV
# ===========================================================================
class Obv(Indicateur):
    """On Balance Volume : cumule le volume avec le signe de la variation de
    prix. Sa pente révèle l'accumulation ou la distribution silencieuse."""

    code = "OBV"
    nom = "On Balance Volume"
    categorie = Categorie.VOLUME
    description = (
        "Volume cumulé signé par le sens des bougies : mesure l'accumulation, et "
        "sa comparaison au prix révèle les divergences volume / prix."
    )
    periodes_min = 60
    PARAMETRES_DEFAUT = {"periode_moyenne": 20, "fenetre_pente": 10}

    def calculer(self, df):
        sens = np.sign(df["Close"].diff()).fillna(0)
        obv = (sens * df["Volume"]).cumsum()
        return pd.DataFrame(
            {"OBV": obv, "OBV_moyenne": ema(obv, self.p("periode_moyenne"))}, index=df.index
        )

    def interpreter(self, df, calc):
        fenetre = self.p("fenetre_pente")

        # L'OBV n'a pas d'échelle propre : on le compare à sa moyenne en unités
        # d'amplitude récente, sinon le seuil dépendrait de l'ancienneté du cumul.
        amplitude = calc["OBV"].rolling(self.p("periode_moyenne")).std()
        ecart_normalise = derniere((calc["OBV"] - calc["OBV_moyenne"]) / (amplitude + 1e-12))

        # Divergence : on compare le SENS de la pente du prix et celle de l'OBV.
        pente_prix = derniere(df["Close"].pct_change(fenetre))
        pente_obv = derniere((calc["OBV"] - calc["OBV"].shift(fenetre)) / (amplitude + 1e-12))

        coherence = None
        if valide(pente_prix, pente_obv):
            if abs(pente_prix) < 0.005:
                # Prix quasi immobile : le sens de l'OBV ne confirme rien du tout.
                coherence = "prix_stable"
            elif pente_prix > 0:
                coherence = "hausse_confirmee" if pente_obv > 0 else "hausse_non_confirmee"
            else:
                coherence = "baisse_confirmee" if pente_obv < 0 else "baisse_non_confirmee"

        return [
            critere_paliers(
                "OBV_TENDANCE",
                "OBV vs sa moyenne",
                ecart_normalise,
                [
                    (-1.5, "Distribution marquée (OBV très sous sa moyenne)", Signal.TRES_NEGATIF),
                    (-0.3, "Distribution (OBV sous sa moyenne)", Signal.NEGATIF),
                    (0.3, "OBV à l'équilibre", Signal.NEUTRE),
                    (1.5, "Accumulation (OBV au-dessus de sa moyenne)", Signal.POSITIF),
                    (math.inf, "Accumulation marquée (OBV très au-dessus)", Signal.TRES_POSITIF),
                ],
            ),
            critere_choix(
                "OBV_CONFIRMATION",
                "Cohérence volume / prix",
                coherence,
                {
                    "hausse_confirmee": ("Hausse confirmée par les volumes", Signal.TRES_POSITIF),
                    "hausse_non_confirmee": ("Hausse non confirmée par les volumes (divergence)", Signal.NEGATIF),
                    "baisse_confirmee": ("Baisse confirmée par les volumes", Signal.TRES_NEGATIF),
                    "baisse_non_confirmee": ("Baisse non confirmée par les volumes (essoufflement vendeur)", Signal.POSITIF),
                    "prix_stable": ("Prix stable, rien à confirmer", Signal.NEUTRE),
                },
            ),
        ]


# ===========================================================================
# 2. VOLUME RELATIF (RVOL)
# ===========================================================================
class VolumeRelatif(Indicateur):
    """Volume de la bougie rapporté à sa moyenne récente. Un mouvement sans
    volume est un mouvement fragile."""

    code = "RVOL"
    nom = "Volume relatif (RVOL 20)"
    categorie = Categorie.VOLUME
    description = (
        "Intensité du volume par rapport à sa moyenne récente, et confirmation "
        "du sens du prix par ce volume."
    )
    periodes_min = 40
    PARAMETRES_DEFAUT = {"periode": 20, "fenetre_rang": 250, "fenetre_prix": 3}

    def calculer(self, df):
        moyenne = sma(df["Volume"], self.p("periode"))
        rvol = df["Volume"] / (moyenne + 1e-12)
        return pd.DataFrame(
            {"RVOL": rvol, "RVOL_rang": rang_percentile(rvol, self.p("fenetre_rang"))},
            index=df.index,
        )

    def interpreter(self, df, calc):
        rvol = derniere(calc["RVOL"])
        variation = derniere(df["Close"].pct_change(self.p("fenetre_prix")))

        # Croisement sens du prix × intensité du volume : c'est là que le volume
        # devient directionnel.
        confirmation = None
        if valide(rvol, variation):
            fort = rvol >= 1.3
            if variation > 0.005:
                confirmation = "hausse_volume_fort" if fort else "hausse_volume_faible"
            elif variation < -0.005:
                confirmation = "baisse_volume_fort" if fort else "baisse_volume_faible"
            else:
                confirmation = "prix_stable"

        return [
            critere_paliers(
                "RVOL_NIVEAU",
                "Intensité du volume",
                rvol,
                [
                    (0.6, "Volume très faible (désintérêt)", Signal.NEUTRE),
                    (0.9, "Volume inférieur à la moyenne", Signal.NEUTRE),
                    (1.3, "Volume normal", Signal.NEUTRE),
                    (2.0, "Volume élevé", Signal.NEUTRE),
                    (math.inf, "Volume exceptionnel (plus du double de la moyenne)", Signal.NEUTRE),
                ],
                directionnel=False,
            ),
            critere_choix(
                "RVOL_CONFIRMATION",
                "Volume à l'appui du mouvement",
                confirmation,
                {
                    "hausse_volume_fort": ("Hausse portée par un volume élevé", Signal.TRES_POSITIF),
                    "hausse_volume_faible": ("Hausse sans volume marqué (peu convaincante)", Signal.NEUTRE),
                    "baisse_volume_fort": ("Baisse portée par un volume élevé (pression vendeuse)", Signal.TRES_NEGATIF),
                    "baisse_volume_faible": ("Baisse sans volume marqué (simple respiration)", Signal.NEUTRE),
                    "prix_stable": ("Prix stable, volume sans signification directionnelle", Signal.NEUTRE),
                },
            ),
        ]


# ===========================================================================
# 3. CHAIKIN MONEY FLOW
# ===========================================================================
class ChaikinMoneyFlow(Indicateur):
    """Pondère chaque volume par la position de la clôture dans la bougie :
    clôturer près du haut = pression acheteuse."""

    code = "CMF"
    nom = "Chaikin Money Flow (20)"
    categorie = Categorie.VOLUME
    description = (
        "Pression acheteuse ou vendeuse mesurée par la place de la clôture dans "
        "chaque bougie, pondérée par le volume."
    )
    periodes_min = 50
    PARAMETRES_DEFAUT = {"periode": 20, "fenetre_pente": 5}

    def calculer(self, df):
        amplitude = (df["High"] - df["Low"]).replace(0, float("nan"))
        # Multiplicateur dans [-1, 1] : +1 = clôture sur le haut de la bougie.
        multiplicateur = ((df["Close"] - df["Low"]) - (df["High"] - df["Close"])) / amplitude
        flux = (multiplicateur * df["Volume"]).fillna(0)

        periode = self.p("periode")
        cmf = flux.rolling(periode).sum() / (df["Volume"].rolling(periode).sum() + 1e-12)
        return pd.DataFrame({"CMF": cmf}, index=df.index)

    def interpreter(self, df, calc):
        return [
            critere_paliers(
                "CMF_PRESSION",
                "Pression acheteuse / vendeuse",
                derniere(calc["CMF"]),
                [
                    (-0.20, "Forte pression vendeuse", Signal.TRES_NEGATIF),
                    (-0.05, "Pression vendeuse", Signal.NEGATIF),
                    (0.05, "Pression équilibrée", Signal.NEUTRE),
                    (0.20, "Pression acheteuse", Signal.POSITIF),
                    (math.inf, "Forte pression acheteuse", Signal.TRES_POSITIF),
                ],
            ),
            critere_paliers(
                "CMF_DYNAMIQUE",
                "Évolution de la pression",
                derniere(calc["CMF"].diff(self.p("fenetre_pente"))),
                [
                    (-0.15, "Pression qui se dégrade nettement", Signal.TRES_NEGATIF),
                    (-0.03, "Pression qui se dégrade", Signal.NEGATIF),
                    (0.03, "Pression stable", Signal.NEUTRE),
                    (0.15, "Pression qui s'améliore", Signal.POSITIF),
                    (math.inf, "Pression qui s'améliore nettement", Signal.TRES_POSITIF),
                ],
            ),
        ]


# ===========================================================================
# 4. MONEY FLOW INDEX
# ===========================================================================
class MoneyFlowIndex(Indicateur):
    """Le RSI pondéré par le volume : mêmes zones de lecture, mais un excès
    confirmé par les volumes pèse plus lourd."""

    code = "MFI"
    nom = "Money Flow Index (14)"
    categorie = Categorie.VOLUME
    description = (
        "Équivalent du RSI pondéré par les volumes échangés : zones de surachat "
        "et de survente confirmées par les flux de capitaux."
    )
    periodes_min = 50
    PARAMETRES_DEFAUT = {"periode": 14, "fenetre_pente": 5}

    def calculer(self, df):
        periode = self.p("periode")
        prix_typique = (df["High"] + df["Low"] + df["Close"]) / 3
        flux = prix_typique * df["Volume"]

        hausse = prix_typique > prix_typique.shift()
        baisse = prix_typique < prix_typique.shift()
        flux_positif = flux.where(hausse, 0.0).rolling(periode).sum()
        flux_negatif = flux.where(baisse, 0.0).rolling(periode).sum()

        ratio = flux_positif / (flux_negatif + 1e-12)
        mfi = 100 - (100 / (1 + ratio))

        # Aucun flux dans un sens ni dans l'autre (prix figé, volume nul) : la
        # formule renverrait 0, donc « survente extrême », à tort. Valeur neutre.
        immobile = (flux_positif <= 1e-12) & (flux_negatif <= 1e-12)
        return pd.DataFrame({"MFI": mfi.mask(immobile, 50.0)}, index=df.index)

    def interpreter(self, df, calc):
        return [
            critere_paliers(
                "MFI_ZONE",
                "Zone du Money Flow Index",
                derniere(calc["MFI"]),
                [
                    (10, "Survente extrême sur volumes (rebond probable)", Signal.POSITIF),
                    (20, "Survente sur volumes", Signal.POSITIF),
                    (45, "Flux de capitaux orientés à la vente", Signal.NEGATIF),
                    (55, "Flux de capitaux équilibrés", Signal.NEUTRE),
                    (80, "Flux de capitaux orientés à l'achat", Signal.POSITIF),
                    (90, "Surachat sur volumes", Signal.NEGATIF),
                    (math.inf, "Surachat extrême sur volumes (reflux probable)", Signal.NEGATIF),
                ],
            ),
            critere_paliers(
                "MFI_DYNAMIQUE",
                "Orientation des flux",
                derniere(calc["MFI"].diff(self.p("fenetre_pente"))),
                [
                    (-12, "Flux se retirant rapidement", Signal.TRES_NEGATIF),
                    (-3, "Flux se retirant", Signal.NEGATIF),
                    (3, "Flux stables", Signal.NEUTRE),
                    (12, "Flux entrants", Signal.POSITIF),
                    (math.inf, "Flux entrants massifs", Signal.TRES_POSITIF),
                ],
            ),
        ]
