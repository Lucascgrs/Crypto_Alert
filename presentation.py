"""
Couche de présentation commune aux deux interfaces.

Tout ce qui relève de la MISE EN FORME (couleurs, libellés courts, formats de
nombres) vit ici, pour que l'interface de bureau et l'interface web restent
strictement cohérentes : une même crypto doit avoir la même couleur des deux
côtés. Aucune de ces fonctions ne calcule quoi que ce soit de financier.
"""

from __future__ import annotations

import math
from zoneinfo import ZoneInfo

import pandas as pd

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
# Palette des séries (graphiques d'évolution)
# ---------------------------------------------------------------------------
# Palette CATÉGORIELLE : elle encode une identité (quelle crypto), pas une
# magnitude. L'ordre des emplacements est le mécanisme de sécurité pour les
# daltonismes — il n'est pas décoratif et ne doit pas être réarrangé.
#
# Les deux modes sont validés séparément (les mêmes teintes, calées sur chaque
# fond) : écart minimal entre voisines de 9,1 en clair et 8,4 en sombre sous
# simulation protanope, 19,6 / 19,3 en vision normale. Trois teintes claires
# passent sous 3:1 de contraste sur fond clair, d'où l'étiquetage direct des
# courbes et le tableau de valeurs sous le graphique.
PALETTE_SERIES = {
    "clair": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
              "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
    "sombre": ["#3987e5", "#d95926", "#199e70", "#c98500",
               "#d55181", "#008300", "#9085e9", "#e66767"],
}

# Au-delà de 8 séries, deux teintes deviennent indiscernables sous daltonisme.
# On ne génère jamais une 9e couleur : on limite la sélection.
MAX_SERIES = len(PALETTE_SERIES["clair"])

SURFACES = {"clair": "#fcfcfb", "sombre": "#1a1a19"}

# Encres : le texte porte toujours une couleur de texte, jamais celle d'une
# série. C'est la pastille colorée voisine qui porte l'identité.
ENCRES = {
    "clair": {
        "primaire": "#0b0b0b", "secondaire": "#52514e",
        "discrete": "#8a8a85", "grille": "#e6e5e1",
    },
    "sombre": {
        "primaire": "#ffffff", "secondaire": "#c3c2b7",
        "discrete": "#83827b", "grille": "#2e2e2c",
    },
}


class AttributionCouleurs:
    """
    Attribue une couleur stable à chaque crypto.

    Règle essentielle : la couleur suit l'ENTITÉ, jamais son rang. Décocher une
    crypto ne doit pas repeindre les autres — un lecteur qui a appris « BTC est
    bleu » serait sinon induit en erreur. Chaque symbole conserve donc son
    emplacement pour toute la durée de la session.
    """

    def __init__(self, mode: str = "sombre"):
        self.mode = mode
        self._emplacements: dict[str, int] = {}

    def couleur(self, symbole: str) -> str:
        palette = PALETTE_SERIES[self.mode]
        if symbole not in self._emplacements:
            occupes = set(self._emplacements.values())
            libres = [i for i in range(len(palette)) if i not in occupes]
            if not libres:
                # Ne devrait pas arriver : la sélection est plafonnée en amont.
                return ENCRES[self.mode]["discrete"]
            self._emplacements[symbole] = libres[0]
        return palette[self._emplacements[symbole]]

    def oublier(self, symboles_actifs):
        """Libère les emplacements des cryptos retirées de la sélection."""
        actifs = set(symboles_actifs)
        self._emplacements = {s: i for s, i in self._emplacements.items() if s in actifs}


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
# Fuseau horaire d'affichage
# ---------------------------------------------------------------------------
# Toutes les données de prix (Binance) et tous les horodatages internes
# (Trade.entree/sortie, journal de suivi) sont en UTC, naîfs (sans tzinfo) :
# c'est le format renvoyé par l'API, et le seul qui permette de comparer une
# échéance à une bougie sans ambiguïté. Cette fonction n'intervient qu'à la
# dernière étape, l'AFFICHAGE : convertir en heure de Paris ce qui va être lu.
FUSEAU_AFFICHAGE = ZoneInfo("Europe/Paris")


def heure_fr(valeur):
    """
    Convertit un horodatage UTC naïf en heure de Paris (gère l'heure d'été).

    Accepte un datetime/Timestamp, une Series ou un DatetimeIndex ; les valeurs
    manquantes (None, NaT) traversent sans erreur. Le résultat reste naïf : ni
    Excel ni les widgets d'affichage n'ont besoin d'un fuseau, seule l'heure
    montrée à l'écran doit être la bonne.
    """
    if isinstance(valeur, pd.DatetimeIndex):
        return valeur.tz_localize("UTC").tz_convert(FUSEAU_AFFICHAGE).tz_localize(None)
    if isinstance(valeur, pd.Series):
        return valeur.dt.tz_localize("UTC").dt.tz_convert(FUSEAU_AFFICHAGE).dt.tz_localize(None)
    if valeur is None or pd.isna(valeur):
        return valeur
    instant = pd.Timestamp(valeur)
    if instant.tzinfo is None:
        instant = instant.tz_localize("UTC")
    return instant.tz_convert(FUSEAU_AFFICHAGE).tz_localize(None)


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
