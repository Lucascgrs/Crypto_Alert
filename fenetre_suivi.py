"""
Fenêtre de suivi, en deux onglets.

« Évolution des scores » trace la trajectoire de chaque crypto dans le temps :
on choisit les cryptos, le type de score (global ou l'une des quatre familles)
et l'intervalle. Chaque analyse ajoute un point.

« Simulation » remonte le temps : les scores sont recalculés à chaque barre du
passé et les allers-retours qu'ils auraient déclenchés sont rejoués, pour
répondre à « combien aurais-je gagné en misant telle somme ». Voir
`simulation.py` pour les règles du jeu.

Le bilan des vérifications au fil de l'eau n'a plus d'onglet : il reste écrit
dans le classeur Excel (feuilles « Vérifications » et « Performance »), que le
bouton « Ouvrir le classeur » atteint directement. La simulation répond à la
même question de façon plus directe, en rejouant la stratégie sur le passé.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk

import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import graphiques
import presentation as pr
import simulation as mod_simulation
import suivi as mod_suivi
from donnees import SourceDonnees

def planifier(widget, rappel, *arguments):
    """
    Fait exécuter `rappel` par le thread graphique, depuis un thread de travail.

    Tkinter n'est pas réentrant : seul le thread qui fait tourner la boucle
    d'événements peut toucher aux widgets. `after(0, ...)` est le passe-plat
    habituel, mais il lève si la fenêtre a été fermée entre-temps — ce qui
    arrive très bien quand un calcul dure une dizaine de secondes. On absorbe
    donc l'échec : il n'y a plus personne pour afficher le résultat, ce n'est
    pas une erreur.
    """
    try:
        if widget.winfo_exists():
            widget.after(0, rappel, *arguments)
    except (tk.TclError, RuntimeError):
        pass

POLICE_TITRE = ("Segoe UI", 15, "bold")
POLICE_SOUS_TITRE = ("Segoe UI", 12, "bold")
POLICE_NORMALE = ("Segoe UI", 12)
POLICE_PETITE = ("Segoe UI", 11)


class FenetreSuivi(ctk.CTkToplevel):
    """Fenêtre de consultation, en lecture seule."""

    def __init__(self, parent, journal):
        super().__init__(parent)
        self.title("Suivi et simulation")
        self.geometry("1240x800")
        self.journal = journal

        # Attribution persistante : une crypto garde sa couleur d'un
        # rafraîchissement à l'autre, et quand la sélection change.
        self.couleurs = pr.AttributionCouleurs("sombre")
        self.selection_cryptos = {}   # symbole -> BooleanVar
        self.canevas = None

        self.transient(parent)
        self._construire()

    def _construire(self):
        entete = ctk.CTkFrame(self, fg_color="transparent")
        entete.pack(fill="x", padx=16, pady=(14, 6))

        ctk.CTkLabel(entete, text="Suivi et simulation", font=POLICE_TITRE).pack(side="left")
        ctk.CTkButton(
            entete, text="Ouvrir le classeur", width=150, height=30, font=POLICE_PETITE,
            command=self._ouvrir_classeur,
        ).pack(side="right")
        ctk.CTkButton(
            entete, text="Rafraîchir", width=100, height=30, font=POLICE_PETITE,
            fg_color="#555b66", hover_color="#6b7280", command=self._rafraichir,
        ).pack(side="right", padx=6)

        self.etiquette_resume = ctk.CTkLabel(
            self, text="", font=POLICE_NORMALE, text_color="#9aa0a6", anchor="w"
        )
        self.etiquette_resume.pack(fill="x", padx=16, pady=(0, 6))

        onglets = ctk.CTkTabview(self, anchor="w")
        onglets.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.onglet_evolution = onglets.add("Évolution des scores")
        self.onglet_simulation = onglets.add("Simulation")

        self._construire_evolution(self.onglet_evolution)
        self._construire_simulation(self.onglet_simulation)

        self._rafraichir()

    # -- Contenu ------------------------------------------------------------
    def _rafraichir(self):
        self.etiquette_resume.configure(text=self.journal.resume())
        self._rafraichir_selection()
        self._tracer()

    # =====================================================================
    # ONGLET ÉVOLUTION
    # =====================================================================
    def _construire_evolution(self, parent):
        """Barre de réglages, graphique, puis tableau des valeurs."""
        reglages = ctk.CTkFrame(parent, fg_color="transparent")
        reglages.pack(fill="x", pady=(6, 4))

        ctk.CTkLabel(reglages, text="Score :", font=POLICE_NORMALE).pack(side="left")
        self.menu_type = ctk.CTkOptionMenu(
            reglages, width=140, font=POLICE_NORMALE,
            values=list(mod_suivi.TYPES_SCORE),
            command=lambda _v: self._tracer(),
        )
        self.menu_type.set("Global")
        self.menu_type.pack(side="left", padx=(6, 18))

        ctk.CTkLabel(reglages, text="Intervalle :", font=POLICE_NORMALE).pack(side="left")
        self.menu_intervalle = ctk.CTkOptionMenu(
            reglages, width=110, font=POLICE_NORMALE, values=["—"],
            command=lambda _v: self._rafraichir_selection(garder=True) or self._tracer(),
        )
        self.menu_intervalle.pack(side="left", padx=6)

        self.etiquette_selection = ctk.CTkLabel(
            reglages, text="", font=POLICE_PETITE, text_color="#7c8695"
        )
        self.etiquette_selection.pack(side="right", padx=6)

        # Cases à cocher des cryptos, sur une ligne défilante horizontalement.
        self.zone_cryptos = ctk.CTkScrollableFrame(
            parent, fg_color="transparent", orientation="horizontal", height=48
        )
        self.zone_cryptos.pack(fill="x", pady=(0, 6))

        self.zone_graphique = ctk.CTkFrame(parent, fg_color="transparent")
        self.zone_graphique.pack(fill="both", expand=True)

        ctk.CTkLabel(
            parent,
            text="La bande grise est la zone neutre : entre -0,15 et +0,15, l'application "
                 "n'annonce aucune direction.\nL'échelle est fixée à [-1, +1] : une même "
                 "variation garde ainsi la même ampleur d'un relevé à l'autre.",
            font=POLICE_PETITE, text_color="#7c8695", justify="left", anchor="w",
        ).pack(fill="x", pady=(6, 2))

        # Tableau des valeurs sous le graphique : il double l'information de la
        # couleur, condition posée par les teintes claires les moins contrastées.
        self.zone_valeurs = ctk.CTkScrollableFrame(parent, fg_color="transparent", height=130)
        self.zone_valeurs.pack(fill="x", pady=(0, 4))

    def _rafraichir_selection(self, garder: bool = False):
        """
        Reconstruit la liste des cryptos disponibles.

        `garder=True` préserve les cases déjà cochées (changement d'intervalle) ;
        sinon les plus souvent relevées sont présélectionnées.
        """
        intervalles = self.journal.intervalles_suivis()
        valeurs = intervalles or ["—"]
        self.menu_intervalle.configure(values=valeurs)
        if self.menu_intervalle.get() not in valeurs:
            self.menu_intervalle.set(valeurs[0])

        intervalle = self.menu_intervalle.get()
        symboles = self.journal.symboles_suivis(intervalle if intervalles else None)
        deja = {s for s, v in self.selection_cryptos.items() if v.get()} if garder else set()

        for enfant in self.zone_cryptos.winfo_children():
            enfant.destroy()
        self.selection_cryptos = {}

        for rang, symbole in enumerate(symboles):
            # Présélection des plus suivies, dans la limite de la palette.
            actif = symbole in deja if garder else rang < pr.MAX_SERIES
            variable = ctk.BooleanVar(value=actif)
            self.selection_cryptos[symbole] = variable
            ctk.CTkCheckBox(
                self.zone_cryptos, text=symbole, variable=variable,
                font=POLICE_PETITE, checkbox_width=17, checkbox_height=17,
                width=80, command=self._tracer,
            ).pack(side="left", padx=5)

    def _cryptos_cochees(self) -> list[str]:
        return [s for s, v in self.selection_cryptos.items() if v.get()]

    def _tracer(self):
        """Recalcule le tableau croisé et redessine le graphique."""
        choisies = self._cryptos_cochees()
        depassement = max(0, len(choisies) - pr.MAX_SERIES)
        # Au-delà de huit séries, deux teintes deviendraient indiscernables :
        # on tronque plutôt que d'inventer une neuvième couleur.
        choisies = choisies[: pr.MAX_SERIES]
        self.couleurs.oublier(choisies)

        type_score = self.menu_type.get()
        intervalle = self.menu_intervalle.get()
        table = self.journal.evolution(
            type_score, choisies, intervalle if intervalle != "—" else None
        )

        self.etiquette_selection.configure(
            text=f"{len(choisies)} crypto(s) affichée(s)"
                 + (f" — {depassement} au-delà des {pr.MAX_SERIES} couleurs disponibles"
                    if depassement else "")
        )

        figure = graphiques.figure_evolution(
            table, type_score, self.couleurs, mode="sombre",
            intervalle=intervalle if intervalle != "—" else "",
            largeur=10.6, hauteur=4.3,
        )
        if self.canevas is not None:
            self.canevas.get_tk_widget().destroy()
        self.canevas = FigureCanvasTkAgg(figure, master=self.zone_graphique)
        self.canevas.draw()
        self.canevas.get_tk_widget().pack(fill="both", expand=True)

        self._afficher_valeurs(table)

    def _afficher_valeurs(self, table):
        """Les derniers relevés en clair, sous le graphique."""
        for enfant in self.zone_valeurs.winfo_children():
            enfant.destroy()
        if table is None or table.empty:
            return

        derniers = table.tail(8)
        colonnes = list(derniers.columns)

        ctk.CTkLabel(
            self.zone_valeurs, text="Relevé", font=POLICE_PETITE,
            text_color="#9aa0a6", width=130, anchor="w",
        ).grid(row=0, column=0, padx=3, sticky="ew")
        for colonne, symbole in enumerate(colonnes, start=1):
            cadre = ctk.CTkFrame(self.zone_valeurs, fg_color="transparent")
            cadre.grid(row=0, column=colonne, padx=3, sticky="ew")
            # Pastille colorée + nom en encre de texte : c'est la pastille qui
            # porte l'identité, jamais la couleur du texte.
            ctk.CTkLabel(
                cadre, text=" ", width=10, height=10, corner_radius=3,
                fg_color=self.couleurs.couleur(symbole),
            ).pack(side="left", padx=(0, 4))
            ctk.CTkLabel(
                cadre, text=symbole, font=POLICE_PETITE, text_color="#9aa0a6"
            ).pack(side="left")

        for ligne, (horodatage, valeurs) in enumerate(derniers.iterrows(), start=1):
            ctk.CTkLabel(
                self.zone_valeurs, text=f"{horodatage:%d/%m %H:%M}", font=POLICE_PETITE,
                width=130, anchor="w",
            ).grid(row=ligne, column=0, padx=3, sticky="ew")
            for colonne, symbole in enumerate(colonnes, start=1):
                valeur = valeurs[symbole]
                ctk.CTkLabel(
                    self.zone_valeurs,
                    text="—" if valeur != valeur else pr.formater_score(valeur),
                    font=POLICE_PETITE, width=70,
                ).grid(row=ligne, column=colonne, padx=3, sticky="ew")

    # =====================================================================
    # ONGLET SIMULATION
    # =====================================================================
    def _construire_simulation(self, parent):
        """
        Réglages de la stratégie à gauche, résultats à droite.

        Tout est modifiable sans relancer la fenêtre : c'est un outil qu'on
        utilise en faisant varier un paramètre à la fois.
        """
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        reglages = ctk.CTkScrollableFrame(parent, width=310, fg_color="transparent")
        reglages.grid(row=0, column=0, sticky="nsw", padx=(0, 8))

        self.champs_simu = {}

        def champ(libelle, valeur, indice=""):
            """Une étiquette et une zone de saisie."""
            ctk.CTkLabel(reglages, text=libelle, font=POLICE_PETITE, anchor="w").pack(
                fill="x", pady=(8, 2)
            )
            entree = ctk.CTkEntry(reglages, font=POLICE_NORMALE, height=30)
            entree.insert(0, str(valeur))
            entree.pack(fill="x")
            if indice:
                ctk.CTkLabel(
                    reglages, text=indice, font=POLICE_PETITE, text_color="#7c8695",
                    anchor="w", justify="left", wraplength=280,
                ).pack(fill="x")
            return entree

        def menu(libelle, valeurs, defaut):
            ctk.CTkLabel(reglages, text=libelle, font=POLICE_PETITE, anchor="w").pack(
                fill="x", pady=(8, 2)
            )
            option = ctk.CTkOptionMenu(reglages, values=valeurs, font=POLICE_NORMALE, height=30)
            option.set(defaut)
            option.pack(fill="x")
            return option

        ctk.CTkLabel(reglages, text="MISE ET HORIZON", font=POLICE_SOUS_TITRE).pack(
            fill="x", pady=(4, 0)
        )
        self.champs_simu["mise"] = champ("Mise par crypto ($)", 1000)
        self.champs_simu["intervalle"] = menu(
            "Intervalle des bougies", list(pr.INTERVALLES), "Journalier (1d)"
        )
        self.champs_simu["periodes"] = champ(
            "Périodes simulées (en arrière)", 150,
            "Nombre de bougies passées sur lesquelles la stratégie est rejouée.",
        )

        ctk.CTkLabel(reglages, text="SIGNAL D'ENTRÉE", font=POLICE_SOUS_TITRE).pack(
            fill="x", pady=(14, 0)
        )
        self.champs_simu["type_score"] = menu("Score utilisé", mod_simulation.TYPES_SCORE, "Global")
        self.champs_simu["sens"] = menu(
            "Sens autorisés", mod_simulation.SENS_POSSIBLES, mod_simulation.SENS_LES_DEUX
        )

        self.etiquette_seuils = ctk.CTkLabel(
            reglages, text="", font=POLICE_PETITE, text_color="#7c8695", anchor="w"
        )
        ctk.CTkLabel(
            reglages, text="Seuils sur la valeur absolue du score", font=POLICE_PETITE, anchor="w"
        ).pack(fill="x", pady=(10, 2))
        self.curseur_min = ctk.CTkSlider(
            reglages, from_=0, to=1, number_of_steps=20, command=lambda _v: self._maj_seuils()
        )
        self.curseur_min.set(0.30)
        self.curseur_min.pack(fill="x")
        self.curseur_max = ctk.CTkSlider(
            reglages, from_=0, to=1, number_of_steps=20, command=lambda _v: self._maj_seuils()
        )
        self.curseur_max.set(1.0)
        self.curseur_max.pack(fill="x", pady=(4, 0))
        self.etiquette_seuils.pack(fill="x", pady=(2, 0))

        # --- Sortie : la position se referme au PREMIER motif rempli. ---
        ctk.CTkLabel(reglages, text="SORTIE", font=POLICE_SOUS_TITRE).pack(fill="x", pady=(14, 0))
        ctk.CTkLabel(
            reglages,
            text="La position se referme au premier motif rempli. Laissez 0 pour "
                 "désactiver une condition.",
            font=POLICE_PETITE, text_color="#7c8695", anchor="w", justify="left",
            wraplength=280,
        ).pack(fill="x", pady=(2, 0))

        self.champs_simu["duree"] = champ(
            "Durée maximale de détention (bougies)", 6,
            "Ce qui n'a pas été coupé avant se referme après ce nombre de bougies.",
        )
        self.champs_simu["retournement"] = champ(
            "Retournement du score (points)", 0,
            "Coupe la position si le score choisi se retourne d'autant de points "
            "contre elle, par rapport à sa valeur d'entrée. Vérifié à chaque "
            "bougie. Le score vivant dans [-1, +1], 0,30 est déjà un franc "
            "changement d'avis.",
        )
        self.champs_simu["objectif"] = champ(
            "Objectif de gain (%)", 0,
            "Prise de bénéfice : la position se referme dès que le prix atteint "
            "ce gain, même en cours de bougie.",
        )
        self.champs_simu["stop"] = champ(
            "Stop de perte (%)", 0,
            "Coupe la position dès que la perte atteint ce pourcentage. Si la "
            "bougie ouvre déjà au-delà, la sortie se fait à l'ouverture.",
        )

        ctk.CTkLabel(reglages, text="COÛTS", font=POLICE_SOUS_TITRE).pack(fill="x", pady=(14, 0))
        self.champs_simu["frais"] = champ(
            "Frais par transaction (%)", 0.10,
            "Comptés à l'entrée et à la sortie. Sans eux, une stratégie qui "
            "multiplie les allers-retours paraît toujours rentable.",
        )

        ctk.CTkLabel(reglages, text="CRYPTOS", font=POLICE_SOUS_TITRE).pack(fill="x", pady=(14, 2))
        ctk.CTkButton(
            reglages, text="Charger le Top 20", height=26, font=POLICE_PETITE,
            fg_color="#555b66", hover_color="#6b7280", command=self._charger_cryptos,
        ).pack(fill="x", pady=(0, 4))
        self.zone_cryptos_simu = ctk.CTkFrame(reglages, fg_color="transparent")
        self.zone_cryptos_simu.pack(fill="x")
        self.selection_simu = {}

        self.bouton_simuler = ctk.CTkButton(
            reglages, text="Lancer la simulation", height=36,
            font=POLICE_SOUS_TITRE, command=self._lancer_simulation,
        )
        self.bouton_simuler.pack(fill="x", pady=14)

        # --- Résultats ---
        self.zone_simu = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.zone_simu.grid(row=0, column=1, sticky="nsew")

        self.etiquette_simu = ctk.CTkLabel(
            self.zone_simu,
            text="Réglez la stratégie à gauche, puis lancez la simulation.\n\n"
                 "Les scores sont recalculés à chaque barre du passé avec les seules "
                 "données\ndisponibles à cet instant : aucune information future n'entre "
                 "dans le résultat.",
            font=POLICE_NORMALE, text_color="#7c8695", justify="left",
        )
        self.etiquette_simu.pack(anchor="w", pady=20)

        self.canevas_simu = None
        self.simulation_en_cours = False
        self._maj_seuils()
        self._remplir_cryptos(self.journal.symboles_suivis())

    def _maj_seuils(self):
        """Le seuil maximum ne peut pas passer sous le minimum."""
        bas, haut = self.curseur_min.get(), self.curseur_max.get()
        if haut < bas:
            self.curseur_max.set(bas)
            haut = bas
        self.etiquette_seuils.configure(text=f"De {bas:.2f} à {haut:.2f}")

    def _remplir_cryptos(self, symboles):
        for enfant in self.zone_cryptos_simu.winfo_children():
            enfant.destroy()
        self.selection_simu = {}
        if not symboles:
            ctk.CTkLabel(
                self.zone_cryptos_simu,
                text="Aucune crypto connue.\nChargez le Top 20 ou lancez une analyse.",
                font=POLICE_PETITE, text_color="#7c8695", justify="left",
            ).pack(anchor="w")
            return
        for rang, symbole in enumerate(symboles):
            variable = ctk.BooleanVar(value=rang < 3)   # trois par défaut : c'est rapide
            self.selection_simu[symbole] = variable
            ctk.CTkCheckBox(
                self.zone_cryptos_simu, text=symbole, variable=variable,
                font=POLICE_PETITE, checkbox_width=17, checkbox_height=17,
            ).pack(anchor="w", pady=1)

    def _charger_cryptos(self):
        """Récupère le Top 20 par capitalisation, dans un thread (appel réseau)."""
        self.etiquette_resume.configure(text="Récupération du Top 20...")

        def travail():
            try:
                classement = SourceDonnees(verbeux=False).top_cryptos(20)
                symboles = list(classement.index)
            except Exception as e:
                symboles, erreur = [], f"{type(e).__name__} : {e}"
            else:
                erreur = ""
            planifier(self, self._cryptos_chargees, symboles, erreur)

        threading.Thread(target=travail, daemon=True).start()

    def _cryptos_chargees(self, symboles, erreur):
        if erreur:
            self.etiquette_resume.configure(text=f"Top 20 indisponible : {erreur}")
            return
        self._remplir_cryptos(symboles)
        self.etiquette_resume.configure(text=f"{len(symboles)} cryptos chargées.")

    # -- Lancement ----------------------------------------------------------
    def _lire_parametres(self):
        """Construit les paramètres depuis les champs, en tolérant les saisies libres."""
        def nombre(cle, defaut, entier=False):
            try:
                valeur = float(self.champs_simu[cle].get().replace(",", "."))
                return int(valeur) if entier else valeur
            except (ValueError, AttributeError):
                return defaut

        def optionnel(cle):
            """0 (ou une saisie vide) désactive la condition de sortie."""
            valeur = nombre(cle, 0.0)
            return valeur if valeur > 0 else None

        choisies = [s for s, v in self.selection_simu.items() if v.get()]
        return mod_simulation.ParametresSimulation(
            mise=max(nombre("mise", 1000.0), 1.0),
            intervalle=pr.INTERVALLES[self.champs_simu["intervalle"].get()],
            periodes=max(nombre("periodes", 150, entier=True), 10),
            duree_position=max(nombre("duree", 6, entier=True), 1),
            symboles=choisies,
            type_score=self.champs_simu["type_score"].get(),
            seuil_min=round(self.curseur_min.get(), 2),
            seuil_max=round(self.curseur_max.get(), 2),
            sens=self.champs_simu["sens"].get(),
            codes=None,
            frais_pct=max(nombre("frais", 0.10), 0.0),
            retournement=optionnel("retournement"),
            objectif_pct=optionnel("objectif"),
            stop_pct=optionnel("stop"),
        )

    def _lancer_simulation(self):
        if self.simulation_en_cours:
            return
        parametres = self._lire_parametres()
        if not parametres.symboles:
            self.etiquette_resume.configure(text="Cochez au moins une crypto.")
            return

        self.simulation_en_cours = True
        self.bouton_simuler.configure(state="disabled", text="Simulation...")

        def avancement(fait, total, symbole):
            texte = (f"Simulation {fait}/{total} — {symbole}..." if symbole
                     else "Mise en forme des résultats...")
            planifier(self, lambda: self.etiquette_resume.configure(text=texte))

        def travail():
            try:
                resultats = mod_simulation.Simulateur(verbeux=False).simuler(
                    parametres, progression=avancement
                )
                erreur = ""
            except Exception as e:
                resultats, erreur = [], f"{type(e).__name__} : {e}"
            planifier(self, self._simulation_terminee, resultats, parametres, erreur)

        threading.Thread(target=travail, daemon=True).start()

    def _simulation_terminee(self, resultats, parametres, erreur):
        self.simulation_en_cours = False
        self.bouton_simuler.configure(state="normal", text="Lancer la simulation")

        if erreur:
            self.etiquette_resume.configure(text=f"Échec : {erreur}")
            return

        self.etiquette_resume.configure(text=self.journal.resume())
        self._afficher_simulation(resultats, parametres)

    # -- Affichage ----------------------------------------------------------
    def _afficher_simulation(self, resultats, parametres):
        for enfant in self.zone_simu.winfo_children():
            enfant.destroy()
        self.canevas_simu = None

        ctk.CTkLabel(
            self.zone_simu, text=mod_simulation.resume(resultats, parametres),
            font=POLICE_SOUS_TITRE, justify="left", anchor="w", wraplength=780,
        ).pack(fill="x", pady=(6, 2))

        ctk.CTkLabel(
            self.zone_simu,
            text=f"Entrée : score {parametres.type_score.lower()} entre "
                 f"{parametres.seuil_min:.2f} et {parametres.seuil_max:.2f} · "
                 f"{parametres.sens.lower()}.\n"
                 f"Sortie : {parametres.description_sorties()} · frais "
                 f"{parametres.frais_pct:.2f} % par transaction.\n"
                 f"« Marché » est le rendement d'un simple achat-conservation "
                 f"sur la même période : c'est lui qu'il faut battre.",
            font=POLICE_PETITE, text_color="#7c8695", justify="left", anchor="w",
        ).pack(fill="x", pady=(0, 10))

        self._tableau_simulation(resultats)

        # Par quoi les positions se sont refermées : une stratégie qui ne gagne
        # que par son stop et une autre qui gagne par son signal donnent le même
        # capital final sans valoir la même chose.
        repartition = mod_simulation.Simulateur.repartition_sorties(resultats)
        if len(repartition) > 1:
            ctk.CTkLabel(
                self.zone_simu,
                text="Sorties : " + " · ".join(
                    f"{nombre} par {motif.lower()}" for motif, nombre in repartition.items()
                ),
                font=POLICE_PETITE, text_color="#7c8695", anchor="w",
            ).pack(fill="x", pady=(8, 0))

        courbes = mod_simulation.Simulateur.courbes(resultats)
        cadre = ctk.CTkFrame(self.zone_simu, fg_color="transparent")
        cadre.pack(fill="both", expand=True, pady=(12, 0))
        figure = graphiques.figure_capital(
            courbes, self.couleurs, mode="sombre", largeur=8.6, hauteur=3.6
        )
        self.canevas_simu = FigureCanvasTkAgg(figure, master=cadre)
        self.canevas_simu.draw()
        self.canevas_simu.get_tk_widget().pack(fill="both", expand=True)

        self._tableau_trades(resultats)

    COLONNES_SIMU = [
        ("Crypto", 90, "w"), ("Trades", 70, "center"), ("Réussite %", 90, "center"),
        ("Capital final", 110, "center"), ("Gain", 90, "center"), ("Gain %", 85, "center"),
        ("Marché %", 90, "center"), ("Écart %", 85, "center"),
    ]

    def _tableau_simulation(self, resultats):
        table = mod_simulation.Simulateur.tableau(resultats)
        cadre = ctk.CTkFrame(self.zone_simu, fg_color="transparent")
        cadre.pack(fill="x")

        for colonne, (nom, largeur, _) in enumerate(self.COLONNES_SIMU):
            ctk.CTkLabel(
                cadre, text=nom, font=POLICE_PETITE, text_color="#9aa0a6", width=largeur
            ).grid(row=0, column=colonne, padx=2, pady=(0, 4), sticky="ew")

        for ligne, (_, enregistrement) in enumerate(table.iterrows(), start=1):
            if enregistrement["Détail"]:
                ctk.CTkLabel(
                    cadre, text=f"{enregistrement['Crypto']} — {enregistrement['Détail']}",
                    font=POLICE_PETITE, text_color="#7c8695", anchor="w",
                ).grid(row=ligne, column=0, columnspan=len(self.COLONNES_SIMU),
                       padx=2, sticky="ew")
                continue

            ensemble = enregistrement["Crypto"] == "Ensemble"
            for colonne, (nom, largeur, alignement) in enumerate(self.COLONNES_SIMU):
                valeur = enregistrement[nom]
                options = {"font": POLICE_SOUS_TITRE if ensemble else POLICE_NORMALE}
                texte = "—" if valeur is None or valeur != valeur else str(valeur)

                if nom in ("Gain %", "Écart %") and texte != "—":
                    options["fg_color"] = pr.COULEURS_SIGNAL[
                        pr.Signal.POSITIF if valeur >= 0 else pr.Signal.NEGATIF
                    ]
                    options["text_color"] = "white"
                    options["corner_radius"] = 4
                    texte = f"{valeur:+.2f}"
                elif nom in ("Gain", "Marché %") and texte != "—":
                    options["text_color"] = pr.COULEURS_SIGNAL[
                        pr.Signal.POSITIF if valeur >= 0 else pr.Signal.NEGATIF
                    ]
                    texte = f"{valeur:+.2f}"

                ctk.CTkLabel(cadre, text=texte, width=largeur, anchor=alignement, **options).grid(
                    row=ligne, column=colonne, padx=2, pady=1, sticky="ew"
                )

    def _tableau_trades(self, resultats, combien: int = 12):
        """Les derniers allers-retours, pour vérifier ce qui s'est réellement passé."""
        trades = mod_simulation.Simulateur.tableau_trades(resultats)
        if trades.empty:
            return

        ctk.CTkLabel(
            self.zone_simu, text=f"DERNIERS ALLERS-RETOURS ({len(trades)} au total)",
            font=POLICE_PETITE, text_color="#7c8695", anchor="w",
        ).pack(fill="x", pady=(14, 4))

        cadre = ctk.CTkFrame(self.zone_simu, fg_color="transparent")
        cadre.pack(fill="x", pady=(0, 8))
        colonnes = ["Crypto", "Sens", "Score", "Entrée", "Sortie", "Motif",
                    "Rendement net %"]
        largeurs = [85, 105, 65, 135, 135, 100, 115]

        for colonne, (nom, largeur) in enumerate(zip(colonnes, largeurs)):
            ctk.CTkLabel(
                cadre, text=nom, font=POLICE_PETITE, text_color="#9aa0a6", width=largeur
            ).grid(row=0, column=colonne, padx=2, pady=(0, 3), sticky="ew")

        for ligne, (_, trade) in enumerate(trades.head(combien).iterrows(), start=1):
            valeurs = [
                trade["Crypto"], trade["Sens"], f"{trade['Score']:+.2f}",
                f"{trade['Entrée']:%d/%m/%y %H:%M}", f"{trade['Sortie']:%d/%m/%y %H:%M}",
                trade["Motif"], f"{trade['Rendement net %']:+.2f} %",
            ]
            for colonne, (valeur, largeur) in enumerate(zip(valeurs, largeurs)):
                options = {}
                if colonne == 6:
                    options["text_color"] = pr.COULEURS_SIGNAL[
                        pr.Signal.POSITIF if trade["Rendement net %"] >= 0 else pr.Signal.NEGATIF
                    ]
                ctk.CTkLabel(
                    cadre, text=valeur, font=POLICE_PETITE, width=largeur, **options,
                ).grid(row=ligne, column=colonne, padx=2, pady=1, sticky="ew")

    # -- Actions ------------------------------------------------------------
    def _ouvrir_classeur(self):
        """Ouvre le classeur Excel avec l'application par défaut du système."""
        chemin = os.path.abspath(self.journal.chemin)
        if not os.path.exists(chemin):
            self.etiquette_resume.configure(text="Le classeur n'existe pas encore.")
            return
        try:
            if sys.platform == "win32":
                os.startfile(chemin)
            else:
                subprocess.Popen(["xdg-open", chemin])
        except OSError as e:
            self.etiquette_resume.configure(text=f"Ouverture impossible : {e}")
