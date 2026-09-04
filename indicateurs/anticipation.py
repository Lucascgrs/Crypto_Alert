"""
Indicateurs d'ANTICIPATION : chercher ce qui pourrait casser le mouvement.

Pourquoi ce module existe
-------------------------
Le diagnostic mené sur 9 000 barres (voir `diagnostic.py`, feuille « Passé vs
futur ») a montré que le score des 20 indicateurs historiques est corrélé à
**+0,84** avec le rendement des 12 bougies PRÉCÉDENTES, et à **-0,03 / +0,18**
avec celui des 12 bougies SUIVANTES. Ce n'est pas un défaut de réglage : une
moyenne mobile, un MACD, un Supertrend ou un ADX sont par construction des
transformations lissées du prix passé. Ils décrivent excellemment ce qui vient
d'arriver, et c'est exactement pour cela qu'ils ne l'anticipent pas.

Le critère de sélection de ce module est donc explicite et vérifiable :

    un indicateur n'entre ici que si son score N'EST PAS une fonction
    monotone du rendement des dernières barres.

Concrètement, chacun regarde autre chose que le premier moment du prix :

    RETOUR_MOYENNE   l'étirement (distance à la moyenne), lu à contre-courant
    ESSOUFFLEMENT    la dérivée SECONDE, et la longueur de la série en cours
    DIVERGENCES      le désaccord entre le prix et trois oscillateurs
    EPUISEMENT       le volume et la forme des bougies (mèches, absorption)
    ASYMETRIE        le TROISIÈME moment des rendements et leur concentration
    COMPRESSION      la largeur des bandes (contexte : un ressort comprimé)
    EFFICIENCE       la rugosité du chemin et la mémoire des rendements

Convention de pondération, différente du reste du projet
--------------------------------------------------------
`momentum.py` s'interdit les signaux TRES_ sur ses lectures contrariennes, pour
qu'un excès de RSI n'annule pas les critères de tendance du même indicateur.
Ici, il n'y a rien à annuler : TOUS les critères sont de même nature. Brider
l'échelle plafonnerait mécaniquement le score de la famille à 0,5 en valeur
absolue — « Fortement positif » deviendrait inatteignable et les seuils de
simulation ne voudraient plus rien dire. L'échelle complète est donc utilisée.

Ce que la mesure en dit
-----------------------
Construire un indicateur qui ne regarde pas le passé récent ne garantit pas
qu'il regarde l'avenir. Résultat sur 9 000 barres :

  - la règle de sélection est tenue : quatre des cinq indicateurs directionnels
    tiennent entre -0,17 et +0,15 de corrélation au rendement passé, là où les
    20 suiveurs sont tous entre +0,23 et +0,74. `RETOUR_MOYENNE` est l'exception
    assumée (-0,61) : un Z-score est le rendement récent au signe près ;
  - côté rendement futur, en revanche, rien de probant. L'anticipation domine en
    1d (+0,10 de corrélation relative à 24 bougies), les suiveurs dominent en 4h,
    personne ne gagne en 1h : chaque intervalle a un gagnant différent, ce qui
    est la signature du bruit ;
  - un seul point mérite qu'on y revienne : `ASYMETRIE` est le meilleur des 27
    indicateurs du projet sur la corrélation relative (+0,053, contre +0,022 au
    meilleur suiveur) tout en restant orthogonal au passé.

Ce que l'approche change vraiment : elle produit cinq fois moins de signaux
forts et amortit dans les deux sens. C'est un bêta plus faible, pas davantage
d'information.

`python diagnostic.py` refait la mesure ; c'est ce chiffre qui tranche, pas
l'intention de départ. Ne rien régler sur une seule fenêtre de 250 barres.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .base import (
    Approche,
    Categorie,
    Indicateur,
    Signal,
    critere_choix,
    critere_paliers,
)
from .outils import (
    EPS,
    atr,
    bandes_bollinger,
    derniere,
    detecter_divergence,
    ema,
    rang_percentile,
    rsi,
    sma,
    valide,
)


# ===========================================================================
# 1. RETOUR A LA MOYENNE
# ===========================================================================
class RetourMoyenne(Indicateur):
    """Mesure de combien le prix s'est écarté de sa propre moyenne, en
    écarts-types, et lit cet écart à contre-courant : plus l'élastique est
    tendu, plus le rappel est probable."""

    code = "RETOUR_MOYENNE"
    nom = "Retour à la moyenne (Z-score 20)"
    categorie = Categorie.MOMENTUM
    approche = Approche.ANTICIPATION
    description = (
        "Distance du prix à sa moyenne mobile, exprimée en écarts-types, et "
        "vitesse à laquelle cette distance se creuse. Lu à contre-courant : un "
        "écart extrême est un signal de rappel, pas de continuation."
    )
    periodes_min = 60
    PARAMETRES_DEFAUT = {"periode": 20, "fenetre_vitesse": 3}

    def calculer(self, df):
        periode = self.p("periode")
        moyenne = sma(df["Close"], periode)
        ecart_type = df["Close"].rolling(periode).std()
        z = (df["Close"] - moyenne) / (ecart_type + EPS)
        return pd.DataFrame(
            {"Z": z, "Z_vitesse": z.diff(self.p("fenetre_vitesse"))}, index=df.index
        )

    def interpreter(self, df, calc):
        return [
            critere_paliers(
                "MR_ETIREMENT",
                "Écart à la moyenne (en écarts-types)",
                derniere(calc["Z"]),
                [
                    (-2.5, "Très étiré sous la moyenne (rappel probable)", Signal.TRES_POSITIF),
                    (-1.2, "Étiré sous la moyenne", Signal.POSITIF),
                    (1.2, "Proche de sa moyenne", Signal.NEUTRE),
                    (2.5, "Étiré au-dessus de la moyenne", Signal.NEGATIF),
                    (math.inf, "Très étiré au-dessus (reflux probable)", Signal.TRES_NEGATIF),
                ],
            ),
            # La VITESSE d'étirement compte autant que l'étirement lui-même : un
            # écart creusé en trois bougies se referme plus souvent qu'un écart
            # installé lentement, qui est plutôt le signe d'une vraie tendance.
            critere_paliers(
                "MR_VITESSE",
                "Vitesse d'étirement",
                derniere(calc["Z_vitesse"]),
                [
                    (-1.5, "Décrochage brutal sous la moyenne", Signal.TRES_POSITIF),
                    (-0.6, "Écart qui se creuse vers le bas", Signal.POSITIF),
                    (0.6, "Écart stable", Signal.NEUTRE),
                    (1.5, "Écart qui se creuse vers le haut", Signal.NEGATIF),
                    (math.inf, "Envolée brutale au-dessus de la moyenne", Signal.TRES_NEGATIF),
                ],
            ),
        ]


# ===========================================================================
# 2. ESSOUFFLEMENT
# ===========================================================================
# Les libellés dépendent à la fois du sens du mouvement établi et du fait qu'il
# accélère ou ralentit : quatre situations, deux intensités. Une grille de
# paliers ne suffirait pas, car la même accélération négative se lit « hausse
# qui cale » dans un marché haussier et « baisse qui accélère » dans l'autre.
#
# Seule la DÉCÉLÉRATION porte un signal. Une première version notait aussi
# l'accélération (« hausse qui accélère » = positif) ; la mesure a montré que
# cela suffisait à faire remonter la corrélation de l'indicateur au rendement
# passé à +0,34, là où les autres indicateurs du module tiennent entre -0,17 et
# -0,05. C'était un suiveur de tendance qui s'était glissé dans le module, et
# l'indicateur s'appelle « essoufflement » : une accélération reste une absence
# d'essoufflement, pas un signal.
_TABLE_ACCELERATION = {
    "hausse_ralentit_fort": ("Hausse qui cale nettement", Signal.TRES_NEGATIF),
    "hausse_ralentit_modere": ("Hausse qui ralentit", Signal.NEGATIF),
    "hausse_accelere_modere": ("Hausse toujours soutenue", Signal.NEUTRE),
    "hausse_accelere_fort": ("Hausse qui accélère", Signal.NEUTRE),
    "baisse_ralentit_fort": ("Baisse qui cale nettement", Signal.TRES_POSITIF),
    "baisse_ralentit_modere": ("Baisse qui ralentit", Signal.POSITIF),
    "baisse_accelere_modere": ("Baisse toujours soutenue", Signal.NEUTRE),
    "baisse_accelere_fort": ("Baisse qui accélère", Signal.NEUTRE),
    "stable": ("Rythme inchangé", Signal.NEUTRE),
}


class Essoufflement(Indicateur):
    """Compare la jambe en cours à la précédente : c'est la dérivée seconde du
    prix. Un marché qui monte encore mais de moins en moins vite envoie un
    signal que tous les indicateurs de tendance décrivent comme haussier."""

    code = "ESSOUFFLEMENT"
    nom = "Essoufflement (dérivée seconde)"
    categorie = Categorie.MOMENTUM
    approche = Approche.ANTICIPATION
    description = (
        "Décélération du mouvement (jambe en cours comparée à la précédente, "
        "rapportée à l'ATR) et longueur de la série de bougies consécutives dans "
        "le même sens. Une accélération ne compte pas : ce serait du suivi de "
        "tendance."
    )
    periodes_min = 60
    PARAMETRES_DEFAUT = {"jambe": 5, "periode_atr": 14}

    def calculer(self, df):
        n = self.p("jambe")
        jambe = df["Close"].diff(n)
        precedente = jambe.shift(n)
        # Normalisation par l'ATR : sans elle, l'accélération de BTC (en
        # milliers de dollars) et celle de DOGE (en centimes) seraient
        # incomparables et les paliers n'auraient aucun sens commun.
        echelle = n * atr(df, self.p("periode_atr"))

        # Longueur de la série de bougies consécutives dans le même sens,
        # signée. Une bougie plate (signe 0) casse la série, ce qui est le
        # comportement voulu : elle ne prolonge aucun mouvement.
        signe = np.sign(df["Close"].diff()).fillna(0)
        ruptures = (signe != signe.shift()).cumsum()
        serie = (signe.groupby(ruptures).cumcount() + 1) * signe

        return pd.DataFrame(
            {
                "Acceleration": (jambe - precedente) / (echelle + EPS),
                "Jambe_precedente": precedente,
                "Serie": serie,
            },
            index=df.index,
        )

    def interpreter(self, df, calc):
        acceleration = derniere(calc["Acceleration"])
        precedente = derniere(calc["Jambe_precedente"])

        if not valide(acceleration, precedente) or abs(acceleration) < 0.15:
            cle = "stable"
        else:
            sens = "hausse" if precedente > 0 else "baisse"
            # L'accélération est « dans le sens » du mouvement si les deux
            # partagent le même signe.
            rythme = "accelere" if (acceleration > 0) == (precedente > 0) else "ralentit"
            force = "fort" if abs(acceleration) > 0.60 else "modere"
            cle = sens + "_" + rythme + "_" + force

        return [
            critere_choix(
                "ESS_ACCELERATION",
                "Accélération du mouvement",
                cle,
                _TABLE_ACCELERATION,
                valeur_num=acceleration,
            ),
            critere_paliers(
                "ESS_SERIE",
                "Bougies consécutives dans le même sens",
                derniere(calc["Serie"]),
                [
                    (-5.5, "Longue série de baisses (survente mécanique)", Signal.TRES_POSITIF),
                    (-3.5, "Série de baisses", Signal.POSITIF),
                    (3.5, "Pas de série marquée", Signal.NEUTRE),
                    (5.5, "Série de hausses", Signal.NEGATIF),
                    (math.inf, "Longue série de hausses (surachat mécanique)",
                     Signal.TRES_NEGATIF),
                ],
            ),
        ]


# ===========================================================================
# 3. DIVERGENCES MULTIPLES
# ===========================================================================
_TABLE_DIVERGENCE = {
    3: ("Divergence haussière sur les trois oscillateurs", Signal.TRES_POSITIF),
    2: ("Divergence haussière sur deux oscillateurs", Signal.TRES_POSITIF),
    1: ("Divergence haussière isolée", Signal.POSITIF),
    0: ("Aucun désaccord prix / oscillateurs", Signal.NEUTRE),
    -1: ("Divergence baissière isolée", Signal.NEGATIF),
    -2: ("Divergence baissière sur deux oscillateurs", Signal.TRES_NEGATIF),
    -3: ("Divergence baissière sur les trois oscillateurs", Signal.TRES_NEGATIF),
}


class Divergences(Indicateur):
    """Le prix fait un nouveau plus bas, mais ni le RSI, ni le MACD, ni les
    volumes ne le suivent : le mouvement n'est plus alimenté. C'est le seul
    signal classique qui se déclenche AVANT le retournement du prix."""

    code = "DIVERGENCES"
    nom = "Divergences multiples (RSI, MACD, OBV)"
    categorie = Categorie.MOMENTUM
    approche = Approche.ANTICIPATION
    description = (
        "Désaccord entre les extrêmes du prix et ceux de trois oscillateurs de "
        "natures différentes, mesuré sur deux horizons. Une divergence "
        "confirmée par plusieurs oscillateurs vaut bien mieux qu'une isolée."
    )
    periodes_min = 90
    PARAMETRES_DEFAUT = {
        "periode_rsi": 14,
        "rapide": 12,
        "lent": 26,
        "signal": 9,
        "fenetre_courte": 20,
        "fenetre_longue": 40,
    }

    def calculer(self, df):
        macd = ema(df["Close"], self.p("rapide")) - ema(df["Close"], self.p("lent"))
        variation = df["Close"].diff()
        # OBV : cumul du volume signé. Le cumul est causal, et un décalage
        # constant ne change rien à la comparaison d'extrêmes faite plus bas —
        # l'indicateur reste donc valable sur une série tronquée.
        obv = (np.sign(variation).fillna(0) * df["Volume"]).cumsum()
        return pd.DataFrame(
            {
                "RSI": rsi(df["Close"], self.p("periode_rsi")),
                "Histogramme": macd - ema(macd, self.p("signal")),
                "OBV": obv,
            },
            index=df.index,
        )

    def _consensus(self, df, calc, fenetre: int) -> int:
        """Somme des divergences des trois oscillateurs, entre -3 et +3."""
        return sum(
            detecter_divergence(df["Close"], calc[colonne], fenetre)
            for colonne in ("RSI", "Histogramme", "OBV")
        )

    def interpreter(self, df, calc):
        courte = self._consensus(df, calc, self.p("fenetre_courte"))
        longue = self._consensus(df, calc, self.p("fenetre_longue"))
        return [
            critere_choix(
                "DIV_COURTE",
                "Divergences sur %d bougies" % self.p("fenetre_courte"),
                courte,
                _TABLE_DIVERGENCE,
                valeur_num=courte,
            ),
            critere_choix(
                "DIV_LONGUE",
                "Divergences sur %d bougies" % self.p("fenetre_longue"),
                longue,
                _TABLE_DIVERGENCE,
                valeur_num=longue,
            ),
        ]


# ===========================================================================
# 4. EPUISEMENT
# ===========================================================================
_TABLE_CLIMAX = {
    "capitulation": (
        "Capitulation absorbée : volume record, grande bougie, clôture haute",
        Signal.TRES_POSITIF,
    ),
    "distribution": (
        "Distribution : volume record, grande bougie, clôture basse",
        Signal.TRES_NEGATIF,
    ),
    # Un volume record qui pousse dans le sens du mouvement est une
    # continuation, pas un épuisement. On refuse de le compter comme un signal :
    # ce serait rejouer exactement ce que font déjà les indicateurs suiveurs.
    "expansion": ("Volume record dans le sens du mouvement", Signal.NEUTRE),
    "calme": ("Pas de climax de volume", Signal.NEUTRE),
}


class Epuisement(Indicateur):
    """Un sommet de volume sur une grande bougie qui clôture à l'opposé de son
    mouvement signe une absorption : ceux qui devaient vendre ont vendu. C'est
    l'information la plus éloignée d'une moyenne mobile qu'un OHLCV contienne."""

    code = "EPUISEMENT"
    nom = "Épuisement (climax de volume)"
    categorie = Categorie.VOLUME
    approche = Approche.ANTICIPATION
    description = (
        "Repère les climax de volume sur grande amplitude dont la clôture "
        "contredit le mouvement (capitulation, distribution), et la présence "
        "répétée de mèches de rejet."
    )
    periodes_min = 60
    PARAMETRES_DEFAUT = {
        "periode_volume": 20,
        "periode_atr": 14,
        "fenetre_meche": 3,
        "jambe": 5,
        "seuil_volume": 2.0,
        "seuil_amplitude": 1.3,
    }

    def calculer(self, df):
        n = self.p("periode_volume")
        volume = df["Volume"]
        amplitude = df["High"] - df["Low"]
        extremes = pd.concat([df["Open"], df["Close"]], axis=1)
        corps_haut, corps_bas = extremes.max(axis=1), extremes.min(axis=1)
        # Mèche nette : basse moins haute, rapportée à l'amplitude de la bougie.
        # +1 = bougie tout en mèche basse (rejet des vendeurs), -1 = l'inverse.
        meche = ((corps_bas - df["Low"]) - (df["High"] - corps_haut)) / (amplitude + EPS)

        return pd.DataFrame(
            {
                "Volume_z": (volume - sma(volume, n)) / (volume.rolling(n).std() + EPS),
                "Amplitude_atr": amplitude / (atr(df, self.p("periode_atr")) + EPS),
                "Position": (df["Close"] - df["Low"]) / (amplitude + EPS),
                "Meche": meche.rolling(self.p("fenetre_meche")).mean(),
                "Jambe": df["Close"].diff(self.p("jambe")),
            },
            index=df.index,
        )

    def interpreter(self, df, calc):
        volume = derniere(calc["Volume_z"])
        amplitude = derniere(calc["Amplitude_atr"])
        position = derniere(calc["Position"])
        jambe = derniere(calc["Jambe"])

        if not valide(volume, amplitude, position, jambe):
            cle = "indisponible"          # absent de la table -> critère neutralisé
        elif volume < self.p("seuil_volume") or amplitude < self.p("seuil_amplitude"):
            cle = "calme"
        elif jambe < 0 and position > 0.66:
            cle = "capitulation"
        elif jambe > 0 and position < 0.34:
            cle = "distribution"
        else:
            cle = "expansion"

        return [
            critere_choix(
                "EPU_CLIMAX", "Climax de volume", cle, _TABLE_CLIMAX, valeur_num=volume
            ),
            critere_paliers(
                "EPU_MECHE",
                "Mèches de rejet (moyenne sur 3 bougies)",
                derniere(calc["Meche"]),
                [
                    (-0.30, "Mèches hautes répétées (offre au-dessus)", Signal.TRES_NEGATIF),
                    (-0.12, "Mèches hautes (vendeurs présents)", Signal.NEGATIF),
                    (0.12, "Bougies équilibrées", Signal.NEUTRE),
                    (0.30, "Mèches basses (acheteurs présents)", Signal.POSITIF),
                    (math.inf, "Mèches basses répétées (demande en dessous)",
                     Signal.TRES_POSITIF),
                ],
            ),
        ]


