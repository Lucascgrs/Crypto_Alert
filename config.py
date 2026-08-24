"""
Paramètres globaux du tableau de bord crypto.

Tout ce qui se règle sans toucher au code métier est centralisé ici :
source des prix, profondeur d'historique, seuils de qualification des scores.
"""

import math

# ---------------------------------------------------------------------------
# Données de marché
# ---------------------------------------------------------------------------
NB_CRYPTOS_DEFAUT = 20        # taille du Top capitalisation analysé
INTERVALLE_DEFAUT = "1d"      # bougie de travail : 1d, 4h, 1h...
NB_BOUGIES_DEFAUT = 400       # profondeur d'historique (>= 250 pour la SMA 200)
DEVISE = "usd"

# Stablecoins et actifs indexés : l'analyse technique n'a aucun sens sur un actif
# dont le cours est arrimé au dollar, on les écarte du classement.
#
# Deux filets successifs, car de nouveaux stablecoins entrent régulièrement dans
# le Top 50 et une liste figée se périme vite :
#   1. cette liste explicite, pour les cas qui ne suivent aucune convention ;
#   2. le motif MOTIF_STABLECOIN ci-dessous, qui rattrape automatiquement tous
#      les symboles construits autour de « USD » (USDG, RLUSD, USD1...).
STABLECOINS = {
    "USDT", "USDC", "DAI", "BUSD", "TUSD", "FDUSD", "USDE", "PYUSD",
    "USDS", "USD1", "USDD", "GUSD", "LUSD", "FRAX", "USDG", "RLUSD",
    "EURC", "EURS", "STETH", "WSTETH", "WBETH", "WEETH",  # actifs indexés / dérivés stakés
}

# Tout symbole contenant « USD » entouré de lettres ou de chiffres : la
# convention est suffisamment constante pour que le risque de faux positif soit
# négligeable, et l'oubli d'un stablecoin bien plus gênant.
MOTIF_STABLECOIN = r"^[A-Z0-9]{0,3}USD[A-Z0-9]{0,3}$"

# ---------------------------------------------------------------------------
# Réseau
# ---------------------------------------------------------------------------
URL_COINGECKO = "https://api.coingecko.com/api/v3/coins/markets"
URL_BINANCE = "https://api.binance.com/api/v3/klines"
ENTETES_HTTP = {"User-Agent": "CryptoDashboard/1.0"}
TIMEOUT_REQUETE = 20          # secondes
DELAI_ENTRE_REQUETES = 0.25   # anti rate-limit entre deux appels

# Durée d'une bougie, en minutes. Sert au cache, au calcul des horizons de
# vérification et à la conversion des intervalles un peu partout.
MINUTES_PAR_INTERVALLE = {
    "1m": 1, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "4h": 240, "1d": 1440,
}

# ---------------------------------------------------------------------------
# Cache disque (évite de re-télécharger à chaque exécution pendant le dev)
# ---------------------------------------------------------------------------
DOSSIER_CACHE = "cache"
DUREE_CACHE_MINUTES = 15   # plafond ; le cache ne dépasse jamais une bougie

# ---------------------------------------------------------------------------
# Suivi des performances (backtest)
# ---------------------------------------------------------------------------
FICHIER_SUIVI = "suivi_scores.xlsx"

# Un score est évalué N bougies plus tard : un score journalier se juge sur
# quelques jours, un score en 5 minutes sur une demi-heure. Exprimer l'horizon
# en bougies le rend cohérent quel que soit l'intervalle choisi.
HORIZON_BOUGIES = 6

# Au-delà du score, un relevé n'est « prédictif » que si le score dépasse ce
# seuil : en dessous, l'application ne dit rien de tranché et il serait injuste
# de compter le résultat comme une erreur.
SEUIL_PREDICTION = 0.15

# Un mouvement inférieur à ce seuil est considéré comme du bruit : ni hausse,
# ni baisse. Évite de compter comme « correct » un +0,02 % dû au spread.
SEUIL_MOUVEMENT = 0.005

# Passé ce multiple de l'horizon sans avoir pu être vérifié (historique trop
# court pour remonter jusqu'à l'échéance), un relevé est abandonné.
FACTEUR_EXPIRATION = 10

# ---------------------------------------------------------------------------
# Qualification des scores
# ---------------------------------------------------------------------------
# Un score est toujours ramené dans [-1, 1]. On le traduit en libellé lisible
# via ces paliers : le premier dont la borne dépasse le score est retenu.
SEUILS_SYNTHESE = [
    (-0.50, "Fortement négatif"),
    (-0.15, "Négatif"),
    (0.15, "Neutre"),
    (0.50, "Positif"),
    (math.inf, "Fortement positif"),
]
