"""
Interface de bureau (customtkinter).

    python interface_bureau.py

Disposition :
  - barre du haut  : réglages (Top N, intervalle), analyse et alertes Discord ;
  - panneau gauche : cases à cocher des 20 indicateurs, groupées par catégorie ;
  - centre         : tableau de synthèse — une ligne par crypto avec son score
                     global et ses quatre scores de famille. Volontairement
                     compact : le détail par indicateur s'obtient en cliquant ;
  - panneau droit  : tous les critères de la crypto sélectionnée.

L'analyse tourne dans un thread : sans cela, les téléchargements réseau
figeraient la fenêtre pendant plusieurs secondes.
"""

from __future__ import annotations

import threading
import tkinter as tk

import customtkinter as ctk

import notifications as notif
import presentation as pr
import suivi
from fenetre_alertes import FenetreAlertes
from fenetre_suivi import FenetreSuivi, planifier
from indicateurs import CODES_PAR_DEFAUT, Categorie, catalogue, codes_par_categorie
from moteur import AnalyseurMarche

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

POLICE_TITRE = ("Segoe UI", 20, "bold")
POLICE_SOUS_TITRE = ("Segoe UI", 13, "bold")
POLICE_NORMALE = ("Segoe UI", 12)
POLICE_PETITE = ("Segoe UI", 11)
POLICE_CELLULE = ("Segoe UI", 12, "bold")

# Colonnes du tableau de synthèse : identité, marché, puis les scores.
# « Indic. » indique combien d'indicateurs ont réellement pu être calculés.
# C'est un garde-fou de lecture : une crypto dont l'historique est court (jeton
# récent, seulement disponible chez Yahoo) est notée sur moins d'indicateurs,
# et son score n'a donc pas la même solidité que celui du Bitcoin.
COLONNES_FIXES = [
    ("Crypto", 105),
    ("Prix", 100),
    ("24 h", 75),
    ("Indic.", 60),
    ("Score", 70),
]


