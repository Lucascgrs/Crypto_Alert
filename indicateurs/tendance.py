"""
Indicateurs de TENDANCE : dans quel sens va le marché, et avec quelle force ?

7 indicateurs : moyennes mobiles, MACD, ADX, Ichimoku, Supertrend,
Parabolic SAR, Aroon.
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
    paliers_ecart,
)
from .outils import (
    atr,
    croisement_recent,
    derniere,
    ecart_relatif,
    ema,
    lissage_wilder,
    pente,
    sma,
    true_range,
    valide,
)


# ===========================================================================
# 1. MOYENNES MOBILES
# ===========================================================================
class MoyennesMobiles(Indicateur):
    """L'ossature de toute lecture de tendance : où est le prix, et comment
    les moyennes sont-elles empilées les unes par rapport aux autres."""

    code = "MM"
    nom = "Moyennes mobiles (20 / 50 / 200)"
    categorie = Categorie.TENDANCE
    description = (
        "Position du prix par rapport aux moyennes courte, moyenne et longue, "
        "alignement des trois et croisements (golden / death cross)."
    )
    periodes_min = 210
    PARAMETRES_DEFAUT = {
        "courte": 20,
        "moyenne": 50,
        "longue": 200,
        "fenetre_croisement": 10,  # ancienneté maximale d'un croisement "récent"
        "fenetre_pente": 10,
    }

    def calculer(self, df):
        cloture = df["Close"]
        return pd.DataFrame(
            {
                "MM_courte": sma(cloture, self.p("courte")),
                "MM_moyenne": sma(cloture, self.p("moyenne")),
                "MM_longue": sma(cloture, self.p("longue")),
            },
            index=df.index,
        )

    def interpreter(self, df, calc):
        prix = derniere(df["Close"])
        courte = derniere(calc["MM_courte"])
        moyenne = derniere(calc["MM_moyenne"])
        longue = derniere(calc["MM_longue"])

        criteres = [
            # 1. Où se situe le prix par rapport à la moyenne courte ?
            critere_paliers(
                "MM_POSITION",
                f"Prix vs MM{self.p('courte')}",
                ecart_relatif(prix, courte),
                paliers_ecart(f"la MM{self.p('courte')}"),
            )
        ]

        # 2. Combien de moyennes le prix domine-t-il ? (structure d'ensemble)
        if valide(prix, courte, moyenne, longue):
            nombre = int(sum(prix > m for m in (courte, moyenne, longue)))
            criteres.append(
                critere_choix(
                    "MM_STRUCTURE",
                    "Moyennes dominées par le prix",
                    nombre,
                    {
                        3: ("Prix au-dessus des 3 moyennes", Signal.TRES_POSITIF),
                        2: ("Prix au-dessus de 2 moyennes sur 3", Signal.POSITIF),
                        1: ("Prix au-dessus d'1 moyenne sur 3", Signal.NEGATIF),
                        0: ("Prix sous les 3 moyennes", Signal.TRES_NEGATIF),
                    },
                    valeur_num=nombre,
                )
            )

            # 3. Alignement : la configuration la plus lisible d'une tendance saine.
            if courte > moyenne > longue:
                alignement = "haussier"
            elif courte < moyenne < longue:
                alignement = "baissier"
            else:
                alignement = "mixte"
            criteres.append(
                critere_choix(
                    "MM_ALIGNEMENT",
                    "Alignement des moyennes",
                    alignement,
                    {
                        "haussier": ("Alignement haussier (20 > 50 > 200)", Signal.TRES_POSITIF),
                        "baissier": ("Alignement baissier (20 < 50 < 200)", Signal.TRES_NEGATIF),
                        "mixte": ("Alignement mixte, pas de tendance nette", Signal.NEUTRE),
                    },
                )
            )

        # 4. Croisement moyenne/longue : le fameux golden cross.
        sens = croisement_recent(calc["MM_moyenne"], calc["MM_longue"], self.p("fenetre_croisement"))
        criteres.append(
            critere_choix(
                "MM_CROISEMENT",
                "Croisement 50 / 200",
                sens,
                {
                    1: ("Golden cross récent (50 repasse au-dessus de 200)", Signal.TRES_POSITIF),
                    -1: ("Death cross récent (50 repasse sous 200)", Signal.TRES_NEGATIF),
                    0: ("Pas de croisement récent, configuration établie", Signal.NEUTRE),
                },
                valeur_num=sens,
            )
        )

        # 5. Orientation de la moyenne longue : la tendance de fond.
        criteres.append(
            critere_paliers(
                "MM_PENTE_LONGUE",
                f"Orientation de la MM{self.p('longue')}",
                derniere(pente(calc["MM_longue"], self.p("fenetre_pente"))),
                [
                    (-0.02, "Moyenne longue nettement orientée à la baisse", Signal.TRES_NEGATIF),
                    (-0.002, "Moyenne longue orientée à la baisse", Signal.NEGATIF),
                    (0.002, "Moyenne longue à plat", Signal.NEUTRE),
                    (0.02, "Moyenne longue orientée à la hausse", Signal.POSITIF),
                    (math.inf, "Moyenne longue nettement orientée à la hausse", Signal.TRES_POSITIF),
                ],
            )
        )
        return criteres


# ===========================================================================
# 2. MACD
# ===========================================================================
class Macd(Indicateur):
    """Convergence / divergence de deux moyennes exponentielles : mesure
    l'accélération de la tendance plus que sa direction absolue."""

    code = "MACD"
    nom = "MACD (12 / 26 / 9)"
    categorie = Categorie.TENDANCE
    description = (
        "Position de la ligne MACD par rapport à zéro et à sa ligne de signal, "
        "plus la dynamique de l'histogramme (accélération / essoufflement)."
    )
    periodes_min = 60
    PARAMETRES_DEFAUT = {"rapide": 12, "lente": 26, "signal": 9, "fenetre_croisement": 5}

    def calculer(self, df):
        cloture = df["Close"]
        ligne = ema(cloture, self.p("rapide")) - ema(cloture, self.p("lente"))
        signal = ema(ligne, self.p("signal"))
        return pd.DataFrame(
            {
                "MACD": ligne,
                "MACD_signal": signal,
                "MACD_histogramme": ligne - signal,
                # Version rapportée au prix : comparable entre cryptos et dans le temps.
                "MACD_normalise": ligne / cloture,
            },
            index=df.index,
        )

    def interpreter(self, df, calc):
        histogramme = calc["MACD_histogramme"]
        hist = derniere(histogramme)
        hist_precedent = derniere(histogramme.shift(1))

        criteres = [
            # 1. Position vs zéro : au-dessus, la moyenne courte domine la longue.
            critere_paliers(
                "MACD_ZERO",
                "MACD vs ligne zéro",
                derniere(calc["MACD_normalise"]),
                [
                    (-0.02, "Nettement sous zéro, tendance baissière marquée", Signal.TRES_NEGATIF),
                    (-0.001, "Sous zéro, tendance baissière", Signal.NEGATIF),
                    (0.001, "Autour de zéro, tendance indécise", Signal.NEUTRE),
                    (0.02, "Au-dessus de zéro, tendance haussière", Signal.POSITIF),
                    (math.inf, "Nettement au-dessus de zéro, tendance haussière marquée", Signal.TRES_POSITIF),
                ],
            ),
            # 2. Position vs ligne de signal. L'écart est rapporté au prix pour
            #    disposer d'une vraie zone neutre : sans elle, un histogramme
            #    numériquement nul basculerait arbitrairement d'un côté.
            critere_paliers(
                "MACD_SIGNAL",
                "MACD vs ligne de signal",
                hist / derniere(df["Close"]) if valide(hist) else float("nan"),
                [
                    (-0.005, "MACD nettement sous sa ligne de signal", Signal.TRES_NEGATIF),
                    (-0.0002, "MACD sous sa ligne de signal", Signal.NEGATIF),
                    (0.0002, "MACD confondu avec sa ligne de signal", Signal.NEUTRE),
                    (0.005, "MACD au-dessus de sa ligne de signal", Signal.POSITIF),
                    (math.inf, "MACD nettement au-dessus de sa ligne de signal", Signal.TRES_POSITIF),
                ],
            ),
        ]

        # 3. Dynamique de l'histogramme : le signe dit le sens, la variation dit
        #    si le mouvement s'amplifie ou s'essouffle.
        if valide(hist, hist_precedent):
            if hist > 0:
                cle = "expansion_haussiere" if hist > hist_precedent else "essoufflement_haussier"
            else:
                cle = "expansion_baissiere" if hist < hist_precedent else "essoufflement_baissier"
        else:
            cle = None
        criteres.append(
            critere_choix(
                "MACD_HISTOGRAMME",
                "Dynamique de l'histogramme",
                cle,
                {
                    "expansion_haussiere": ("Histogramme positif en expansion (accélération)", Signal.TRES_POSITIF),
                    "essoufflement_haussier": ("Histogramme positif en contraction (essoufflement)", Signal.NEUTRE),
                    "essoufflement_baissier": ("Histogramme négatif en contraction (reprise)", Signal.NEUTRE),
                    "expansion_baissiere": ("Histogramme négatif en expansion (accélération baissière)", Signal.TRES_NEGATIF),
                },
                valeur_num=hist,
            )
        )

        # 4. Fraîcheur du croisement : un signal jeune vaut mieux qu'un signal usé.
        sens = croisement_recent(calc["MACD"], calc["MACD_signal"], self.p("fenetre_croisement"))
        criteres.append(
            critere_choix(
                "MACD_CROISEMENT",
                "Croisement récent",
                sens,
                {
                    1: ("Croisement haussier récent", Signal.TRES_POSITIF),
                    -1: ("Croisement baissier récent", Signal.TRES_NEGATIF),
                    0: ("Aucun croisement récent", Signal.NEUTRE),
                },
                valeur_num=sens,
            )
        )
        return criteres


