"""
Registre des indicateurs disponibles.

C'est le point d'entrée unique pour la sélection : l'interface graphique
(à venir) n'a besoin que de `catalogue()` pour afficher la liste des cases à
cocher, et de `creer()` pour instancier la sélection de l'utilisateur.

Ajouter un indicateur = écrire sa classe dans le module de sa catégorie, puis
l'ajouter à la liste `CLASSES` ci-dessous. Rien d'autre à toucher.
"""

from __future__ import annotations

import pandas as pd

from .base import Categorie, Indicateur
from .momentum import Cci, RocMultiHorizons, Rsi, Stochastique, WilliamsR
from .tendance import Adx, Aroon, Ichimoku, Macd, MoyennesMobiles, ParabolicSar, Supertrend
from .volatilite import AtrIndicateur, Bollinger, Donchian, Keltner
from .volume import ChaikinMoneyFlow, MoneyFlowIndex, Obv, VolumeRelatif

# Les 20 indicateurs retenus, ordonnés par catégorie.
CLASSES: list[type[Indicateur]] = [
    # --- Tendance (7) ---
    MoyennesMobiles,
    Macd,
    Adx,
    Ichimoku,
    Supertrend,
    ParabolicSar,
    Aroon,
    # --- Momentum (5) ---
    Rsi,
    Stochastique,
    Cci,
    WilliamsR,
    RocMultiHorizons,
    # --- Volatilité (4) ---
    Bollinger,
    AtrIndicateur,
    Keltner,
    Donchian,
    # --- Volume (4) ---
    Obv,
    VolumeRelatif,
    ChaikinMoneyFlow,
    MoneyFlowIndex,
]

# Index code -> classe, construit automatiquement pour éviter toute désynchronisation.
REGISTRE: dict[str, type[Indicateur]] = {classe.code: classe for classe in CLASSES}

# Sélection par défaut : tout est activé.
CODES_PAR_DEFAUT: list[str] = list(REGISTRE)


def creer(codes: list[str] | None = None, reglages: dict | None = None) -> list[Indicateur]:
    """
    Instancie les indicateurs demandés.

    codes    : liste de codes (ex. ["BOLLINGER", "RSI"]). None = tous.
    reglages : surcharges de paramètres par code,
               ex. {"RSI": {"periode": 21}, "BOLLINGER": {"ecarts": 2.5}}

    Un code inconnu lève une ValueError explicite : mieux vaut échouer tout de
    suite que d'analyser silencieusement avec un indicateur manquant.
    """
    codes = list(REGISTRE) if codes is None else list(codes)
    reglages = reglages or {}

    inconnus = [c for c in codes if c not in REGISTRE]
    if inconnus:
        raise ValueError(
            f"Indicateur(s) inconnu(s) : {inconnus}. Codes disponibles : {sorted(REGISTRE)}"
        )
    return [REGISTRE[code](**reglages.get(code, {})) for code in codes]


def codes_par_categorie(categorie: Categorie | str) -> list[str]:
    """Codes des indicateurs d'une famille donnée (pratique pour les onglets de l'UI)."""
    valeur = categorie.value if isinstance(categorie, Categorie) else categorie
    return [c.code for c in CLASSES if c.categorie.value == valeur]


def catalogue() -> pd.DataFrame:
    """
    Tableau descriptif de tous les indicateurs disponibles.
    Alimente directement la liste de sélection de l'interface.
    """
    lignes = [classe().fiche() for classe in CLASSES]
    tableau = pd.DataFrame(lignes)
    return tableau[["code", "nom", "categorie", "description", "periodes_min"]]


def periodes_requises(indicateurs: list[Indicateur]) -> int:
    """Profondeur d'historique nécessaire pour que tous les indicateurs répondent."""
    return max((i.periodes_min for i in indicateurs), default=0)
