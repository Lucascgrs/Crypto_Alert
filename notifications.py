"""
Alertes Discord.

Même principe que `PokemonScraper/pokescraper/core/notifier.py` : on passe par un
**webhook** Discord, la solution la plus simple à configurer.

ATTENTION : un webhook n'est PAS un lien d'invitation (`discord.gg/xxx`). C'est une
URL de la forme `https://discord.com/api/webhooks/<id>/<token>`, qu'on obtient dans
Discord : Paramètres du salon → Intégrations → Webhooks → Nouveau webhook →
Copier l'URL. On la colle dans la fenêtre de configuration, rien d'autre à faire.

Ce module contient trois choses :
  1. la validation et l'envoi d'un message ;
  2. la construction du message d'alerte à partir des résultats d'analyse ;
  3. la persistance des réglages (fichier JSON, jamais versionné).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime

import requests

import presentation as pr

# Fichier de réglages. Il contient l'URL du webhook (un secret) : il est donc
# listé dans .gitignore, comme gui_config.json côté PokemonScraper.
FICHIER_CONFIG = "config_alertes.json"

CONFIG_DEFAUT = {
    "webhook": "",
    "actif": False,           # les alertes sont-elles autorisées ?
    "auto": False,            # envoi périodique automatique
    "intervalle": 30,
    "unite": "minutes",       # "minutes" ou "heures"
    # --- Contenu de l'alerte ---
    "nb_cryptos": 5,          # combien de cryptos au maximum dans le message
    "score_min": 0.30,        # seuil sur la VALEUR ABSOLUE du score
    "sens": "tous",           # "haussier", "baissier" ou "tous"
    "inclure_categories": True,   # scores par famille d'indicateurs
    "inclure_criteres": True,     # les critères les plus marquants
    "nb_criteres": 4,
    "mention": "",            # ex. "@here" ou "<@&123456789>"
    "silencieux_si_vide": True,   # ne rien envoyer si aucune crypto ne passe le filtre
}

UNITES_EN_MINUTES = {"minutes": 1, "heures": 60}

# Un vrai webhook : discord.com / discordapp.com / (ptb|canary).discord.com
_RE_WEBHOOK = re.compile(
    r"^https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/api/(?:v\d+/)?webhooks/\d+/[\w-]+/?$",
    re.I,
)

# Couleurs Discord (entiers) alignées sur la charte des interfaces.
_COULEURS_DISCORD = {
    "Fortement positif": 0x157F3D,
    "Positif": 0x2E8B57,
    "Neutre": 0x6B7280,
    "Négatif": 0xD1495B,
    "Fortement négatif": 0x9B1C2E,
}


# ===========================================================================
# 1. VALIDATION ET ENVOI
# ===========================================================================
def valider_webhook(url: str) -> tuple[bool, str]:
    """
    Vérifie qu'une URL est bien un webhook Discord (et pas une invitation).
    Renvoie (ok, message) — le message explique l'échec, affichable tel quel.
    """
    url = (url or "").strip()
    if not url:
        return False, "URL vide."
    if "discord.gg" in url or "/invite/" in url:
        return False, (
            "Ceci est un lien d'INVITATION (discord.gg), pas un webhook. "
            "Dans Discord : Paramètres du salon → Intégrations → Webhooks → "
            "Nouveau webhook → Copier l'URL (elle contient /api/webhooks/)."
        )
    if not _RE_WEBHOOK.match(url):
        return False, (
            "Format inattendu. Un webhook ressemble à : "
            "https://discord.com/api/webhooks/<id>/<token>"
        )
    return True, "OK"


def envoyer_discord(webhook: str, contenu: str = "", embeds: list | None = None) -> tuple[bool, str]:
    """
    Poste un message via un webhook Discord.

    Renvoie (succès, détail). Le succès n'est vrai que si Discord accepte (200/204) ;
    le détail explique précisément l'échec, pour être affiché dans l'interface.
    """
    ok, raison = valider_webhook(webhook)
    if not ok:
        return False, raison

    charge = {}
    if contenu:
        charge["content"] = contenu[:1900]  # limite Discord : 2000 caractères
    if embeds:
        charge["embeds"] = embeds[:10]      # limite Discord : 10 embeds
    if not charge:
        return False, "Message vide."

    try:
        reponse = requests.post(webhook.strip(), json=charge, timeout=15)
    except requests.RequestException as e:
        return False, f"Erreur réseau : {e}"

    if reponse.status_code in (200, 204):
        return True, "Message envoyé."
    if reponse.status_code == 404:
        return False, "Webhook introuvable (404) — supprimé, ou URL incorrecte."
    if reponse.status_code == 401:
        return False, "Token invalide (401) — recopiez l'URL complète du webhook."
    if reponse.status_code == 429:
        return False, "Trop de requêtes (429) — Discord limite, réessayez dans un instant."
    return False, f"Discord a refusé (HTTP {reponse.status_code}) : {(reponse.text or '')[:120]}"


def tester_webhook(webhook: str) -> tuple[bool, str]:
    """Envoie un message de test, pour valider la configuration d'un coup d'œil."""
    return envoyer_discord(
        webhook,
        contenu="✅ **CryptoDashboard** — webhook configuré correctement.",
    )


# ===========================================================================
# 2. CONSTRUCTION DU MESSAGE
# ===========================================================================
def filtrer_resultats(resultats, config: dict) -> list:
    """
    Applique les filtres de la configuration et renvoie les cryptos à signaler,
    triées par score décroissant en valeur absolue (les plus marquantes d'abord).
    """
    seuil = float(config.get("score_min", 0))
    sens = config.get("sens", "tous")

    retenues = []
    for resultat in resultats:
        if not resultat.indicateurs_notes:
            continue
        score = resultat.score_global
        if abs(score) < seuil:
            continue
        if sens == "haussier" and score <= 0:
            continue
        if sens == "baissier" and score >= 0:
            continue
        retenues.append(resultat)

    retenues.sort(key=lambda r: -abs(r.score_global))
    return retenues[: int(config.get("nb_cryptos", 5))]


def _criteres_marquants(resultat, combien: int) -> list:
    """
    Les critères qui EXPLIQUENT l'alerte : les plus tranchés, dans le sens
    dominant du score.

    La sélection se fait indicateur par indicateur, à tour de rôle : quatre
    critères issus de quatre indicateurs différents sont bien plus informatifs
    que les quatre critères d'un même indicateur, qui répètent la même idée.
    """
    sens = 1 if resultat.score_global >= 0 else -1

    # Pour chaque indicateur, ses critères allant dans le sens dominant,
    # du plus tranché au moins tranché.
    par_indicateur = []
    for indicateur in resultat.indicateurs_notes:
        retenus = [
            c for c in indicateur.criteres
            if c.directionnel and c.signal.value * sens > 0
        ]
        if retenus:
            retenus.sort(key=lambda c: -abs(c.signal.value))
            par_indicateur.append(retenus)

    # Les indicateurs les plus tranchés passent en premier.
    par_indicateur.sort(key=lambda liste: -abs(liste[0].signal.value))

    # Puis on pioche un critère par indicateur, tour après tour.
    marquants = []
    rang = 0
    while len(marquants) < combien and any(len(l) > rang for l in par_indicateur):
        for liste in par_indicateur:
            if rang < len(liste):
                marquants.append(liste[rang])
                if len(marquants) == combien:
                    return marquants
        rang += 1
    return marquants


def construire_embeds(resultats, config: dict) -> list[dict]:
    """
    Construit les embeds Discord : un par crypto, coloré selon sa synthèse.
    Les embeds rendent l'alerte bien plus lisible qu'un simple bloc de texte.
    """
    embeds = []
    for resultat in resultats:
        lignes = [
            f"**Score technique : {pr.formater_score(resultat.score_global)}** "
            f"— {resultat.synthese}",
            f"Prix : {pr.formater_prix(resultat.prix)}  ·  "
            f"24 h : {pr.formater_variation(resultat.variation_24h)}",
        ]

        if config.get("inclure_categories", True):
            from indicateurs import Categorie

            morceaux = []
            for categorie in Categorie:
                score = resultat.score_categorie(categorie)
                if score is not None:
                    morceaux.append(f"{categorie.value} {pr.formater_score(score)}")
            if morceaux:
                lignes.append("`" + "  ·  ".join(morceaux) + "`")

        if config.get("inclure_criteres", True):
            marquants = _criteres_marquants(resultat, int(config.get("nb_criteres", 4)))
            if marquants:
                lignes.append("")
                lignes += [f"{c.signal.symbole} {c.libelle} : {c.valeur}" for c in marquants]

        compte = resultat.compter_signaux()
        embeds.append(
            {
                "title": f"{resultat.symbole} — {resultat.nom or resultat.symbole}",
                "description": "\n".join(lignes)[:4000],
                "color": _COULEURS_DISCORD.get(resultat.synthese, 0x6B7280),
                "footer": {
                    "text": f"{compte['positifs']} critères positifs · "
                            f"{compte['negatifs']} négatifs · "
                            f"{len(resultat.indicateurs_notes)} indicateurs"
                },
            }
        )
    return embeds


def construire_entete(resultats, config: dict, intervalle: str = "") -> str:
    """Ligne d'introduction du message, avec la mention éventuelle."""
    mention = (config.get("mention") or "").strip()
    horodatage = datetime.now().strftime("%d/%m/%Y à %H:%M")
    contexte = f" ({intervalle})" if intervalle else ""
    entete = (
        f"📊 **Alerte CryptoDashboard**{contexte} — {horodatage}\n"
        f"{len(resultats)} crypto(s) au-dessus du seuil de "
        f"{config.get('score_min', 0):.2f}."
    )
    return f"{mention} {entete}" if mention else entete


def envoyer_alerte(resultats, config: dict, intervalle: str = "") -> tuple[bool, str]:
    """
    Filtre les résultats puis envoie l'alerte. Point d'entrée unique des deux
    interfaces, pour que l'envoi manuel et l'envoi automatique soient identiques.
    """
    if not config.get("webhook"):
        return False, "Aucun webhook configuré."

    retenues = filtrer_resultats(resultats, config)
    if not retenues:
        if config.get("silencieux_si_vide", True):
            return True, "Aucune crypto au-dessus du seuil : rien envoyé."
        return envoyer_discord(
            config["webhook"],
            contenu=f"📊 **CryptoDashboard** — aucune crypto au-dessus du seuil de "
                    f"{config.get('score_min', 0):.2f}.",
        )

    ok, detail = envoyer_discord(
        config["webhook"],
        contenu=construire_entete(retenues, config, intervalle),
        embeds=construire_embeds(retenues, config),
    )
    if ok:
        return True, f"{len(retenues)} crypto(s) envoyée(s) sur Discord."
    return False, detail


# ===========================================================================
# 3. PERSISTANCE DES RÉGLAGES
# ===========================================================================
def charger_config(chemin: str = FICHIER_CONFIG) -> dict:
    """Lit les réglages, en complétant les clés absentes par les valeurs par défaut."""
    config = dict(CONFIG_DEFAUT)
    if os.path.exists(chemin):
        try:
            with open(chemin, encoding="utf-8") as fichier:
                config.update(json.load(fichier))
        except (OSError, json.JSONDecodeError):
            pass  # fichier illisible ou corrompu : on repart des valeurs par défaut
    return config


def enregistrer_config(config: dict, chemin: str = FICHIER_CONFIG) -> tuple[bool, str]:
    """Écrit les réglages sur disque."""
    try:
        with open(chemin, "w", encoding="utf-8") as fichier:
            json.dump(config, fichier, indent=2, ensure_ascii=False)
        return True, f"Réglages enregistrés dans {chemin}."
    except OSError as e:
        return False, f"Écriture impossible : {e}"


def intervalle_en_ms(config: dict) -> int:
    """Intervalle d'envoi automatique converti en millisecondes (minimum 1 minute)."""
    try:
        valeur = float(config.get("intervalle", 30))
    except (TypeError, ValueError):
        valeur = 30
    minutes = valeur * UNITES_EN_MINUTES.get(config.get("unite", "minutes"), 1)
    return max(int(minutes * 60_000), 60_000)