# ===========================================================================
# 5. ASYMETRIE DES RENDEMENTS
# ===========================================================================
class Asymetrie(Indicateur):
    """Regarde le troisième moment des rendements, pas leur moyenne. Un actif
    dont les rendements penchent fortement à la hausse attire les paris de
    loterie et se paie donc trop cher : l'asymétrie se lit à contre-courant."""

    code = "ASYMETRIE"
    nom = "Asymétrie des rendements (40)"
    categorie = Categorie.VOLATILITE
    approche = Approche.ANTICIPATION
    description = (
        "Asymétrie (skewness) des rendements récents et concentration du "
        "mouvement : une hausse portée par une seule bougie est bien plus "
        "fragile que la même hausse étalée sur quarante."
    )
    periodes_min = 80
    PARAMETRES_DEFAUT = {"periode": 40}

    def calculer(self, df):
        n = self.p("periode")
        rendement = df["Close"].pct_change()

        # Part du chemin parcouru portée par la plus grosse bougie de la
        # fenêtre. `max + min` est positif quand la plus grosse bougie est une
        # hausse : c'est ce qui donne son SENS à la concentration, sans avoir à
        # aller chercher l'indice de l'extremum.
        plus_haute = rendement.rolling(n).max()
        plus_basse = rendement.rolling(n).min()
        part = pd.concat([plus_haute, -plus_basse], axis=1).max(axis=1) / (
            rendement.abs().rolling(n).sum() + EPS
        )
        sens = np.sign(plus_haute + plus_basse)

        return pd.DataFrame(
            {
                "Asymetrie": rendement.rolling(n).skew(),
                # Signe inversé : lecture à contre-courant, comme l'asymétrie.
                "Concentration": -sens * part,
            },
            index=df.index,
        )

    def interpreter(self, df, calc):
        return [
            critere_paliers(
                "ASY_SKEW",
                "Asymétrie des rendements",
                derniere(calc["Asymetrie"]),
                [
                    (-1.00, "Fortement asymétrique à la baisse (excès déjà purgé)",
                     Signal.TRES_POSITIF),
                    (-0.35, "Asymétrie baissière", Signal.POSITIF),
                    (0.35, "Rendements symétriques", Signal.NEUTRE),
                    (1.00, "Asymétrie haussière", Signal.NEGATIF),
                    (math.inf, "Fortement asymétrique à la hausse (effet loterie)",
                     Signal.TRES_NEGATIF),
                ],
            ),
            critere_paliers(
                "ASY_CONCENTRATION",
                "Concentration du mouvement",
                derniere(calc["Concentration"]),
                [
                    (-0.22, "Hausse portée par une seule bougie (fragile)",
                     Signal.TRES_NEGATIF),
                    (-0.12, "Hausse concentrée sur peu de bougies", Signal.NEGATIF),
                    (0.12, "Mouvement réparti sur la période", Signal.NEUTRE),
                    (0.22, "Baisse concentrée sur peu de bougies", Signal.POSITIF),
                    (math.inf, "Baisse portée par une seule bougie (fragile)",
                     Signal.TRES_POSITIF),
                ],
            ),
        ]


