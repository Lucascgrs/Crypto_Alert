"""
Couche de présentation commune aux deux interfaces.

Tout ce qui relève de la MISE EN FORME (couleurs, libellés courts, formats de
nombres) vit ici, pour que l'interface de bureau et l'interface web restent
strictement cohérentes : une même crypto doit avoir la même couleur des deux
côtés. Aucune de ces fonctions ne calcule quoi que ce soit de financier.
"""

from __future__ import annotations

import math

from indicateurs import Signal

# ---------------------------------------------------------------------------
# Couleurs
# ---------------------------------------------------------------------------
# Un seul jeu de couleurs pleines, choisi pour rester lisible avec du texte
# blanc aussi bien sur un thème clair que sombre (les deux interfaces
# proposent les deux thèmes).
COULEURS_SIGNAL: dict[Signal, str] = {
    Signal.TRES_POSITIF: "#157f3d",
    Signal.POSITIF: "#2e8b57",
    Signal.NEUTRE: "#6b7280",
    Signal.NEGATIF: "#d1495b",
    Signal.TRES_NEGATIF: "#9b1c2e",
}

COULEUR_INDISPONIBLE = "#3f4550"
COULEUR_CONTEXTE = "#4b5563"  # critères non directionnels : gris plus discret

# Paliers de couleur pour un score continu dans [-1, 1].
# Alignés sur config.SEUILS_SYNTHESE pour que couleur et libellé concordent.
_PALIERS_COULEUR_SCORE = [
    (-0.50, COULEURS_SIGNAL[Signal.TRES_NEGATIF]),
    (-0.15, COULEURS_SIGNAL[Signal.NEGATIF]),
    (0.15, COULEURS_SIGNAL[Signal.NEUTRE]),
    (0.50, COULEURS_SIGNAL[Signal.POSITIF]),
    (math.inf, COULEURS_SIGNAL[Signal.TRES_POSITIF]),
]


def couleur_score(score: float | None) -> str:
    """Couleur d'un score continu de [-1, 1]."""
    if score is None or (isinstance(score, float) and math.isnan(score)):
        return COULEUR_INDISPONIBLE
    for borne, couleur in _PALIERS_COULEUR_SCORE:
        if score < borne:
            return couleur
    return _PALIERS_COULEUR_SCORE[-1][1]


def couleur_synthese(synthese: str) -> str:
    """Couleur associée à un libellé de synthèse d'indicateur."""
    correspondances = {
        "Fortement positif": COULEURS_SIGNAL[Signal.TRES_POSITIF],
        "Positif": COULEURS_SIGNAL[Signal.POSITIF],
        "Neutre": COULEURS_SIGNAL[Signal.NEUTRE],
        "Négatif": COULEURS_SIGNAL[Signal.NEGATIF],
        "Fortement négatif": COULEURS_SIGNAL[Signal.TRES_NEGATIF],
        "Contexte": COULEUR_CONTEXTE,
    }
    return correspondances.get(synthese, COULEUR_INDISPONIBLE)


def couleur_critere(critere) -> str:
    """Couleur d'un critère : les critères de contexte restent volontairement gris."""
    if not critere.directionnel:
        return COULEUR_CONTEXTE
    return COULEURS_SIGNAL[critere.signal]


# ---------------------------------------------------------------------------
# Libellés courts
# ---------------------------------------------------------------------------
# Version compacte des synthèses, pour les cellules étroites du tableau.
ABREVIATIONS_SYNTHESE = {
    "Fortement positif": "++",
    "Positif": "+",
    "Neutre": "=",
    "Négatif": "-",
    "Fortement négatif": "--",
    "Contexte": "·",
    "Non disponible": "",
}


def abreger(synthese: str) -> str:
    return ABREVIATIONS_SYNTHESE.get(synthese, "?")


# ---------------------------------------------------------------------------
# Formats de nombres
# ---------------------------------------------------------------------------
def formater_prix(valeur: float | None) -> str:
    """
    Prix lisible quel que soit l'ordre de grandeur : le BTC se lit en dizaines
    de milliers, certains jetons en millionièmes de dollar.
    """
    if valeur is None or (isinstance(valeur, float) and math.isnan(valeur)):
        return "—"
    if valeur >= 1000:
        return f"{valeur:,.0f} $".replace(",", " ")
    if valeur >= 1:
        return f"{valeur:,.2f} $".replace(",", " ")
    if valeur >= 0.01:
        return f"{valeur:.4f} $"
    return f"{valeur:.8f} $".rstrip("0")


def formater_capitalisation(valeur: float | None) -> str:
    """Capitalisation abrégée en milliards / millions."""
    if valeur is None or (isinstance(valeur, float) and math.isnan(valeur)):
        return "—"
    if valeur >= 1e12:
        return f"{valeur / 1e12:.2f} T$"
    if valeur >= 1e9:
        return f"{valeur / 1e9:.1f} Md$"
    if valeur >= 1e6:
        return f"{valeur / 1e6:.0f} M$"
    return f"{valeur:,.0f} $".replace(",", " ")


def formater_variation(valeur: float | None) -> str:
    """Variation en pourcentage, toujours signée."""
    if valeur is None or (isinstance(valeur, float) and math.isnan(valeur)):
        return "—"
    return f"{valeur:+.2f} %"


def formater_score(score: float | None) -> str:
    if score is None or (isinstance(score, float) and math.isnan(score)):
        return "—"
    return f"{score:+.2f}"


def formater_valeur_critere(valeur: float | None) -> str:
    """
    Valeur numérique brute d'un critère, affichée en info complémentaire.
    Format court : c'est le libellé qualitatif qui porte l'information.
    """
    if valeur is None or (isinstance(valeur, float) and math.isnan(valeur)):
        return ""
    if isinstance(valeur, float) and valeur.is_integer():
        return str(int(valeur))
    return f"{valeur:,.4g}"


# ---------------------------------------------------------------------------
# Options proposées dans les deux interfaces
# ---------------------------------------------------------------------------
# Du plus long au plus court. Les intervalles en minutes servent à l'analyse
# réactive ; ils ne sont proposés que par Binance (Yahoo ne remonte pas assez
# loin en intraday pour alimenter une MM 200).
INTERVALLES = {
    "Journalier (1d)": "1d",
    "4 heures (4h)": "4h",
    "1 heure (1h)": "1h",
    "30 minutes (30m)": "30m",
    "15 minutes (15m)": "15m",
    "5 minutes (5m)": "5m",
    "1 minute (1m)": "1m",
}

# Profondeur d'historique adaptée à chaque intervalle : il faut au moins ~250
# bougies pour la MM 200 et les rangs-percentiles, sans télécharger inutilement.
# Binance plafonne à 1000 bougies par appel, d'où les valeurs des intervalles courts.
BOUGIES_PAR_INTERVALLE = {
    "1d": 400, "4h": 700, "1h": 800,
    "30m": 900, "15m": 1000, "5m": 1000, "1m": 1000,
}
