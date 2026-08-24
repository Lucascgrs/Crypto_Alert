"""
Socle commun à tous les indicateurs.

Idée directrice du projet : un indicateur ne renvoie JAMAIS un nombre brut au
tableau de bord, mais des **critères qualitatifs**. Un critère, c'est une phrase
lisible ("Prix au-dessus de la bande supérieure") associée à un **signal**
positif / neutre / négatif.

Chaque indicateur respecte donc un contrat en deux temps :

  1. `calculer(df)`          -> les colonnes numériques de l'indicateur ;
  2. `interpreter(df, calc)` -> la traduction de ces nombres en critères.

Cette séparation permet de réutiliser les valeurs numériques (graphiques,
export Excel) tout en gardant l'interprétation isolée et facile à ajuster.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

import pandas as pd

import config


# ===========================================================================
# 1. SIGNAL ET CATEGORIE
# ===========================================================================
class Signal(Enum):
    """Orientation d'un critère. La valeur numérique sert à l'agrégation."""

    TRES_POSITIF = 2
    POSITIF = 1
    NEUTRE = 0
    NEGATIF = -1
    TRES_NEGATIF = -2

    @property
    def libelle(self) -> str:
        return {
            Signal.TRES_POSITIF: "Très positif",
            Signal.POSITIF: "Positif",
            Signal.NEUTRE: "Neutre",
            Signal.NEGATIF: "Négatif",
            Signal.TRES_NEGATIF: "Très négatif",
        }[self]

    @property
    def symbole(self) -> str:
        """Pictogramme court pour l'affichage console / futur tableau de bord."""
        return {
            Signal.TRES_POSITIF: "++",
            Signal.POSITIF: "+",
            Signal.NEUTRE: "=",
            Signal.NEGATIF: "-",
            Signal.TRES_NEGATIF: "--",
        }[self]


class Categorie(Enum):
    """Famille d'indicateurs : sert à regrouper le tableau de bord."""

    TENDANCE = "Tendance"
    MOMENTUM = "Momentum"
    VOLATILITE = "Volatilité"
    VOLUME = "Volume"


def qualifier_score(score: float | None) -> str:
    """Traduit un score de [-1, 1] en libellé lisible (cf. config.SEUILS_SYNTHESE)."""
    if score is None or (isinstance(score, float) and math.isnan(score)):
        return "Non disponible"
    for borne, libelle in config.SEUILS_SYNTHESE:
        if score < borne:
            return libelle
    return config.SEUILS_SYNTHESE[-1][1]


# ===========================================================================
# 2. CRITERE QUALITATIF
# ===========================================================================
@dataclass
class Critere:
    """
    Une observation qualitative issue d'un indicateur.

    code         : identifiant technique, ex. "BB_POSITION"
    libelle      : ce qui est mesuré, ex. "Position dans les bandes"
    valeur       : le critère qualitatif, ex. "Au-dessus de la bande supérieure"
    signal       : orientation positive / neutre / négative
    valeur_num   : le nombre d'origine, conservé pour la transparence (info-bulle)
    directionnel : False pour un critère de CONTEXTE (volatilité, force de
                   tendance, niveau de volume) qui décrit l'état du marché sans
                   dire s'il est haussier ou baissier. Ces critères sont affichés
                   mais exclus du calcul de score.
    """

    code: str
    libelle: str
    valeur: str
    signal: Signal
    valeur_num: float | None = None
    directionnel: bool = True

    def to_dict(self) -> dict:
        """Format plat, prêt pour un DataFrame ou une API."""
        return {
            "code": self.code,
            "libelle": self.libelle,
            "valeur": self.valeur,
            "signal": self.signal.libelle,
            "score": self.signal.value,
            "valeur_num": self.valeur_num,
            "directionnel": self.directionnel,
        }


# ===========================================================================
# 3. RESULTAT D'UN INDICATEUR
# ===========================================================================
@dataclass
class ResultatIndicateur:
    """Ce que renvoie un indicateur pour une crypto à un instant donné."""

    code: str
    nom: str
    categorie: Categorie
    criteres: list[Critere] = field(default_factory=list)
    erreur: str | None = None

    @property
    def score(self) -> float:
        """
        Moyenne des signaux directionnels, ramenée dans [-1, 1].
        Les critères de contexte (directionnel=False) sont ignorés.
        """
        directionnels = [c for c in self.criteres if c.directionnel]
        if not directionnels:
            return 0.0
        return sum(c.signal.value for c in directionnels) / (2 * len(directionnels))

    @property
    def porte_une_direction(self) -> bool:
        """
        True si l'indicateur produit au moins un critère directionnel.

        Certains indicateurs (l'ATR par exemple) sont purement contextuels : ils
        décrivent le marché sans jamais dire s'il est haussier. Leur score vaut
        toujours 0 et ne doit donc PAS entrer dans les moyennes, sous peine de
        tirer artificiellement tous les scores globaux vers le neutre.
        """
        return any(c.directionnel for c in self.criteres)

    @property
    def synthese(self) -> str:
        """Libellé global de l'indicateur, ex. 'Positif'."""
        if self.erreur:
            return "Non disponible"
        if not self.porte_une_direction:
            return "Contexte"
        return qualifier_score(self.score)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "nom": self.nom,
            "categorie": self.categorie.value,
            "score": round(self.score, 3),
            "synthese": self.synthese,
            "erreur": self.erreur,
            "criteres": [c.to_dict() for c in self.criteres],
        }


