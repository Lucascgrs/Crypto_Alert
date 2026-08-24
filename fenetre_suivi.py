"""
Fenêtre de suivi, en deux onglets.

« Performance » répond à la question de fond : les scores produits se
vérifient-ils dans les faits ? Bilan global, puis détail par tranche de score
— un score élevé prédit-il mieux qu'un score faible ? —, par intervalle et par
crypto.

« Évolution des scores » trace la trajectoire de chaque crypto dans le temps :
on choisit les cryptos, le type de score (global ou l'une des quatre familles)
et l'intervalle. Chaque analyse ajoute un point.
"""

from __future__ import annotations

import os
import subprocess
import sys

import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import graphiques
import presentation as pr
import suivi as mod_suivi

POLICE_TITRE = ("Segoe UI", 15, "bold")
POLICE_SOUS_TITRE = ("Segoe UI", 12, "bold")
POLICE_NORMALE = ("Segoe UI", 12)
POLICE_PETITE = ("Segoe UI", 11)

# Un taux de réussite se lit par rapport à 50 % (le pile ou face), pas par
# rapport à 0 : ces paliers colorent l'écart à cette référence.
PALIERS_TAUX = [
    (40, "#9b1c2e"),
    (48, "#d1495b"),
    (52, "#6b7280"),
    (60, "#2e8b57"),
    (101, "#157f3d"),
]


def couleur_taux(taux) -> str:
    """Couleur d'un taux de réussite en pourcentage."""
    if taux is None or taux != taux:  # None ou NaN
        return pr.COULEUR_INDISPONIBLE
    for borne, couleur in PALIERS_TAUX:
        if taux < borne:
            return couleur
    return PALIERS_TAUX[-1][1]


class FenetreSuivi(ctk.CTkToplevel):
    """Fenêtre de consultation, en lecture seule."""

    COLONNES = [
        ("Catégorie", 210, "w"),
        ("Vérifications", 90, "center"),
        ("Corrects", 80, "center"),
        ("Incorrects", 85, "center"),
        ("Indécis", 75, "center"),
        ("Taux de réussite %", 120, "center"),
        ("Rendement moyen %", 130, "center"),
        ("Rendement relatif moyen %", 165, "center"),
    ]

    def __init__(self, parent, journal):
        super().__init__(parent)
        self.title("Suivi des performances")
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

        ctk.CTkLabel(entete, text="Suivi des performances", font=POLICE_TITRE).pack(side="left")
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
        self.onglet_performance = onglets.add("Performance")
        self.onglet_evolution = onglets.add("Évolution des scores")

        self._construire_performance(self.onglet_performance)
        self._construire_evolution(self.onglet_evolution)

        self._rafraichir()

    def _construire_performance(self, parent):
        ctk.CTkLabel(
            parent,
            text="Le taux de réussite ne compte que les cas tranchés : un score neutre "
                 "(« Non prédictif ») ou un marché immobile (« Indécis ») n'est ni une "
                 "réussite ni un échec.\nLe rendement relatif compare chaque crypto à la "
                 "moyenne de son lot d'analyse : c'est lui qui dit si le score apporte "
                 "vraiment quelque chose.",
            font=POLICE_PETITE, text_color="#7c8695", justify="left", anchor="w",
        ).pack(fill="x", padx=4, pady=(4, 8))

        self.zone = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.zone.pack(fill="both", expand=True, pady=(0, 4))

    # -- Contenu ------------------------------------------------------------
    def _rafraichir(self):
        self.etiquette_resume.configure(text=self.journal.resume())
        self._rafraichir_performance()
        self._rafraichir_selection()
        self._tracer()

    def _rafraichir_performance(self):
        for enfant in self.zone.winfo_children():
            enfant.destroy()

        performance = self.journal.performance()

        if performance.empty:
            ctk.CTkLabel(
                self.zone,
                text="Aucune vérification pour l'instant.\n\n"
                     "Les relevés sont confrontés au marché lorsque leur échéance est "
                     "atteinte,\nc'est-à-dire quelques bougies après l'analyse qui les a "
                     "produits.\nRelancez une analyse après ce délai.",
                font=POLICE_NORMALE, text_color="#7c8695", justify="left",
            ).pack(pady=40)
            return

        ligne = 0
        for regroupement in ["Global", "Tranche de score", "Intervalle", "Crypto"]:
            sous = performance[performance["Regroupement"] == regroupement]
            if sous.empty:
                continue
            ligne = self._section(regroupement, sous, ligne)

    def _section(self, titre: str, table, ligne: int) -> int:
        """Un bloc de résultats précédé de son titre."""
        ctk.CTkLabel(
            self.zone, text=titre.upper(), font=POLICE_PETITE, text_color="#7c8695"
        ).grid(row=ligne, column=0, sticky="w", pady=(14, 4))
        ligne += 1

        for colonne, (nom, largeur, _) in enumerate(self.COLONNES):
            ctk.CTkLabel(
                self.zone, text=nom, font=POLICE_PETITE, text_color="#9aa0a6", width=largeur
            ).grid(row=ligne, column=colonne, padx=2, pady=(0, 4), sticky="ew")
        ligne += 1

        for _, enregistrement in table.iterrows():
            self._ligne(enregistrement, ligne)
            ligne += 1
        return ligne

    def _ligne(self, enregistrement, ligne: int):
        valeurs = [
            enregistrement["Catégorie"],
            enregistrement["Vérifications"],
            enregistrement["Corrects"],
            enregistrement["Incorrects"],
            enregistrement["Indécis"],
            enregistrement["Taux de réussite %"],
            enregistrement["Rendement moyen %"],
            enregistrement["Rendement relatif moyen %"],
        ]

        for colonne, ((_, largeur, alignement), valeur) in enumerate(zip(self.COLONNES, valeurs)):
            texte = "—" if valeur is None or valeur != valeur else str(valeur)
            options = {}

            if colonne == 5 and texte != "—":       # taux de réussite
                options = {
                    "fg_color": couleur_taux(valeur), "text_color": "white", "corner_radius": 4
                }
                texte = f"{valeur:.1f} %"
            elif colonne in (6, 7) and texte != "—":  # rendements
                options = {
                    "text_color": pr.COULEURS_SIGNAL[
                        pr.Signal.POSITIF if valeur >= 0 else pr.Signal.NEGATIF
                    ]
                }
                texte = f"{valeur:+.2f} %"

            ctk.CTkLabel(
                self.zone, text=texte, font=POLICE_NORMALE, width=largeur,
                anchor=alignement, **options,
            ).grid(row=ligne, column=colonne, padx=2, pady=1, sticky="ew")

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