class ApplicationBureau(ctk.CTk):
    """Fenêtre principale du tableau de bord."""

    def __init__(self):
        super().__init__()
        self.title("CryptoDashboard — analyse technique qualitative")
        self.geometry("1400x880")
        self.minsize(1100, 700)

        # État de l'application
        self.resultats = []
        self.selection = {}          # code indicateur -> BooleanVar
        self.analyse_en_cours = False
        self.envoyer_apres_analyse = False
        self.symbole_detaille = None
        self.config_alertes = notif.charger_config()
        self._job_auto = None        # identifiant du prochain envoi programmé
        self._fenetre_alertes = None
        self.journal = suivi.JournalSuivi()   # classeur de suivi des performances
        self.historiques = {}                 # bougies de la dernière analyse
        self._fenetre_suivi = None

        # Grille 3 colonnes : indicateurs / tableau / détail
        self.grid_columnconfigure(1, weight=2)
        self.grid_columnconfigure(2, weight=3)
        self.grid_rowconfigure(1, weight=1)

        self._construire_barre_haut()
        self._construire_panneau_indicateurs()
        self._construire_tableau()
        self._construire_detail()

        self.protocol("WM_DELETE_WINDOW", self._fermer)
        self._programmer_envoi_auto()

    # =====================================================================
    # CONSTRUCTION DE L'INTERFACE
    # =====================================================================
    def _construire_barre_haut(self):
        barre = ctk.CTkFrame(self, corner_radius=0, height=70)
        barre.grid(row=0, column=0, columnspan=3, sticky="ew")
        barre.grid_propagate(False)

        ctk.CTkLabel(barre, text="CryptoDashboard", font=POLICE_TITRE).pack(
            side="left", padx=20
        )

        ctk.CTkLabel(barre, text="Cryptos :", font=POLICE_NORMALE).pack(side="left", padx=(15, 5))
        self.champ_nombre = ctk.CTkComboBox(
            barre, values=["5", "10", "15", "20", "30", "50"], width=75, font=POLICE_NORMALE
        )
        self.champ_nombre.set("20")
        self.champ_nombre.pack(side="left", padx=5)

        ctk.CTkLabel(barre, text="Intervalle :", font=POLICE_NORMALE).pack(side="left", padx=(15, 5))
        self.champ_intervalle = ctk.CTkComboBox(
            barre, values=list(pr.INTERVALLES), width=150, font=POLICE_NORMALE
        )
        self.champ_intervalle.set("Journalier (1d)")
        self.champ_intervalle.pack(side="left", padx=5)

        self.bouton_analyser = ctk.CTkButton(
            barre, text="Analyser", width=110, height=36,
            font=POLICE_SOUS_TITRE, command=self.lancer_analyse,
        )
        self.bouton_analyser.pack(side="left", padx=15)

        # --- Alertes Discord ---
        self.bouton_envoyer = ctk.CTkButton(
            barre, text="Envoyer sur Discord", width=160, height=36, font=POLICE_PETITE,
            fg_color="#5865F2", hover_color="#4752c4", command=self._envoyer_manuel,
        )
        self.bouton_envoyer.pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            barre, text="⚙ Alertes", width=95, height=36, font=POLICE_PETITE,
            fg_color="#555b66", hover_color="#6b7280", command=self._ouvrir_alertes,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            barre, text="📈 Suivi", width=95, height=36, font=POLICE_PETITE,
            fg_color="#555b66", hover_color="#6b7280", command=self._ouvrir_suivi,
        ).pack(side="left")

        self.etiquette_etat = ctk.CTkLabel(
            barre, text="Prêt.", font=POLICE_PETITE, text_color="#9aa0a6", anchor="w"
        )
        self.etiquette_etat.pack(side="left", padx=12, fill="x", expand=True)

    def _construire_panneau_indicateurs(self):
        """Colonne de gauche : la sélection des indicateurs."""
        cadre = ctk.CTkFrame(self, width=250, corner_radius=0)
        cadre.grid(row=1, column=0, sticky="nsw")
        cadre.grid_propagate(False)

        ctk.CTkLabel(cadre, text="INDICATEURS", font=POLICE_SOUS_TITRE).pack(pady=(15, 5))

        boutons = ctk.CTkFrame(cadre, fg_color="transparent")
        boutons.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkButton(
            boutons, text="Tout", height=26, font=POLICE_PETITE,
            command=lambda: self._basculer_tout(True),
        ).pack(side="left", expand=True, fill="x", padx=2)
        ctk.CTkButton(
            boutons, text="Rien", height=26, font=POLICE_PETITE, fg_color="#555b66",
            hover_color="#6b7280", command=lambda: self._basculer_tout(False),
        ).pack(side="left", expand=True, fill="x", padx=2)

        liste = ctk.CTkScrollableFrame(cadre, fg_color="transparent")
        liste.pack(fill="both", expand=True, padx=8, pady=(0, 10))

        # Groupés par catégorie, dans l'ordre du registre : c'est celui qui parle
        # le plus à l'utilisateur.
        fiches = catalogue().set_index("code")
        for categorie in Categorie:
            codes = codes_par_categorie(categorie)
            if not codes:
                continue
            ctk.CTkLabel(
                liste, text=categorie.value.upper(), font=POLICE_PETITE, text_color="#7c8695"
            ).pack(anchor="w", pady=(10, 2))

            for code in codes:
                variable = tk.BooleanVar(value=True)
                self.selection[code] = variable
                ctk.CTkCheckBox(
                    liste, text=fiches.loc[code, "nom"], variable=variable,
                    font=POLICE_PETITE, checkbox_width=18, checkbox_height=18,
                ).pack(anchor="w", pady=1)

    def _construire_tableau(self):
        """Colonne centrale : le tableau de synthèse (scores uniquement)."""
        cadre = ctk.CTkFrame(self, corner_radius=0)
        cadre.grid(row=1, column=1, sticky="nsew", padx=(1, 0))
        cadre.grid_rowconfigure(1, weight=1)
        cadre.grid_columnconfigure(0, weight=1)

        entete = ctk.CTkFrame(cadre, fg_color="transparent")
        entete.grid(row=0, column=0, sticky="ew", pady=(10, 4))
        ctk.CTkLabel(entete, text="SYNTHÈSE", font=POLICE_SOUS_TITRE).pack()
        ctk.CTkLabel(
            entete, text="Cliquez sur une ligne pour voir le détail des indicateurs",
            font=POLICE_PETITE, text_color="#7c8695",
        ).pack()

        self.zone_tableau = ctk.CTkScrollableFrame(cadre, fg_color="transparent")
        self.zone_tableau.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        ctk.CTkLabel(
            self.zone_tableau,
            text="Choisissez vos indicateurs puis cliquez sur « Analyser ».",
            font=POLICE_NORMALE, text_color="#7c8695",
        ).pack(pady=40)

    def _construire_detail(self):
        """Colonne de droite : le détail des critères d'une crypto."""
        cadre = ctk.CTkFrame(self, corner_radius=0)
        cadre.grid(row=1, column=2, sticky="nsew", padx=(1, 0))
        cadre.grid_rowconfigure(1, weight=1)
        cadre.grid_columnconfigure(0, weight=1)

        self.titre_detail = ctk.CTkLabel(cadre, text="DÉTAIL", font=POLICE_SOUS_TITRE)
        self.titre_detail.grid(row=0, column=0, pady=10)

        self.zone_detail = ctk.CTkScrollableFrame(cadre, fg_color="transparent")
        self.zone_detail.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        ctk.CTkLabel(
            self.zone_detail, text="Cliquez sur une crypto du tableau.",
            font=POLICE_PETITE, text_color="#7c8695",
        ).pack(pady=30)

    # =====================================================================
    # SÉLECTION ET ANALYSE
    # =====================================================================
    def _basculer_tout(self, valeur: bool):
        for variable in self.selection.values():
            variable.set(valeur)

    def _codes_selectionnes(self) -> list[str]:
        """Codes cochés, dans l'ordre du registre pour un affichage stable."""
        return [code for code in CODES_PAR_DEFAUT if self.selection[code].get()]

    def _etat(self, message: str):
        self.etiquette_etat.configure(text=message)

    def lancer_analyse(self, envoyer_apres: bool = False):
        """Démarre l'analyse en arrière-plan et verrouille le bouton."""
        if self.analyse_en_cours:
            return

        codes = self._codes_selectionnes()
        if not codes:
            self._etat("Sélectionnez au moins un indicateur.")
            return

        try:
            nombre = int(self.champ_nombre.get())
        except ValueError:
            nombre = 20

        intervalle = pr.INTERVALLES[self.champ_intervalle.get()]
        bougies = pr.BOUGIES_PAR_INTERVALLE.get(intervalle, 400)

        self.analyse_en_cours = True
        self.envoyer_apres_analyse = envoyer_apres
        self.bouton_analyser.configure(state="disabled", text="Analyse...")
        self._etat(f"Téléchargement et analyse de {nombre} cryptos ({len(codes)} indicateurs)...")

        threading.Thread(
            target=self._analyser_en_fond,
            args=(codes, nombre, intervalle, bougies),
            daemon=True,
        ).start()

    def _analyser_en_fond(self, codes, nombre, intervalle, bougies):
        """Exécuté hors du thread graphique : aucun widget ne doit être touché ici."""
        suivi_message = ""
        try:
            analyseur = AnalyseurMarche(
                codes=codes, intervalle=intervalle, nb_bougies=bougies, verbeux=False
            )
            resultats, erreur = analyseur.analyser_top(nombre), None
            historiques = analyseur.historiques
            # Le suivi (Excel + éventuels rechargements) reste dans ce thread.
            suivi_message = self._journaliser(
                resultats, historiques, intervalle, codes,
                origine="auto" if self.envoyer_apres_analyse else "analyse",
                source=analyseur.source,
            )
        except Exception as e:
            historiques = {}
            resultats, erreur = [], f"{type(e).__name__} : {e}"

        # Retour dans le thread graphique, seul autorisé à modifier l'affichage.
        planifier(self, self._analyse_terminee, resultats, erreur, historiques, suivi_message)

    def _analyse_terminee(self, resultats, erreur, historiques=None, suivi_message=""):
        self.analyse_en_cours = False
        self.bouton_analyser.configure(state="normal", text="Analyser")

        if erreur:
            self._etat(f"Échec : {erreur}")
            self.envoyer_apres_analyse = False
            return

        self.resultats = resultats
        self.historiques = historiques or {}
        exploitables = [r for r in resultats if r.indicateurs_notes]
        message = f"{len(exploitables)}/{len(resultats)} cryptos analysées."
        self._afficher_tableau()

        # Le suivi a déjà été alimenté par le thread de travail : il ne reste
        # qu'à en afficher le bilan.
        self._etat(f"{message}  {suivi_message}".strip())

        if exploitables:
            self._afficher_detail(exploitables[0].symbole)

        # Envoi programmé : on n'alerte qu'une fois les résultats disponibles.
        if self.envoyer_apres_analyse:
            self.envoyer_apres_analyse = False
            self._envoyer(self.config_alertes, automatique=True)

    # =====================================================================
    # TABLEAU DE SYNTHÈSE
    # =====================================================================
    def _vider(self, cadre):
        for enfant in cadre.winfo_children():
            enfant.destroy()

    def _afficher_tableau(self):
        """
        Reconstruit le tableau : identité, marché, score global et scores de
        famille. Pas de colonne par indicateur — le détail est dans le panneau
        de droite, où il est réellement lisible.
        """
        self._vider(self.zone_tableau)

        entetes = COLONNES_FIXES + [(c.value, 90) for c in Categorie]
        for colonne, (texte, largeur) in enumerate(entetes):
            self.zone_tableau.grid_columnconfigure(colonne, weight=1)
            ctk.CTkLabel(
                self.zone_tableau, text=texte, font=POLICE_PETITE,
                text_color="#9aa0a6", width=largeur,
            ).grid(row=0, column=colonne, padx=2, pady=(0, 6), sticky="ew")

        # Les mieux notées en premier, celles sans historique exploitable à la fin.
        ordonnes = sorted(
            self.resultats, key=lambda r: (not r.indicateurs_notes, -r.score_global)
        )
        for ligne, resultat in enumerate(ordonnes, start=1):
            self._construire_ligne(ligne, resultat)

    def _construire_ligne(self, ligne: int, resultat):
        """Une ligne : identité, prix, variation, score global, scores de famille."""
        cliquer = lambda _e, s=resultat.symbole: self._afficher_detail(s)

        identite = ctk.CTkLabel(
            self.zone_tableau, text=resultat.symbole, font=POLICE_CELLULE,
            width=110, anchor="w",
        )
        identite.grid(row=ligne, column=0, padx=2, pady=1, sticky="ew")
        identite.bind("<Button-1>", cliquer)

        prix = ctk.CTkLabel(
            self.zone_tableau, text=pr.formater_prix(resultat.prix),
            font=POLICE_PETITE, width=100, anchor="e",
        )
        prix.grid(row=ligne, column=1, padx=2, sticky="ew")
        prix.bind("<Button-1>", cliquer)

        variation = resultat.variation_24h
        cellule_var = ctk.CTkLabel(
            self.zone_tableau, text=pr.formater_variation(variation),
            font=POLICE_PETITE, width=75, anchor="e",
            text_color=pr.COULEURS_SIGNAL[
                pr.Signal.POSITIF if (variation or 0) >= 0 else pr.Signal.NEGATIF
            ],
        )
        cellule_var.grid(row=ligne, column=2, padx=2, sticky="ew")
        cellule_var.bind("<Button-1>", cliquer)

        # Crypto sans historique exploitable : on l'affiche avec sa raison plutôt
        # que de la masquer, pour que l'absence soit explicable.
        if not resultat.indicateurs_notes:
            ctk.CTkLabel(
                self.zone_tableau, text=resultat.raison_indisponible, font=POLICE_PETITE,
                text_color="#7c8695", anchor="w",
            ).grid(row=ligne, column=3, columnspan=len(Categorie) + 2, padx=4, sticky="ew")
            return

        # Couverture : combien d'indicateurs ont pu être calculés, sur combien
        # de demandés ? On compte ici les indicateurs VALIDES et non les notés,
        # sinon l'ATR — volontairement non noté — passerait pour un échec.
        notes, demandes = len(resultat.indicateurs_valides), len(resultat.resultats)
        partielle = notes < demandes
        couverture = ctk.CTkLabel(
            self.zone_tableau, text=f"{notes}/{demandes}", font=POLICE_PETITE, width=60,
            text_color="#e0a458" if partielle else "#7c8695",
        )
        couverture.grid(row=ligne, column=3, padx=2, sticky="ew")
        couverture.bind("<Button-1>", cliquer)

        score = ctk.CTkLabel(
            self.zone_tableau, text=pr.formater_score(resultat.score_global),
            font=POLICE_CELLULE, width=70, corner_radius=4,
            fg_color=pr.couleur_score(resultat.score_global), text_color="white",
        )
        score.grid(row=ligne, column=4, padx=2, pady=1, sticky="ew")
        score.bind("<Button-1>", cliquer)

        for colonne, categorie in enumerate(Categorie, start=5):
            valeur = resultat.score_categorie(categorie)
            cellule = ctk.CTkLabel(
                self.zone_tableau,
                text="—" if valeur is None else pr.formater_score(valeur),
                font=POLICE_CELLULE, width=90, corner_radius=4, text_color="white",
                fg_color=pr.COULEUR_INDISPONIBLE if valeur is None else pr.couleur_score(valeur),
            )
            cellule.grid(row=ligne, column=colonne, padx=2, pady=1, sticky="ew")
            cellule.bind("<Button-1>", cliquer)

    # =====================================================================
    # PANNEAU DE DÉTAIL
    # =====================================================================
    def _afficher_detail(self, symbole: str):
        """Tous les critères qualitatifs de la crypto choisie."""
        self.symbole_detaille = symbole
        resultat = next((r for r in self.resultats if r.symbole == symbole), None)
        if resultat is None:
            return

        self._vider(self.zone_detail)
        self.titre_detail.configure(text=f"DÉTAIL — {symbole}")

        bandeau = ctk.CTkFrame(self.zone_detail, fg_color=pr.couleur_score(resultat.score_global))
        bandeau.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            bandeau,
            text=f"{resultat.nom or symbole} — {resultat.synthese} "
                 f"({pr.formater_score(resultat.score_global)})",
            font=POLICE_SOUS_TITRE, text_color="white",
        ).pack(pady=6)

        if not resultat.indicateurs_notes:
            ctk.CTkLabel(
                self.zone_detail, text=resultat.raison_indisponible, font=POLICE_PETITE,
                text_color="#7c8695", wraplength=440, justify="left",
            ).pack(pady=20)
            return

        compte = resultat.compter_signaux()
        ctk.CTkLabel(
            self.zone_detail,
            text=f"{compte['positifs']} critères positifs · {compte['neutres']} neutres "
                 f"· {compte['negatifs']} négatifs",
            font=POLICE_PETITE, text_color="#9aa0a6",
        ).pack(anchor="w", pady=(0, 8))

        categorie_courante = None
        for indicateur in resultat.resultats.values():
            if indicateur.categorie.value != categorie_courante:
                categorie_courante = indicateur.categorie.value
                ctk.CTkLabel(
                    self.zone_detail, text=categorie_courante.upper(),
                    font=POLICE_PETITE, text_color="#7c8695",
                ).pack(anchor="w", pady=(12, 2))
            self._construire_bloc_indicateur(indicateur)

    def _construire_bloc_indicateur(self, indicateur):
        """Un indicateur et la liste de ses critères qualitatifs."""
        bloc = ctk.CTkFrame(self.zone_detail)
        bloc.pack(fill="x", pady=2)

        entete = ctk.CTkFrame(bloc, fg_color="transparent")
        entete.pack(fill="x", padx=8, pady=(6, 2))
        ctk.CTkLabel(entete, text=indicateur.nom, font=POLICE_SOUS_TITRE, anchor="w").pack(
            side="left"
        )
        ctk.CTkLabel(
            entete, text=indicateur.synthese, font=POLICE_PETITE, text_color="white",
            fg_color=pr.couleur_synthese(indicateur.synthese), corner_radius=4, padx=6,
        ).pack(side="right")

        if indicateur.erreur:
            ctk.CTkLabel(
                bloc, text=indicateur.erreur, font=POLICE_PETITE,
                text_color="#7c8695", anchor="w", justify="left", wraplength=430,
            ).pack(fill="x", padx=8, pady=(0, 6))
            return

        for critere in indicateur.criteres:
            ligne = ctk.CTkFrame(bloc, fg_color="transparent")
            ligne.pack(fill="x", padx=8, pady=1)

            marque = critere.signal.symbole if critere.directionnel else "·"
            ctk.CTkLabel(
                ligne, text=marque, font=POLICE_CELLULE, width=26, corner_radius=3,
                fg_color=pr.couleur_critere(critere), text_color="white",
            ).pack(side="left", padx=(0, 6))

            valeur = pr.formater_valeur_critere(critere.valeur_num)
            texte = f"{critere.libelle} : {critere.valeur}"
            if valeur:
                texte += f"  ({valeur})"
            ctk.CTkLabel(
                ligne, text=texte, font=POLICE_PETITE, anchor="w",
                justify="left", wraplength=470,
            ).pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(bloc, text="", height=2).pack()

    # =====================================================================
    # SUIVI DES PERFORMANCES
    # =====================================================================
    def _journaliser(self, resultats, historiques, intervalle, codes, origine, source=None) -> str:
        """
        Enregistre les scores de l'analyse qui vient de se terminer, puis vérifie
        les relevés arrivés à échéance. Renvoie une phrase d'état.

        Appelée depuis le THREAD DE TRAVAIL : elle ne touche aucun widget, et
        peut donc se permettre les accès disque et réseau qu'elle implique.

        Les historiques de l'analyse sont réutilisés pour la vérification (le
        prix d'échéance est lu dans la bougie exacte) ; `source` sert de recours
        pour les relevés d'un autre intervalle, que ces bougies ne couvrent pas.
        """
        try:
            ajoutes = self.journal.enregistrer(resultats, intervalle, codes, origine=origine)
            bilan = self.journal.verifier(historiques=historiques, source=source)
            ok, detail = self.journal.sauvegarder()
        except Exception as e:
            return f"Suivi indisponible ({type(e).__name__})."

        if not ok:
            return detail  # le plus souvent : classeur ouvert dans Excel

        etat = f"Suivi : +{ajoutes} relevés"
        if bilan["verifies"]:
            etat += f", {bilan['verifies']} vérifiés"
        if bilan["expires"]:
            etat += f", {bilan['expires']} expirés"
        return etat + f", {bilan['en_attente']} en attente."

    def _ouvrir_suivi(self):
        """Fenêtre d'évolution des scores et de simulation."""
        if self._fenetre_suivi is not None and self._fenetre_suivi.winfo_exists():
            self._fenetre_suivi.focus()
            return
        self._fenetre_suivi = FenetreSuivi(self, self.journal)

    # =====================================================================
    # ALERTES DISCORD
    # =====================================================================
    def _ouvrir_alertes(self):
        """Ouvre la fenêtre de réglages (une seule à la fois)."""
        if self._fenetre_alertes is not None and self._fenetre_alertes.winfo_exists():
            self._fenetre_alertes.focus()
            return
        self._fenetre_alertes = FenetreAlertes(
            self,
            config=self.config_alertes,
            au_changement=self._alertes_modifiees,
            envoyer_maintenant=self._envoyer,
        )

    def _alertes_modifiees(self, config: dict):
        """Rappelée par la fenêtre de réglages : on reprogramme la boucle d'envoi."""
        self.config_alertes = config
        self._programmer_envoi_auto()

    def _envoyer_manuel(self):
        """Bouton « Envoyer sur Discord » de la barre du haut."""
        self._envoyer(self.config_alertes, retour=lambda m, _ok: self._etat(m))

    def _envoyer(self, config: dict, retour=None, automatique: bool = False):
        """
        Envoie l'alerte dans un thread (appel réseau) et rapporte le résultat.

        `retour(message, succes)` est rappelée dans le thread graphique. La
        fenêtre de réglages s'en sert pour afficher son propre message d'état.
        """
        if not self.resultats:
            message = "Lancez d'abord une analyse."
            if retour:
                retour(message, False)
            else:
                self._etat(message)
            return

        if not config.get("webhook"):
            message = "Aucun webhook configuré (bouton ⚙ Alertes)."
            if retour:
                retour(message, False)
            else:
                self._etat(message)
            return

        intervalle = self.champ_intervalle.get()

        def travail():
            ok, detail = notif.envoyer_alerte(self.resultats, config, intervalle)
            prefixe = "Envoi automatique — " if automatique else ""
            planifier(self, self._envoi_termine, prefixe + detail, ok, retour)

        threading.Thread(target=travail, daemon=True).start()

    def _envoi_termine(self, message: str, succes: bool, retour):
        self._etat(message)
        # La fenêtre de réglages a pu être fermée entre-temps.
        if retour is not None:
            try:
                retour(message, succes)
            except tk.TclError:
                pass

    # -- Boucle d'envoi automatique ----------------------------------------
    def _programmer_envoi_auto(self):
        """(Re)programme le prochain envoi automatique, ou l'annule."""
        self._annuler_envoi_auto()

        if not (self.config_alertes.get("auto") and self.config_alertes.get("actif")):
            return

        delai = notif.intervalle_en_ms(self.config_alertes)
        self._job_auto = self.after(delai, self._tic_auto)
        minutes = delai / 60_000
        self._etat(f"Envoi automatique programmé dans {minutes:.0f} min.")

    def _annuler_envoi_auto(self):
        if self._job_auto is not None:
            self.after_cancel(self._job_auto)
            self._job_auto = None

    def _tic_auto(self):
        """
        Échéance atteinte : on relance une analyse complète (données fraîches)
        puis on envoie. Si une analyse manuelle est déjà en cours, on saute ce
        tour plutôt que de lancer deux analyses concurrentes.
        """
        self._job_auto = None
        if not self.analyse_en_cours:
            self.lancer_analyse(envoyer_apres=True)
        self._programmer_envoi_auto()

    # =====================================================================
    def _fermer(self):
        self._annuler_envoi_auto()
        self.destroy()


def main():
    ApplicationBureau().mainloop()


if __name__ == "__main__":
    main()