# ===========================================================================
# 6. COMPRESSION DE VOLATILITE  (contexte)
# ===========================================================================
class Compression(Indicateur):
    """Les bandes se resserrent avant les grands mouvements. Cet indicateur dit
    QUAND quelque chose va probablement se produire — jamais dans quel sens.
    Il est donc purement contextuel et n'entre dans aucun score."""

    code = "COMPRESSION"
    nom = "Compression de volatilité"
    categorie = Categorie.VOLATILITE
    approche = Approche.ANTICIPATION
    contextuel = True
    description = (
        "Largeur des bandes de Bollinger située dans son propre historique : "
        "repère les ressorts comprimés et le moment où ils se détendent. "
        "Indique l'imminence d'un mouvement, jamais sa direction."
    )
    periodes_min = 120
    PARAMETRES_DEFAUT = {"periode": 20, "ecarts": 2.0, "fenetre_rang": 250, "fenetre_pente": 5}

    def calculer(self, df):
        basse, mediane, haute = bandes_bollinger(
            df["Close"], self.p("periode"), self.p("ecarts")
        )
        largeur = (haute - basse) / (mediane.abs() + EPS)
        return pd.DataFrame(
            {
                "Largeur": largeur,
                "Rang": rang_percentile(largeur, self.p("fenetre_rang")),
                "Detente": largeur.diff(self.p("fenetre_pente")) / (largeur.abs() + EPS),
            },
            index=df.index,
        )

    def interpreter(self, df, calc):
        return [
            critere_paliers(
                "COMP_RESSORT",
                "État du ressort",
                derniere(calc["Rang"]),
                [
                    (0.10, "Compression extrême (mouvement imminent)", Signal.NEUTRE),
                    (0.30, "Bandes resserrées", Signal.NEUTRE),
                    (0.70, "Largeur ordinaire", Signal.NEUTRE),
                    (0.90, "Bandes écartées", Signal.NEUTRE),
                    (math.inf, "Expansion extrême (mouvement déjà consommé)", Signal.NEUTRE),
                ],
                directionnel=False,
            ),
            critere_paliers(
                "COMP_DETENTE",
                "Sens de la respiration",
                derniere(calc["Detente"]),
                [
                    (-0.20, "Compression en cours", Signal.NEUTRE),
                    (-0.05, "Léger resserrement", Signal.NEUTRE),
                    (0.05, "Largeur stable", Signal.NEUTRE),
                    (0.20, "Début d'expansion", Signal.NEUTRE),
                    (math.inf, "Détente franche du ressort", Signal.NEUTRE),
                ],
                directionnel=False,
            ),
        ]