# ===========================================================================
# 3. ADX
# ===========================================================================
class Adx(Indicateur):
    """Mesure la FORCE de la tendance (sans son sens) via l'ADX, et son sens
    via les directionnels +DI / -DI."""

    code = "ADX"
    nom = "ADX / DI (14)"
    categorie = Categorie.TENDANCE
    description = (
        "Force de la tendance en cours (marché directionnel ou en range) et "
        "domination des acheteurs (+DI) ou des vendeurs (-DI)."
    )
    periodes_min = 60
    PARAMETRES_DEFAUT = {"periode": 14, "fenetre_pente": 5}

    def calculer(self, df):
        periode = self.p("periode")
        haut, bas = df["High"], df["Low"]

        # Mouvements directionnels : on ne retient que le plus ample des deux.
        hausse = haut.diff()
        baisse = -bas.diff()
        dm_plus = pd.Series(np.where((hausse > baisse) & (hausse > 0), hausse, 0.0), index=df.index)
        dm_moins = pd.Series(np.where((baisse > hausse) & (baisse > 0), baisse, 0.0), index=df.index)

        tr_lisse = lissage_wilder(true_range(df), periode)
        di_plus = 100 * lissage_wilder(dm_plus, periode) / (tr_lisse + 1e-12)
        di_moins = 100 * lissage_wilder(dm_moins, periode) / (tr_lisse + 1e-12)
        dx = 100 * (di_plus - di_moins).abs() / ((di_plus + di_moins) + 1e-12)

        return pd.DataFrame(
            {"ADX": lissage_wilder(dx, periode), "DI_plus": di_plus, "DI_moins": di_moins},
            index=df.index,
        )

    def interpreter(self, df, calc):
        adx = derniere(calc["ADX"])
        di_plus = derniere(calc["DI_plus"])
        di_moins = derniere(calc["DI_moins"])

        # Domination normalisée dans [-1, 1] : indépendante de l'échelle des DI.
        domination = float("nan")
        if valide(di_plus, di_moins):
            domination = (di_plus - di_moins) / (di_plus + di_moins + 1e-12)

        return [
            # Critère de CONTEXTE : l'ADX ne dit pas d'acheter, il dit si une
            # tendance existe. On l'exclut donc du score directionnel.
            critere_paliers(
                "ADX_FORCE",
                "Force de la tendance",
                adx,
                [
                    (20, "Absence de tendance (marché en range)", Signal.NEUTRE),
                    (25, "Tendance naissante ou faible", Signal.NEUTRE),
                    (40, "Tendance établie", Signal.NEUTRE),
                    (50, "Tendance forte", Signal.NEUTRE),
                    (math.inf, "Tendance très forte (risque d'épuisement)", Signal.NEUTRE),
                ],
                directionnel=False,
            ),
            critere_paliers(
                "ADX_DIRECTION",
                "Domination +DI / -DI",
                domination,
                [
                    (-0.30, "Vendeurs nettement dominants", Signal.TRES_NEGATIF),
                    (-0.08, "Vendeurs dominants", Signal.NEGATIF),
                    (0.08, "Acheteurs et vendeurs à l'équilibre", Signal.NEUTRE),
                    (0.30, "Acheteurs dominants", Signal.POSITIF),
                    (math.inf, "Acheteurs nettement dominants", Signal.TRES_POSITIF),
                ],
            ),
            critere_paliers(
                "ADX_DYNAMIQUE",
                "Évolution de la force",
                derniere(pente(calc["ADX"], self.p("fenetre_pente"))),
                [
                    (-0.10, "Tendance qui s'affaiblit nettement", Signal.NEUTRE),
                    (-0.02, "Tendance qui s'affaiblit", Signal.NEUTRE),
                    (0.02, "Force de tendance stable", Signal.NEUTRE),
                    (0.10, "Tendance qui se renforce", Signal.NEUTRE),
                    (math.inf, "Tendance qui se renforce nettement", Signal.NEUTRE),
                ],
                directionnel=False,
            ),
        ]


