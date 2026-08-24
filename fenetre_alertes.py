"""
Fenêtre de configuration des alertes Discord.

Ouverte depuis l'interface de bureau (bouton « Alertes Discord »). Elle règle :
  - le webhook et son test ;
  - l'activation et la périodicité de l'envoi automatique ;
  - le CONTENU de l'alerte : combien de cryptos, à partir de quel score, dans
    quel sens, avec ou sans le détail des critères.

La fenêtre ne fait qu'éditer un dictionnaire de réglages ; c'est l'application
principale qui déclenche les envois, elle seule connaissant les résultats
d'analyse en cours.
"""

from __future__ import annotations

import threading
import tkinter as tk

import customtkinter as ctk

import notifications as notif

POLICE_TITRE = ("Segoe UI", 15, "bold")
POLICE_NORMALE = ("Segoe UI", 12)
POLICE_PETITE = ("Segoe UI", 11)


class FenetreAlertes(ctk.CTkToplevel):
    """
    Fenêtre modale de réglage des alertes.

    `au_changement` est rappelée après enregistrement, pour que l'application
    principale reprogramme (ou arrête) sa boucle d'envoi automatique.
    `envoyer_maintenant` déclenche un envoi immédiat depuis l'application.
    """

    def __init__(self, parent, config: dict, au_changement=None, envoyer_maintenant=None):
        super().__init__(parent)
        self.title("Alertes Discord")
        self.geometry("620x760")
        self.resizable(False, True)

        self.config_alertes = dict(config)
        self.au_changement = au_changement
        self.envoyer_maintenant = envoyer_maintenant

        # La fenêtre reste au-dessus de la principale et capte les clics.
        self.transient(parent)
        self.after(200, self.grab_set)

        self._construire()

    # =====================================================================
    # CONSTRUCTION
    # =====================================================================
    def _construire(self):
        zone = ctk.CTkScrollableFrame(self, fg_color="transparent")
        zone.pack(fill="both", expand=True, padx=14, pady=(14, 0))

        self._section_webhook(zone)
        self._section_automatique(zone)
        self._section_contenu(zone)

        # Barre d'actions, hors de la zone défilante pour rester toujours visible.
        barre = ctk.CTkFrame(self, fg_color="transparent")
        barre.pack(fill="x", padx=14, pady=12)

        self.etiquette_etat = ctk.CTkLabel(
            barre, text="", font=POLICE_PETITE, text_color="#9aa0a6", anchor="w"
        )
        self.etiquette_etat.pack(fill="x", pady=(0, 8))

        ctk.CTkButton(
            barre, text="Envoyer maintenant", height=34, command=self._envoyer_maintenant
        ).pack(side="left", expand=True, fill="x", padx=(0, 4))
        ctk.CTkButton(
            barre, text="Enregistrer", height=34, command=self._enregistrer
        ).pack(side="left", expand=True, fill="x", padx=4)
        ctk.CTkButton(
            barre, text="Fermer", height=34, fg_color="#555b66", hover_color="#6b7280",
            command=self._fermer,
        ).pack(side="left", expand=True, fill="x", padx=(4, 0))

    def _titre_section(self, parent, texte: str):
        ctk.CTkLabel(parent, text=texte, font=POLICE_TITRE, anchor="w").pack(
            fill="x", pady=(14, 6)
        )

    def _section_webhook(self, parent):
        self._titre_section(parent, "1. Webhook Discord")

        cadre = ctk.CTkFrame(parent)
        cadre.pack(fill="x")

        ctk.CTkLabel(
            cadre,
            text="Discord → Paramètres du salon → Intégrations → Webhooks →\n"
                 "Nouveau webhook → Copier l'URL (elle contient /api/webhooks/).",
            font=POLICE_PETITE, text_color="#9aa0a6", justify="left", anchor="w",
        ).pack(fill="x", padx=10, pady=(10, 6))

        self.champ_webhook = ctk.CTkEntry(
            cadre, placeholder_text="https://discord.com/api/webhooks/...",
            font=POLICE_PETITE, height=32,
        )
        self.champ_webhook.insert(0, self.config_alertes.get("webhook", ""))
        self.champ_webhook.pack(fill="x", padx=10, pady=(0, 8))

        ligne = ctk.CTkFrame(cadre, fg_color="transparent")
        ligne.pack(fill="x", padx=10, pady=(0, 10))

        self.var_actif = tk.BooleanVar(value=self.config_alertes.get("actif", False))
        ctk.CTkCheckBox(
            ligne, text="Alertes activées", variable=self.var_actif, font=POLICE_NORMALE
        ).pack(side="left")
        ctk.CTkButton(
            ligne, text="Tester le webhook", width=150, height=28,
            font=POLICE_PETITE, command=self._tester,
        ).pack(side="right")

    def _section_automatique(self, parent):
        self._titre_section(parent, "2. Envoi automatique")

        cadre = ctk.CTkFrame(parent)
        cadre.pack(fill="x")

        ligne = ctk.CTkFrame(cadre, fg_color="transparent")
        ligne.pack(fill="x", padx=10, pady=10)

        self.var_auto = tk.BooleanVar(value=self.config_alertes.get("auto", False))
        ctk.CTkCheckBox(
            ligne, text="Relancer l'analyse et envoyer toutes les",
            variable=self.var_auto, font=POLICE_NORMALE,
        ).pack(side="left")

        self.champ_intervalle = ctk.CTkEntry(ligne, width=60, font=POLICE_NORMALE)
        self.champ_intervalle.insert(0, str(self.config_alertes.get("intervalle", 30)))
        self.champ_intervalle.pack(side="left", padx=6)

        self.menu_unite = ctk.CTkOptionMenu(
            ligne, width=110, values=list(notif.UNITES_EN_MINUTES), font=POLICE_NORMALE
        )
        self.menu_unite.set(self.config_alertes.get("unite", "minutes"))
        self.menu_unite.pack(side="left")

        ctk.CTkLabel(
            cadre,
            text="L'analyse complète est relancée à chaque envoi : les données sont "
                 "donc toujours fraîches.\nMinimum 1 minute, pour ménager les API.",
            font=POLICE_PETITE, text_color="#9aa0a6", justify="left", anchor="w",
        ).pack(fill="x", padx=10, pady=(0, 10))

    def _section_contenu(self, parent):
        self._titre_section(parent, "3. Contenu de l'alerte")

        cadre = ctk.CTkFrame(parent)
        cadre.pack(fill="x")

        # -- Nombre de cryptos --
        ligne = ctk.CTkFrame(cadre, fg_color="transparent")
        ligne.pack(fill="x", padx=10, pady=(12, 4))
        ctk.CTkLabel(ligne, text="Cryptos par alerte (au maximum)", font=POLICE_NORMALE).pack(
            side="left"
        )
        self.etiquette_nb = ctk.CTkLabel(ligne, text="", font=POLICE_NORMALE, width=30)
        self.etiquette_nb.pack(side="right")

        self.curseur_nb = ctk.CTkSlider(
            cadre, from_=1, to=10, number_of_steps=9,
            command=lambda v: self.etiquette_nb.configure(text=str(int(v))),
        )
        self.curseur_nb.set(self.config_alertes.get("nb_cryptos", 5))
        self.curseur_nb.pack(fill="x", padx=10)
        self.etiquette_nb.configure(text=str(int(self.curseur_nb.get())))

        # -- Seuil de score --
        ligne = ctk.CTkFrame(cadre, fg_color="transparent")
        ligne.pack(fill="x", padx=10, pady=(14, 4))
        ctk.CTkLabel(
            ligne, text="Score minimum (en valeur absolue)", font=POLICE_NORMALE
        ).pack(side="left")
        self.etiquette_seuil = ctk.CTkLabel(ligne, text="", font=POLICE_NORMALE, width=40)
        self.etiquette_seuil.pack(side="right")

        self.curseur_seuil = ctk.CTkSlider(
            cadre, from_=0, to=1, number_of_steps=20,
            command=lambda v: self.etiquette_seuil.configure(text=f"{v:.2f}"),
        )
        self.curseur_seuil.set(self.config_alertes.get("score_min", 0.30))
        self.curseur_seuil.pack(fill="x", padx=10)
        self.etiquette_seuil.configure(text=f"{self.curseur_seuil.get():.2f}")

        ctk.CTkLabel(
            cadre,
            text="0.15 = signal net · 0.50 = signal fort. Le seuil porte sur la valeur "
                 "absolue :\nune crypto très baissière déclenche autant qu'une très haussière.",
            font=POLICE_PETITE, text_color="#9aa0a6", justify="left", anchor="w",
        ).pack(fill="x", padx=10, pady=(4, 10))

        # -- Sens --
        ligne = ctk.CTkFrame(cadre, fg_color="transparent")
        ligne.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(ligne, text="Signaler les cryptos", font=POLICE_NORMALE).pack(side="left")
        self.menu_sens = ctk.CTkOptionMenu(
            ligne, width=170, font=POLICE_NORMALE,
            values=["tous", "haussier", "baissier"],
        )
        self.menu_sens.set(self.config_alertes.get("sens", "tous"))
        self.menu_sens.pack(side="right")

        # -- Détail inclus --
        self.var_categories = tk.BooleanVar(
            value=self.config_alertes.get("inclure_categories", True)
        )
        ctk.CTkCheckBox(
            cadre, text="Inclure les scores par famille (tendance, momentum...)",
            variable=self.var_categories, font=POLICE_NORMALE,
        ).pack(anchor="w", padx=10, pady=3)

        self.var_criteres = tk.BooleanVar(
            value=self.config_alertes.get("inclure_criteres", True)
        )
        ctk.CTkCheckBox(
            cadre, text="Inclure les critères les plus marquants",
            variable=self.var_criteres, font=POLICE_NORMALE,
        ).pack(anchor="w", padx=10, pady=3)

        ligne = ctk.CTkFrame(cadre, fg_color="transparent")
        ligne.pack(fill="x", padx=10, pady=(4, 4))
        ctk.CTkLabel(ligne, text="Nombre de critères par crypto", font=POLICE_NORMALE).pack(
            side="left"
        )
        self.etiquette_nb_criteres = ctk.CTkLabel(ligne, text="", font=POLICE_NORMALE, width=30)
        self.etiquette_nb_criteres.pack(side="right")

        self.curseur_criteres = ctk.CTkSlider(
            cadre, from_=1, to=10, number_of_steps=9,
            command=lambda v: self.etiquette_nb_criteres.configure(text=str(int(v))),
        )
        self.curseur_criteres.set(self.config_alertes.get("nb_criteres", 4))
        self.curseur_criteres.pack(fill="x", padx=10)
        self.etiquette_nb_criteres.configure(text=str(int(self.curseur_criteres.get())))

        # -- Mention --
        ligne = ctk.CTkFrame(cadre, fg_color="transparent")
        ligne.pack(fill="x", padx=10, pady=(14, 4))
        ctk.CTkLabel(ligne, text="Mention (facultatif)", font=POLICE_NORMALE).pack(side="left")
        self.champ_mention = ctk.CTkEntry(
            ligne, width=210, placeholder_text="@here, <@&role_id>...", font=POLICE_PETITE
        )
        self.champ_mention.insert(0, self.config_alertes.get("mention", ""))
        self.champ_mention.pack(side="right")

        self.var_silencieux = tk.BooleanVar(
            value=self.config_alertes.get("silencieux_si_vide", True)
        )
        ctk.CTkCheckBox(
            cadre, text="Ne rien envoyer si aucune crypto ne passe le seuil",
            variable=self.var_silencieux, font=POLICE_NORMALE,
        ).pack(anchor="w", padx=10, pady=(6, 12))

    # =====================================================================
    # ACTIONS
    # =====================================================================
    def lire_config(self) -> dict:
        """Reconstruit le dictionnaire de réglages à partir des champs affichés."""
        try:
            intervalle = float(self.champ_intervalle.get())
        except ValueError:
            intervalle = 30.0

        return {
            "webhook": self.champ_webhook.get().strip(),
            "actif": self.var_actif.get(),
            "auto": self.var_auto.get(),
            "intervalle": intervalle,
            "unite": self.menu_unite.get(),
            "nb_cryptos": int(self.curseur_nb.get()),
            "score_min": round(self.curseur_seuil.get(), 2),
            "sens": self.menu_sens.get(),
            "inclure_categories": self.var_categories.get(),
            "inclure_criteres": self.var_criteres.get(),
            "nb_criteres": int(self.curseur_criteres.get()),
            "mention": self.champ_mention.get().strip(),
            "silencieux_si_vide": self.var_silencieux.get(),
        }

    def _etat(self, message: str, succes: bool | None = None):
        couleurs = {True: "#2e8b57", False: "#d1495b", None: "#9aa0a6"}
        self.etiquette_etat.configure(text=message, text_color=couleurs[succes])

    def _tester(self):
        """Envoie un message de test, dans un thread pour ne pas figer la fenêtre."""
        webhook = self.champ_webhook.get().strip()
        ok, raison = notif.valider_webhook(webhook)
        if not ok:
            self._etat(raison, False)
            return

        self._etat("Envoi du message de test...")

        def travail():
            succes, detail = notif.tester_webhook(webhook)
            self.after(0, self._etat, detail, succes)

        threading.Thread(target=travail, daemon=True).start()

    def _envoyer_maintenant(self):
        """
        Délègue l'envoi à l'application principale, qui détient les résultats.
        L'envoi étant asynchrone, on lui passe une fonction de rappel plutôt que
        d'attendre une valeur de retour.
        """
        if self.envoyer_maintenant is None:
            self._etat("Envoi indisponible depuis cette fenêtre.", False)
            return
        self.config_alertes = self.lire_config()
        self._etat("Envoi en cours...")
        self.envoyer_maintenant(self.config_alertes, retour=self._retour_envoi)

    def _retour_envoi(self, message: str, succes: bool):
        """Rappelée par l'application une fois l'envoi terminé."""
        if self.winfo_exists():  # la fenêtre a pu être fermée entre-temps
            self._etat(message, succes)

    def _enregistrer(self):
        self.config_alertes = self.lire_config()
        ok, detail = notif.enregistrer_config(self.config_alertes)
        self._etat(detail, ok)
        if ok and self.au_changement:
            self.au_changement(self.config_alertes)

    def _fermer(self):
        # On enregistre systématiquement en sortant : c'est ce qu'attend
        # l'utilisateur après avoir bougé des curseurs.
        self.config_alertes = self.lire_config()
        notif.enregistrer_config(self.config_alertes)
        if self.au_changement:
            self.au_changement(self.config_alertes)
        self.grab_release()
        self.destroy()
