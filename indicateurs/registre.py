"""
Registre des indicateurs disponibles.

C'est le point d'entrée unique pour la sélection : l'interface n'a besoin que de
`catalogue()` pour afficher la liste des cases à cocher, et de `creer()` pour
instancier la sélection de l'utilisateur.

Ajouter un indicateur = écrire sa classe dans le module de sa catégorie, puis
l'ajouter à la liste de son APPROCHE ci-dessous. Rien d'autre à toucher.

Deux approches cohabitent (cf. `base.Approche`) :

  - SUIVEUSE     : les 20 indicateurs d'origine, transformations lissées du prix
                   passé. C'est la sélection par défaut, celle du tableau de bord
                   historique ;
  - ANTICIPATION : 7 indicateurs construits pour ne PAS être une fonction
                   monotone du rendement récent (cf. `anticipation.py`).

Elles ne se mélangent pas dans un score : moyenner un Supertrend (qui dit « ça
monte ») avec un retour à la moyenne (qui dit « ça monte trop ») produirait un
zéro permanent, pas une synthèse. L'interface propose donc un interrupteur, pas
des cases à cocher communes.
"""

from __future__ import annotations

import pandas as pd

from .anticipation import (
    Asymetrie,
    Compression,
    Divergences,
    Efficience,
    Epuisement,
    Essoufflement,
    RetourMoyenne,
)
from .base import Approche, Categorie, Indicateur
from .momentum import Cci, RocMultiHorizons, Rsi, Stochastique, WilliamsR
from .tendance import Adx, Aroon, Ichimoku, Macd, MoyennesMobiles, ParabolicSar, Supertrend
from .volatilite import AtrIndicateur, Bollinger, Donchian, Keltner
from .volume import ChaikinMoneyFlow, MoneyFlowIndex, Obv, VolumeRelatif

# Les 20 indicateurs suiveurs, ordonnés par catégorie.
CLASSES_SUIVEUSES: list[type[Indicateur]] = [
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

# Les 7 indicateurs d'anticipation, même ordre de lecture.
CLASSES_ANTICIPATION: list[type[Indicateur]] = [
    # --- Tendance (1, contextuel) ---
    Efficience,
    # --- Momentum (3) ---
    RetourMoyenne,
    Essoufflement,
    Divergences,
    # --- Volatilité (2, dont 1 contextuel) ---
    Asymetrie,
    Compression,
    # --- Volume (1) ---
    Epuisement,
]

CLASSES: list[type[Indicateur]] = CLASSES_SUIVEUSES + CLASSES_ANTICIPATION

# Index code -> classe, construit automatiquement pour éviter toute désynchronisation.
REGISTRE: dict[str, type[Indicateur]] = {classe.code: classe for classe in CLASSES}

CLASSES_PAR_APPROCHE: dict[Approche, list[type[Indicateur]]] = {
    Approche.SUIVEUSE: CLASSES_SUIVEUSES,
    Approche.ANTICIPATION: CLASSES_ANTICIPATION,
}

APPROCHE_DEFAUT = Approche.SUIVEUSE

# Sélection par défaut : les suiveurs, et eux seuls. Mélanger les deux approches
# dans une même moyenne les ferait s'annuler (voir l'en-tête du module).
CODES_PAR_DEFAUT: list[str] = [classe.code for classe in CLASSES_SUIVEUSES]


def codes_par_approche(approche: Approche | str) -> list[str]:
    """Codes d'une approche donnée, dans l'ordre de lecture du registre."""
    valeur = approche.value if isinstance(approche, Approche) else approche
    return [c.code for c in CLASSES if c.approche.value == valeur]


def approche_de(codes: list[str] | None) -> Approche:
    """
    Approche d'une sélection de codes.

    Une sélection panachée est possible (rien ne l'interdit en Python), mais
    l'approche majoritaire est la seule réponse utile pour un libellé d'écran.
    """
    if not codes:
        return APPROCHE_DEFAUT
    compte = {approche: 0 for approche in Approche}
    for code in codes:
        classe = REGISTRE.get(code)
        if classe is not None:
            compte[classe.approche] += 1
    return max(compte, key=compte.get)


def creer(codes: list[str] | None = None, reglages: dict | None = None) -> list[Indicateur]:
    """
    Instancie les indicateurs demandés.

    codes    : liste de codes (ex. ["BOLLINGER", "RSI"]). None = la sélection
               par défaut, c'est-à-dire l'approche suiveuse. Pour l'autre
               approche, passer `codes_par_approche(Approche.ANTICIPATION)`.
    reglages : surcharges de paramètres par code,
               ex. {"RSI": {"periode": 21}, "BOLLINGER": {"ecarts": 2.5}}

    Un code inconnu lève une ValueError explicite : mieux vaut échouer tout de
    suite que d'analyser silencieusement avec un indicateur manquant.
    """
    codes = list(CODES_PAR_DEFAUT) if codes is None else list(codes)
    reglages = reglages or {}

    inconnus = [c for c in codes if c not in REGISTRE]
    if inconnus:
        raise ValueError(
            f"Indicateur(s) inconnu(s) : {inconnus}. Codes disponibles : {sorted(REGISTRE)}"
        )
    return [REGISTRE[code](**reglages.get(code, {})) for code in codes]


def codes_par_categorie(categorie: Categorie | str,
                        approche: Approche | str | None = None) -> list[str]:
    """
    Codes d'une famille donnée (pratique pour les onglets de l'UI).

    `approche` restreint en plus à une approche : c'est ce dont l'interface a
    besoin, puisqu'elle n'affiche jamais les deux ensembles à la fois.
    """
    valeur = categorie.value if isinstance(categorie, Categorie) else categorie
    classes = CLASSES if approche is None else CLASSES_PAR_APPROCHE[
        approche if isinstance(approche, Approche) else Approche(approche)
    ]
    return [c.code for c in classes if c.categorie.value == valeur]


def catalogue(approche: Approche | str | None = None) -> pd.DataFrame:
    """
    Tableau descriptif des indicateurs disponibles.
    Alimente directement la liste de sélection de l'interface.
    """
    classes = CLASSES if approche is None else CLASSES_PAR_APPROCHE[
        approche if isinstance(approche, Approche) else Approche(approche)
    ]
    lignes = [classe().fiche() for classe in classes]
    tableau = pd.DataFrame(lignes)
    return tableau[["code", "nom", "categorie", "approche", "description", "periodes_min"]]


def periodes_requises(indicateurs: list[Indicateur]) -> int:
    """Profondeur d'historique nécessaire pour que tous les indicateurs répondent."""
    return max((i.periodes_min for i in indicateurs), default=0)