# ===========================================================================
# 4. ICHIMOKU
# ===========================================================================
class Ichimoku(Indicateur):
    """Système complet japonais : le nuage sert de zone de support/résistance,
    les lignes Tenkan/Kijun de signaux de momentum."""

    code = "ICHIMOKU"
    nom = "Ichimoku Kinko Hyo"
    categorie = Categorie.TENDANCE
    description = (
        "Position du prix vis-à-vis du nuage (support/résistance majeur), "
        "croisement Tenkan/Kijun, orientation du nuage futur et Chikou span."
    )
    periodes_min = 130
    PARAMETRES_DEFAUT = {"tenkan": 9, "kijun": 26, "senkou_b": 52, "decalage": 26}

    def calculer(self, df):
        haut, bas = df["High"], df["Low"]

        def milieu_canal(periode):
            """Ligne médiane du canal : (plus haut + plus bas) / 2 sur N périodes."""
            return (haut.rolling(periode).max() + bas.rolling(periode).min()) / 2

        tenkan = milieu_canal(self.p("tenkan"))
        kijun = milieu_canal(self.p("kijun"))
        decalage = self.p("decalage")

        # Le nuage visible AUJOURD'HUI a été calculé il y a `decalage` périodes :
        # on décale donc les spans vers l'avant pour les aligner sur le prix.
        span_a = ((tenkan + kijun) / 2).shift(decalage)
        span_b = milieu_canal(self.p("senkou_b")).shift(decalage)

        return pd.DataFrame(
            {
                "Tenkan": tenkan,
                "Kijun": kijun,
                "Span_A": span_a,
                "Span_B": span_b,
                "Nuage_haut": pd.concat([span_a, span_b], axis=1).max(axis=1),
                "Nuage_bas": pd.concat([span_a, span_b], axis=1).min(axis=1),
                # Nuage projeté dans le futur (non décalé) : donne l'orientation à venir.
                "Futur_A": (tenkan + kijun) / 2,
                "Futur_B": milieu_canal(self.p("senkou_b")),
            },
            index=df.index,
        )

    def interpreter(self, df, calc):
        prix = derniere(df["Close"])
        nuage_haut = derniere(calc["Nuage_haut"])
        nuage_bas = derniere(calc["Nuage_bas"])

        # 1. Position vis-à-vis du nuage : le critère roi d'Ichimoku.
        if valide(prix, nuage_haut, nuage_bas):
            if prix > nuage_haut:
                position = "au_dessus"
            elif prix < nuage_bas:
                position = "sous"
            else:
                position = "dedans"
        else:
            position = None

        criteres = [
            critere_choix(
                "ICHI_NUAGE",
                "Position vs nuage",
                position,
                {
                    "au_dessus": ("Prix au-dessus du nuage (zone haussière)", Signal.TRES_POSITIF),
                    "dedans": ("Prix à l'intérieur du nuage (zone d'indécision)", Signal.NEUTRE),
                    "sous": ("Prix sous le nuage (zone baissière)", Signal.TRES_NEGATIF),
                },
            ),
            # 2. Croisement Tenkan / Kijun : le signal de momentum du système.
            critere_paliers(
                "ICHI_TENKAN_KIJUN",
                "Tenkan vs Kijun",
                ecart_relatif(derniere(calc["Tenkan"]), derniere(calc["Kijun"])),
                [
                    (-0.03, "Tenkan nettement sous la Kijun", Signal.TRES_NEGATIF),
                    (-0.002, "Tenkan sous la Kijun", Signal.NEGATIF),
                    (0.002, "Tenkan et Kijun confondues", Signal.NEUTRE),
                    (0.03, "Tenkan au-dessus de la Kijun", Signal.POSITIF),
                    (math.inf, "Tenkan nettement au-dessus de la Kijun", Signal.TRES_POSITIF),
                ],
            ),
            # 3. Prix vs Kijun : la Kijun fait souvent office d'aimant / support.
            critere_paliers(
                "ICHI_KIJUN",
                "Prix vs Kijun",
                ecart_relatif(prix, derniere(calc["Kijun"])),
                paliers_ecart("la Kijun"),
            ),
            # 4. Orientation du nuage futur.
            critere_paliers(
                "ICHI_NUAGE_FUTUR",
                "Nuage futur",
                ecart_relatif(derniere(calc["Futur_A"]), derniere(calc["Futur_B"])),
                [
                    (-0.02, "Nuage futur nettement baissier", Signal.TRES_NEGATIF),
                    (-0.001, "Nuage futur baissier", Signal.NEGATIF),
                    (0.001, "Nuage futur plat (transition)", Signal.NEUTRE),
                    (0.02, "Nuage futur haussier", Signal.POSITIF),
                    (math.inf, "Nuage futur nettement haussier", Signal.TRES_POSITIF),
                ],
            ),
        ]

        # 5. Chikou span : le prix d'aujourd'hui comparé à celui d'il y a N périodes.
        decalage = self.p("decalage")
        prix_passe = derniere(df["Close"].shift(decalage))
        criteres.append(
            critere_paliers(
                "ICHI_CHIKOU",
                f"Chikou span (prix vs il y a {decalage} bougies)",
                ecart_relatif(prix, prix_passe),
                [
                    (-0.05, "Chikou nettement sous les prix passés", Signal.TRES_NEGATIF),
                    (-0.005, "Chikou sous les prix passés", Signal.NEGATIF),
                    (0.005, "Chikou au contact des prix passés", Signal.NEUTRE),
                    (0.05, "Chikou au-dessus des prix passés", Signal.POSITIF),
                    (math.inf, "Chikou nettement au-dessus des prix passés", Signal.TRES_POSITIF),
                ],
            )
        )
        return criteres


