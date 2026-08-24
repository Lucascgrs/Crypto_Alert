"""
Boîte à outils numérique partagée par les indicateurs.

Uniquement des fonctions pures sur des séries pandas : aucune notion de signal
ou de critère ici, c'est le rôle de `base.py` et des modules d'indicateurs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

EPS = 1e-12  # évite les divisions par zéro sans fausser les ordres de grandeur


# ---------------------------------------------------------------------------
# Moyennes
# ---------------------------------------------------------------------------
def sma(serie: pd.Series, periode: int) -> pd.Series:
    """Moyenne mobile simple."""
    return serie.rolling(periode).mean()


def ema(serie: pd.Series, periode: int) -> pd.Series:
    """Moyenne mobile exponentielle."""
    return serie.ewm(span=periode, adjust=False).mean()


def lissage_wilder(serie: pd.Series, periode: int) -> pd.Series:
    """
    Lissage de Wilder (utilisé par RSI, ATR, ADX) : une EMA de facteur 1/période.
    Réagit deux fois moins vite qu'une EMA classique de même période.
    """
    return serie.ewm(alpha=1 / periode, adjust=False).mean()


# ---------------------------------------------------------------------------
# Volatilité de base
# ---------------------------------------------------------------------------
def true_range(df: pd.DataFrame) -> pd.Series:
    """
    True Range : la plus grande des trois amplitudes (haut-bas, haut-clôture
    précédente, bas-clôture précédente). Capture les gaps d'ouverture.
    """
    haut_bas = df["High"] - df["Low"]
    haut_cloture = (df["High"] - df["Close"].shift()).abs()
    bas_cloture = (df["Low"] - df["Close"].shift()).abs()
    return pd.concat([haut_bas, haut_cloture, bas_cloture], axis=1).max(axis=1)


def atr(df: pd.DataFrame, periode: int = 14) -> pd.Series:
    """Average True Range (lissage de Wilder)."""
    return lissage_wilder(true_range(df), periode)


# ---------------------------------------------------------------------------
# Lecture de séries
# ---------------------------------------------------------------------------
def derniere(serie: pd.Series) -> float:
    """
    Dernière valeur d'une série, convertie en float.
    Renvoie NaN si la série est vide : les fonctions de classement savent gérer.
    """
    if serie is None or len(serie) == 0:
        return float("nan")
    valeur = serie.iloc[-1]
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return float("nan")


def valide(*valeurs) -> bool:
    """True si toutes les valeurs sont des nombres exploitables (ni None ni NaN)."""
    for v in valeurs:
        if v is None:
            return False
        try:
            if np.isnan(v):
                return False
        except TypeError:
            return False
    return True


def ecart_relatif(valeur: float, reference: float) -> float:
    """
    Écart en proportion entre une valeur et une référence : (val - ref) / |ref|.
    C'est la brique qui rend les comparaisons de prix comparables entre cryptos
    (un écart de 200 $ ne veut rien dire, un écart de +3 % si).
    """
    if not valide(valeur, reference):
        return float("nan")
    return (valeur - reference) / (abs(reference) + EPS)


# ---------------------------------------------------------------------------
# Dynamique et régime
# ---------------------------------------------------------------------------
def pente(serie: pd.Series, periodes: int = 5) -> pd.Series:
    """
    Variation relative d'une série sur N périodes, sans unité.
    Sert à répondre à « la moyenne monte-t-elle ? » plutôt qu'à « où est-elle ? ».
    """
    reference = serie.shift(periodes)
    return (serie - reference) / (reference.abs() + EPS)


def rang_percentile(serie: pd.Series, fenetre: int = 250) -> pd.Series:
    """
    Rang de la valeur courante dans sa propre fenêtre glissante, entre 0 et 1.

    Indispensable pour les critères de type « bandes resserrées » : la largeur
    de Bollinger n'a pas de seuil universel, mais un rang de 0,05 signifie
    toujours « parmi les 5 % de périodes les plus calmes de l'historique récent ».
    """
    minimum = max(20, fenetre // 4)
    return serie.rolling(fenetre, min_periods=minimum).rank(pct=True)


def croisement_recent(serie_a: pd.Series, serie_b: pd.Series, fenetre: int = 3) -> int:
    """
    Détecte un croisement récent entre deux séries.

    Renvoie  1  si A est passée au-dessus de B dans les `fenetre` dernières bougies,
            -1  si A est passée en dessous,
             0  s'il n'y a pas eu de croisement (situation établie).
    """
    ecart = (serie_a - serie_b).dropna()
    if len(ecart) < fenetre + 1:
        return 0
    signes = np.sign(ecart.iloc[-(fenetre + 1):].to_numpy())
    # On remonte du plus récent au plus ancien : le premier croisement trouvé
    # est le plus récent.
    for i in range(len(signes) - 1, 0, -1):
        if signes[i] > 0 >= signes[i - 1]:
            return 1
        if signes[i] < 0 <= signes[i - 1]:
            return -1
    return 0


def detecter_divergence(prix: pd.Series, oscillateur: pd.Series, fenetre: int = 40) -> int:
    """
    Détection simplifiée de divergence prix / oscillateur.

    On coupe la fenêtre récente en deux moitiés et on compare leurs extrêmes :
      1  = divergence haussière (le prix fait un plus bas, pas l'oscillateur)
     -1  = divergence baissière (le prix fait un plus haut, pas l'oscillateur)
      0  = pas de divergence détectée

    Approche volontairement grossière (pas de détection de pivots) : elle suffit
    à lever un drapeau dans un tableau de bord, pas à déclencher un ordre.
    """
    donnees = pd.concat([prix, oscillateur], axis=1).dropna()
    if len(donnees) < fenetre:
        return 0

    recent = donnees.iloc[-fenetre:]
    milieu = fenetre // 2
    p_avant, p_apres = recent.iloc[:milieu, 0], recent.iloc[milieu:, 0]
    o_avant, o_apres = recent.iloc[:milieu, 1], recent.iloc[milieu:, 1]

    if p_apres.min() < p_avant.min() and o_apres.min() > o_avant.min():
        return 1
    if p_apres.max() > p_avant.max() and o_apres.max() < o_avant.max():
        return -1
    return 0


# ---------------------------------------------------------------------------
# Indicateurs de base réutilisés par plusieurs modules
# ---------------------------------------------------------------------------
def rsi(serie: pd.Series, periode: int = 14) -> pd.Series:
    """RSI de Wilder, borné entre 0 et 100."""
    variation = serie.diff()
    hausses = variation.clip(lower=0)
    baisses = -variation.clip(upper=0)
    moyenne_hausses = lissage_wilder(hausses, periode)
    moyenne_baisses = lissage_wilder(baisses, periode)
    force = moyenne_hausses / (moyenne_baisses + EPS)
    resultat = 100 - (100 / (1 + force))

    # Cas d'un prix parfaitement immobile (actif illiquide, bougies plates) :
    # la formule donnerait 0, donc « survente extrême », alors qu'il ne s'est
    # tout simplement rien passé. On force la valeur neutre.
    immobile = (moyenne_hausses <= EPS) & (moyenne_baisses <= EPS)
    return resultat.mask(immobile, 50.0)


def bandes_bollinger(serie: pd.Series, periode: int = 20, ecarts: float = 2.0):
    """
    Bandes de Bollinger : (bande basse, médiane, bande haute).
    La médiane est une SMA, les bandes sont à N écarts-types de celle-ci.
    """
    mediane = sma(serie, periode)
    ecart_type = serie.rolling(periode).std()
    return mediane - ecarts * ecart_type, mediane, mediane + ecarts * ecart_type
