"""
Paquet des indicateurs techniques.

Organisation :
  base.py         -> contrat commun (Signal, Critere, Indicateur) et outils de
                     traduction nombre -> critère qualitatif
  outils.py       -> fonctions numériques partagées (moyennes, ATR, rangs...)
  tendance.py     -> 7 indicateurs de tendance
  momentum.py     -> 5 indicateurs de momentum
  volatilite.py   -> 4 indicateurs de volatilité
  volume.py       -> 4 indicateurs de volume
  anticipation.py -> 7 indicateurs de l'approche « anticipation »
  registre.py     -> catalogue et instanciation de la sélection
"""

from .base import (
    Approche,
    Categorie,
    Critere,
    Indicateur,
    ResultatIndicateur,
    Signal,
    qualifier_score,
)
from .registre import (
    APPROCHE_DEFAUT,
    CODES_PAR_DEFAUT,
    REGISTRE,
    approche_de,
    catalogue,
    codes_par_approche,
    codes_par_categorie,
    creer,
    periodes_requises,
)

__all__ = [
    "Approche",
    "Categorie",
    "Critere",
    "Indicateur",
    "ResultatIndicateur",
    "Signal",
    "qualifier_score",
    "REGISTRE",
    "CODES_PAR_DEFAUT",
    "APPROCHE_DEFAUT",
    "approche_de",
    "catalogue",
    "codes_par_approche",
    "codes_par_categorie",
    "creer",
    "periodes_requises",
]