# ===========================================================================
# 5. SUPERTREND
# ===========================================================================
def _supertrend(df: pd.DataFrame, periode: int, multiplicateur: float) -> pd.DataFrame:
    """
    Calcul du Supertrend : deux bandes ATR autour du prix médian, avec une règle
    de « verrouillage » qui empêche la bande active de reculer tant que la
    tendance tient. Nécessite une boucle, l'état d'une bougie dépendant de la
    précédente.
    """
    milieu = (df["High"] + df["Low"]) / 2
    marge = multiplicateur * atr(df, periode)
    base_haute = (milieu + marge).to_numpy(dtype=float)
    base_basse = (milieu - marge).to_numpy(dtype=float)
    cloture = df["Close"].to_numpy(dtype=float)

    n = len(df)
    haute, basse = base_haute.copy(), base_basse.copy()
    tendance = np.ones(n, dtype=int)

    for i in range(1, n):
        # La bande haute ne peut que descendre tant que le prix reste dessous.
        if base_haute[i] < haute[i - 1] or cloture[i - 1] > haute[i - 1]:
            haute[i] = base_haute[i]
        else:
            haute[i] = haute[i - 1]
        # La bande basse ne peut que monter tant que le prix reste dessus.
        if base_basse[i] > basse[i - 1] or cloture[i - 1] < basse[i - 1]:
            basse[i] = base_basse[i]
        else:
            basse[i] = basse[i - 1]
        # Retournement uniquement lorsque la bande active est franchie.
        if tendance[i - 1] == 1:
            tendance[i] = -1 if cloture[i] < basse[i] else 1
        else:
            tendance[i] = 1 if cloture[i] > haute[i] else -1

    ligne = np.where(tendance == 1, basse, haute)
    return pd.DataFrame({"Supertrend": ligne, "Sens": tendance}, index=df.index)