# ===========================================================================
# 7. EFFICIENCE DU MOUVEMENT  (contexte)
# ===========================================================================
class Efficience(Indicateur):
    """Le méta-indicateur : dit laquelle des deux approches a une chance de
    fonctionner en ce moment. Un marché au chemin efficient et aux rendements
    persistants est le terrain des suiveurs ; un marché haché aux rendements
    qui se contredisent est celui de l'anticipation."""

    code = "EFFICIENCE"
    nom = "Efficience du mouvement"
    categorie = Categorie.TENDANCE
    approche = Approche.ANTICIPATION
    contextuel = True
    description = (
        "Rapport entre le déplacement net et le chemin réellement parcouru "
        "(ratio de Kaufman), et autocorrélation des rendements. Ensemble, ils "
        "disent si le marché est en régime de tendance ou de retour à la moyenne."
    )
    periodes_min = 120
    PARAMETRES_DEFAUT = {"periode": 20, "fenetre_memoire": 60}

    def calculer(self, df):
        n = self.p("periode")
        variation = df["Close"].diff()
        deplacement = (df["Close"] - df["Close"].shift(n)).abs()
        chemin = variation.abs().rolling(n).sum()

        rendement = df["Close"].pct_change()
        memoire = rendement.rolling(self.p("fenetre_memoire")).corr(rendement.shift(1))

        return pd.DataFrame(
            {"Efficience": deplacement / (chemin + EPS), "Memoire": memoire}, index=df.index
        )

    def interpreter(self, df, calc):
        return [
            critere_paliers(
                "EFF_REGIME",
                "Efficience du chemin",
                derniere(calc["Efficience"]),
                [
                    (0.20, "Marché sans direction (les suiveurs s'y font hacher)",
                     Signal.NEUTRE),
                    (0.35, "Marché peu directionnel", Signal.NEUTRE),
                    (0.55, "Marché moyennement directionnel", Signal.NEUTRE),
                    (math.inf, "Marché franchement directionnel", Signal.NEUTRE),
                ],
                directionnel=False,
            ),
            critere_paliers(
                "EFF_MEMOIRE",
                "Mémoire des rendements",
                derniere(calc["Memoire"]),
                [
                    (-0.15, "Rendements qui se contredisent (terrain de l'anticipation)",
                     Signal.NEUTRE),
                    (-0.05, "Légère tendance au retour à la moyenne", Signal.NEUTRE),
                    (0.05, "Aucune mémoire d'une bougie à l'autre", Signal.NEUTRE),
                    (0.15, "Légère persistance", Signal.NEUTRE),
                    (math.inf, "Rendements qui s'enchaînent (terrain des suiveurs)",
                     Signal.NEUTRE),
                ],
                directionnel=False,
            ),
        ]