# ===========================================================================
# 4. OUTILS DE TRADUCTION NOMBRE -> CRITERE
# ===========================================================================
def classer(valeur, paliers, defaut=("Non disponible", Signal.NEUTRE)):
    """
    Traduit un nombre en couple (libellé qualitatif, signal).

    `paliers` : liste [(borne_superieure, libellé, signal), ...] triée par borne
    croissante, la dernière borne valant math.inf. Le premier palier dont la
    borne dépasse strictement la valeur est retenu.

    Les valeurs manquantes (NaN, None) renvoient `defaut` : c'est le garde-fou
    qui évite qu'un indicateur pas encore « chaud » soit lu comme négatif.
    """
    if valeur is None or (isinstance(valeur, float) and math.isnan(valeur)):
        return defaut
    for borne, libelle, signal in paliers:
        if valeur < borne:
            return libelle, signal
    return paliers[-1][1], paliers[-1][2]


def critere_paliers(code, libelle, valeur_num, paliers, directionnel=True) -> Critere:
    """Raccourci : construit un Critere directement depuis une grille de paliers."""
    texte, signal = classer(valeur_num, paliers)
    if texte == "Non disponible":
        return Critere(code, libelle, texte, Signal.NEUTRE, None, directionnel=False)
    return Critere(code, libelle, texte, signal, valeur_num, directionnel)


def critere_choix(code, libelle, cle, table, valeur_num=None, directionnel=True) -> Critere:
    """
    Raccourci pour un critère à cas discrets.
    `table` : dict {clé: (libellé, Signal)}. Une clé absente donne "Non disponible".
    """
    if cle not in table:
        return Critere(code, libelle, "Non disponible", Signal.NEUTRE, None, directionnel=False)
    texte, signal = table[cle]
    return Critere(code, libelle, texte, signal, valeur_num, directionnel)


def paliers_ecart(reference: str, faible: float = 0.005, fort: float = 0.05) -> list:
    """
    Grille de paliers standard pour un écart relatif « prix vs niveau ».

    Cette grille revient partout (prix vs moyenne mobile, vs Kijun, vs Supertrend...)
    d'où sa mutualisation. Les deux seuils délimitent trois zones symétriques :
    au contact (< `faible`), franchement d'un côté, très éloigné (> `fort`).
    """
    return [
        (-fort, f"Nettement sous {reference}", Signal.TRES_NEGATIF),
        (-faible, f"Sous {reference}", Signal.NEGATIF),
        (faible, f"Au contact de {reference}", Signal.NEUTRE),
        (fort, f"Au-dessus de {reference}", Signal.POSITIF),
        (math.inf, f"Nettement au-dessus de {reference}", Signal.TRES_POSITIF),
    ]


# ===========================================================================
# 5. CLASSE DE BASE DES INDICATEURS
# ===========================================================================
class Indicateur(ABC):
    """
    Classe mère de tous les indicateurs.

    Attributs de classe à renseigner dans chaque sous-classe :
      code              : identifiant court et stable (sélection dans l'UI)
      nom               : libellé affiché
      categorie         : Categorie.TENDANCE / MOMENTUM / VOLATILITE / VOLUME
      description       : une phrase expliquant ce que l'indicateur mesure
      periodes_min      : nombre de bougies minimum pour un calcul fiable
      PARAMETRES_DEFAUT : réglages surchargeables à l'instanciation
    """

    code: str = ""
    nom: str = ""
    categorie: Categorie = Categorie.TENDANCE
    description: str = ""
    periodes_min: int = 50
    PARAMETRES_DEFAUT: dict = {}

    def __init__(self, **parametres):
        # Les réglages passés à l'instanciation écrasent les valeurs par défaut.
        self.parametres = {**self.PARAMETRES_DEFAUT, **parametres}

    def p(self, cle):
        """Accès court à un paramètre de réglage."""
        return self.parametres[cle]

    @abstractmethod
    def calculer(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calcule les colonnes numériques de l'indicateur (df OHLCV en entrée)."""

    @abstractmethod
    def interpreter(self, df: pd.DataFrame, calc: pd.DataFrame) -> list[Critere]:
        """Traduit les dernières valeurs calculées en critères qualitatifs."""

    def analyser(self, df: pd.DataFrame) -> ResultatIndicateur:
        """
        Enchaîne calcul + interprétation en absorbant les erreurs : un indicateur
        qui échoue ne doit jamais faire tomber l'analyse des autres.
        """
        entete = dict(code=self.code, nom=self.nom, categorie=self.categorie)

        if df is None or len(df) < self.periodes_min:
            dispo = 0 if df is None else len(df)
            bougie = "bougie" if dispo <= 1 else "bougies"
            return ResultatIndicateur(
                **entete,
                erreur=f"Historique insuffisant ({dispo} {bougie}, {self.periodes_min} requises)",
            )
        try:
            calc = self.calculer(df)
            return ResultatIndicateur(**entete, criteres=self.interpreter(df, calc))
        except Exception as e:  # on veut vraiment tout attraper ici
            return ResultatIndicateur(**entete, erreur=f"{type(e).__name__}: {e}")

    def fiche(self) -> dict:
        """Descriptif de l'indicateur (alimente la liste sélectionnable de l'UI)."""
        return {
            "code": self.code,
            "nom": self.nom,
            "categorie": self.categorie.value,
            "description": self.description,
            "periodes_min": self.periodes_min,
            "parametres": dict(self.parametres),
        }