class Supertrend(Indicateur):
    """Suiveur de tendance à base d'ATR : une seule ligne, un seul sens, très
    lisible dans un tableau de bord."""

    code = "SUPERTREND"
    nom = "Supertrend (10, 3)"
    categorie = Categorie.TENDANCE
    description = (
        "Ligne de suivi de tendance calée sur la volatilité (ATR) : donne un sens "
        "binaire haussier/baissier et signale les retournements récents."
    )
    periodes_min = 60
    PARAMETRES_DEFAUT = {"periode": 10, "multiplicateur": 3.0, "fenetre_retournement": 5}

    def calculer(self, df):
        return _supertrend(df, self.p("periode"), self.p("multiplicateur"))

    def interpreter(self, df, calc):
        sens = calc["Sens"]
        sens_actuel = int(derniere(sens)) if valide(derniere(sens)) else 0

        criteres = [
            critere_choix(
                "ST_SENS",
                "Sens du Supertrend",
                sens_actuel,
                {
                    1: ("Tendance haussière (prix au-dessus du Supertrend)", Signal.TRES_POSITIF),
                    -1: ("Tendance baissière (prix sous le Supertrend)", Signal.TRES_NEGATIF),
                },
                valeur_num=sens_actuel,
            )
        ]

        # Un retournement tout frais est l'information la plus actionnable ici.
        fenetre = self.p("fenetre_retournement")
        recents = sens.iloc[-(fenetre + 1):]
        retournement = 0
        if len(recents) > 1 and recents.nunique() > 1:
            retournement = sens_actuel
        criteres.append(
            critere_choix(
                "ST_RETOURNEMENT",
                "Retournement récent",
                retournement,
                {
                    1: (f"Retournement haussier dans les {fenetre} dernières bougies", Signal.TRES_POSITIF),
                    -1: (f"Retournement baissier dans les {fenetre} dernières bougies", Signal.TRES_NEGATIF),
                    0: ("Tendance établie, pas de retournement récent", Signal.NEUTRE),
                },
                valeur_num=retournement,
            )
        )
        return criteres


