"""
Récupération des données de marché.

Deux besoins seulement :
  1. le classement des N cryptos les plus capitalisées  -> CoinGecko ;
  2. l'historique OHLCV de chacune                      -> Binance (repli Yahoo).

Reprend l'approche de Crypto/GatherData.py en la simplifiant : ici on n'a
besoin que des dernières centaines de bougies, donc pas de pagination.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta

import pandas as pd
import requests

import config

COLONNES_OHLCV = ["Open", "High", "Low", "Close", "Volume"]


class SourceDonnees:
    """
    Accès aux données de marché, avec cache disque optionnel.

    Le cache évite de re-télécharger 20 historiques à chaque exécution pendant
    le développement de l'interface (et de se faire limiter par les API).
    """

    def __init__(self, utiliser_cache: bool = True, dossier_cache: str | None = None,
                 duree_cache_minutes: int | None = None, verbeux: bool = True):
        self.utiliser_cache = utiliser_cache
        self.dossier_cache = dossier_cache or config.DOSSIER_CACHE
        self.duree_cache = timedelta(
            minutes=duree_cache_minutes
            if duree_cache_minutes is not None
            else config.DUREE_CACHE_MINUTES
        )
        self.verbeux = verbeux

        if self.utiliser_cache:
            os.makedirs(self.dossier_cache, exist_ok=True)

    # -- Journalisation -----------------------------------------------------
    def _log(self, message: str):
        if self.verbeux:
            print(message)

    # -- Cache --------------------------------------------------------------
    def _chemin_cache(self, cle: str) -> str:
        return os.path.join(self.dossier_cache, f"{cle}.csv")

    def _lire_cache(self, cle: str, index_dates: bool = False,
                    duree: timedelta | None = None) -> pd.DataFrame | None:
        """
        Renvoie le contenu du cache s'il existe et n'est pas périmé.

        `index_dates` distingue les deux formes de cache : l'historique OHLCV est
        indexé par date, le classement par symbole. Sans cette distinction,
        pandas tente de deviner et émet un avertissement à chaque lecture.
        """
        if not self.utiliser_cache:
            return None
        chemin = self._chemin_cache(cle)
        if not os.path.exists(chemin):
            return None
        age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(chemin))
        if age > (duree if duree is not None else self.duree_cache):
            return None
        try:
            df = pd.read_csv(chemin, index_col=0)
            if index_dates:
                # Le cache est toujours écrit par to_csv, donc au format ISO.
                df.index = pd.to_datetime(df.index, format="ISO8601")
                df.index.name = "Date"
            return df
        except Exception:
            return None  # cache corrompu : on retélécharge, sans faire de bruit

    def _ecrire_cache(self, cle: str, df: pd.DataFrame):
        if self.utiliser_cache and df is not None and not df.empty:
            try:
                df.to_csv(self._chemin_cache(cle))
            except Exception as e:
                self._log(f"   Cache non écrit ({cle}) : {e}")

    # -- 1. Classement par capitalisation -----------------------------------
    def top_cryptos(self, n: int = config.NB_CRYPTOS_DEFAUT,
                    exclure_stablecoins: bool = True) -> pd.DataFrame:
        """
        Top N des cryptos par capitalisation via CoinGecko.

        Renvoie un DataFrame indexé par symbole avec : rang, nom, prix,
        capitalisation, volume 24 h et variation 24 h.
        """
        cle = f"top_{n}_{int(exclure_stablecoins)}"
        cache = self._lire_cache(cle)
        if cache is not None:
            self._log(f"Top {n} : lu depuis le cache.")
            return cache

        # Marge de sécurité : on demande plus large pour compenser les
        # stablecoins qui seront retirés du classement.
        marge = 15 if exclure_stablecoins else 0
        parametres = {
            "vs_currency": config.DEVISE,
            "order": "market_cap_desc",
            "per_page": min(n + marge, 250),
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "24h",
        }

        self._log(f"CoinGecko : récupération du Top {n} par capitalisation...")
        reponse = requests.get(
            config.URL_COINGECKO,
            params=parametres,
            headers=config.ENTETES_HTTP,
            timeout=config.TIMEOUT_REQUETE,
        )
        if reponse.status_code == 429:  # limite de débit : une pause suffit
            self._log("   Limite de débit atteinte, pause de 10 s...")
            time.sleep(10)
            reponse = requests.get(
                config.URL_COINGECKO,
                params=parametres,
                headers=config.ENTETES_HTTP,
                timeout=config.TIMEOUT_REQUETE,
            )
        reponse.raise_for_status()

        df = pd.DataFrame(reponse.json())
        df = df.rename(
            columns={
                "market_cap_rank": "rang",
                "symbol": "symbole",
                "name": "nom",
                "current_price": "prix",
                "market_cap": "capitalisation",
                "total_volume": "volume_24h",
                "price_change_percentage_24h": "variation_24h",
            }
        )
        colonnes = ["rang", "symbole", "nom", "prix", "capitalisation", "volume_24h", "variation_24h"]
        df = df[[c for c in colonnes if c in df.columns]]
        df["symbole"] = df["symbole"].str.upper()

        if exclure_stablecoins:
            # Liste explicite + motif « ...USD... », cf. config.STABLECOINS.
            connus = df["symbole"].isin(config.STABLECOINS)
            motif = df["symbole"].str.match(config.MOTIF_STABLECOIN)
            df = df[~(connus | motif)]

        df = df.head(n).set_index("symbole")
        self._ecrire_cache(cle, df)
        self._log(f"   {len(df)} cryptos retenues.")
        return df

    # -- 2. Historique OHLCV ------------------------------------------------
    def historique(self, symbole: str, intervalle: str = config.INTERVALLE_DEFAUT,
                   nb_bougies: int = config.NB_BOUGIES_DEFAUT) -> pd.DataFrame | None:
        """
        Historique OHLCV d'une crypto, indexé par date croissante.
        Essaie Binance puis Yahoo Finance. Renvoie None si aucune source ne répond.
        """
        cle = f"ohlcv_{symbole}_{intervalle}_{nb_bougies}"
        # Le cache ne doit jamais survivre à la bougie en cours : conserver
        # 15 minutes des chandeliers d'une minute donnerait des prix périmés.
        duree = min(
            self.duree_cache,
            timedelta(minutes=config.MINUTES_PAR_INTERVALLE.get(intervalle, 15)),
        )
        cache = self._lire_cache(cle, index_dates=True, duree=duree)
        if cache is not None:
            return cache

        df = self._binance(symbole, intervalle, nb_bougies)
        if df is None:
            df = self._yahoo(symbole, intervalle, nb_bougies)

        if df is not None and not df.empty:
            self._ecrire_cache(cle, df)
        time.sleep(config.DELAI_ENTRE_REQUETES)
        return df

    def _binance(self, symbole: str, intervalle: str, nb_bougies: int) -> pd.DataFrame | None:
        """Chandeliers Binance. La limite de 1000 bougies par appel nous suffit."""
        parametres = {
            "symbol": f"{symbole}USDT",
            "interval": intervalle,
            "limit": min(nb_bougies, 1000),
        }
        try:
            reponse = requests.get(
                config.URL_BINANCE, params=parametres, timeout=config.TIMEOUT_REQUETE
            )
            if reponse.status_code != 200:  # paire inexistante le plus souvent
                return None
            bougies = reponse.json()
            if not bougies:
                return None
        except requests.RequestException as e:
            self._log(f"   {symbole} : Binance injoignable ({e})")
            return None

        df = pd.DataFrame(
            bougies,
            columns=[
                "ouverture", "Open", "High", "Low", "Close", "Volume",
                "fermeture", "volume_quote", "trades",
                "achat_base", "achat_quote", "ignore",
            ],
        )
        df["Date"] = pd.to_datetime(df["ouverture"], unit="ms")
        df = df.set_index("Date")[COLONNES_OHLCV].astype(float)
        return df.sort_index()

    def _yahoo(self, symbole: str, intervalle: str, nb_bougies: int) -> pd.DataFrame | None:
        """
        Repli Yahoo Finance pour les actifs sans paire USDT sur Binance.
        yfinance est optionnel : son absence dégrade proprement.
        """
        try:
            import logging

            import yfinance as yf

            # yfinance journalise ses échecs sur stderr ; ici un échec est un cas
            # normal (le jeton n'existe pas chez Yahoo non plus), on le gère nous-mêmes.
            logging.getLogger("yfinance").setLevel(logging.CRITICAL)
        except ImportError:
            return None

        # Yahoo raisonne en durée, pas en nombre de bougies.
        jours_par_bougie = {"1d": 1, "4h": 1 / 6, "1h": 1 / 24}.get(intervalle, 1)
        periode_jours = int(nb_bougies * jours_par_bougie) + 10

        try:
            df = yf.download(
                f"{symbole}-USD",
                period=f"{min(periode_jours, 3650)}d",
                interval=intervalle,
                progress=False,
                auto_adjust=True,
            )
        except Exception as e:
            self._log(f"   {symbole} : Yahoo injoignable ({e})")
            return None

        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if not set(COLONNES_OHLCV).issubset(df.columns):
            return None

        df = df[COLONNES_OHLCV].dropna()
        if getattr(df.index, "tz", None) is not None:
            df.index = df.index.tz_localize(None)
        df.index.name = "Date"
        return df.sort_index().tail(nb_bougies)