# ===========================================================================
# 6. PARABOLIC SAR
# ===========================================================================
def _psar(df: pd.DataFrame, pas: float, pas_max: float) -> pd.DataFrame:
    """
    Parabolic SAR de Wilder. Le point de retournement accélère vers le prix tant
    que la tendance progresse (facteur d'accélération), d'où la boucle.
    """
    haut = df["High"].to_numpy(dtype=float)
    bas = df["Low"].to_numpy(dtype=float)
    n = len(df)

    sar = np.zeros(n)
    tendance = np.ones(n, dtype=int)
    sar[0] = bas[0]
    extreme = haut[0]  # point extrême atteint dans la tendance en cours
    acceleration = pas

    for i in range(1, n):
        sar[i] = sar[i - 1] + acceleration * (extreme - sar[i - 1])
        precedent = max(i - 2, 0)

        if tendance[i - 1] == 1:
            # En tendance haussière, le SAR ne peut pas dépasser les plus bas récents.
            sar[i] = min(sar[i], bas[i - 1], bas[precedent])
            if bas[i] < sar[i]:  # retournement à la baisse
                tendance[i] = -1
                sar[i] = extreme
                extreme = bas[i]
                acceleration = pas
            else:
                tendance[i] = 1
                if haut[i] > extreme:
                    extreme = haut[i]
                    acceleration = min(acceleration + pas, pas_max)
        else:
            sar[i] = max(sar[i], haut[i - 1], haut[precedent])
            if haut[i] > sar[i]:  # retournement à la hausse
                tendance[i] = 1
                sar[i] = extreme
                extreme = haut[i]
                acceleration = pas
            else:
                tendance[i] = -1
                if bas[i] < extreme:
                    extreme = bas[i]
                    acceleration = min(acceleration + pas, pas_max)

    return pd.DataFrame({"PSAR": sar, "Sens": tendance}, index=df.index)


class ParabolicSar(Indicateur):
    """Points de retournement : indique le sens et où placerait un stop suiveur."""

    code = "PSAR"
    nom = "Parabolic SAR (0.02, 0.2)"
    categorie = Categorie.TENDANCE
    description = (
        "Sens de la tendance selon la position des points SAR par rapport au prix, "
        "et signalement des retournements récents."
    )
    periodes_min = 40
    PARAMETRES_DEFAUT = {"pas": 0.02, "pas_max": 0.2, "fenetre_retournement": 5}

    def calculer(self, df):
        return _psar(df, self.p("pas"), self.p("pas_max"))

    def interpreter(self, df, calc):
        sens = calc["Sens"]
        sens_actuel = int(derniere(sens)) if valide(derniere(sens)) else 0
        fenetre = self.p("fenetre_retournement")
        recents = sens.iloc[-(fenetre + 1):]
        retournement = sens_actuel if recents.nunique() > 1 else 0

        return [
            critere_choix(
                "PSAR_SENS",
                "Sens du SAR",
                sens_actuel,
                {
                    1: ("Points SAR sous le prix (configuration haussière)", Signal.POSITIF),
                    -1: ("Points SAR au-dessus du prix (configuration baissière)", Signal.NEGATIF),
                },
                valeur_num=sens_actuel,
            ),
            critere_choix(
                "PSAR_RETOURNEMENT",
                "Retournement récent",
                retournement,
                {
                    1: (f"Bascule haussière dans les {fenetre} dernières bougies", Signal.TRES_POSITIF),
                    -1: (f"Bascule baissière dans les {fenetre} dernières bougies", Signal.TRES_NEGATIF),
                    0: ("Aucune bascule récente", Signal.NEUTRE),
                },
                valeur_num=retournement,
            ),
            # Distance au SAR : plus le prix s'éloigne, plus la tendance est mûre.
            critere_paliers(
                "PSAR_DISTANCE",
                "Distance prix / SAR",
                abs(ecart_relatif(derniere(df["Close"]), derniere(calc["PSAR"]))),
                [
                    (0.01, "Prix collé au SAR (retournement possible)", Signal.NEUTRE),
                    (0.05, "Distance modérée au SAR", Signal.NEUTRE),
                    (math.inf, "Prix très éloigné du SAR (tendance mûre)", Signal.NEUTRE),
                ],
                directionnel=False,
            ),
        ]


# ===========================================================================
# 7. AROON
# ===========================================================================
class Aroon(Indicateur):
    """Mesure la FRAÎCHEUR des extrêmes : depuis combien de temps le plus haut
    (ou le plus bas) de la fenêtre n'a-t-il pas été renouvelé ?"""

    code = "AROON"
    nom = "Aroon (25)"
    categorie = Categorie.TENDANCE
    description = (
        "Ancienneté du dernier plus haut et du dernier plus bas de la période : "
        "détecte tôt les débuts de tendance et les phases de consolidation."
    )
    periodes_min = 60
    PARAMETRES_DEFAUT = {"periode": 25}

    def calculer(self, df):
        periode = self.p("periode")
        # argmax/argmin renvoient la position du extremum dans la fenêtre :
        # `periode` = tout frais, 0 = aussi vieux que la fenêtre.
        position_haut = df["High"].rolling(periode + 1).apply(np.argmax, raw=True)
        position_bas = df["Low"].rolling(periode + 1).apply(np.argmin, raw=True)
        return pd.DataFrame(
            {
                "Aroon_haut": 100 * position_haut / periode,
                "Aroon_bas": 100 * position_bas / periode,
            },
            index=df.index,
        )

    def interpreter(self, df, calc):
        aroon_haut = derniere(calc["Aroon_haut"])
        aroon_bas = derniere(calc["Aroon_bas"])

        # État qualitatif : les deux lignes lues ensemble.
        etat = None
        if valide(aroon_haut, aroon_bas):
            if aroon_haut > 70 and aroon_bas < 30:
                etat = "haussier_fort"
            elif aroon_bas > 70 and aroon_haut < 30:
                etat = "baissier_fort"
            elif aroon_haut < 50 and aroon_bas < 50:
                etat = "consolidation"
            else:
                etat = "indecis"

        return [
            critere_paliers(
                "AROON_DOMINANCE",
                "Aroon Up vs Aroon Down",
                (aroon_haut - aroon_bas) / 100 if valide(aroon_haut, aroon_bas) else float("nan"),
                [
                    (-0.60, "Plus bas bien plus récents que les plus hauts", Signal.TRES_NEGATIF),
                    (-0.15, "Plus bas plus récents que les plus hauts", Signal.NEGATIF),
                    (0.15, "Plus hauts et plus bas d'ancienneté comparable", Signal.NEUTRE),
                    (0.60, "Plus hauts plus récents que les plus bas", Signal.POSITIF),
                    (math.inf, "Plus hauts bien plus récents que les plus bas", Signal.TRES_POSITIF),
                ],
            ),
            critere_choix(
                "AROON_ETAT",
                "Configuration Aroon",
                etat,
                {
                    "haussier_fort": ("Tendance haussière franche et récente", Signal.TRES_POSITIF),
                    "baissier_fort": ("Tendance baissière franche et récente", Signal.TRES_NEGATIF),
                    "consolidation": ("Consolidation (aucun extrême renouvelé)", Signal.NEUTRE),
                    "indecis": ("Configuration de transition", Signal.NEUTRE),
                },
            ),
        ]
