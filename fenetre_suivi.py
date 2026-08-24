"""
Fenêtre de suivi des performances.

Affiche le contenu de l'onglet « Performance » du classeur de suivi : les scores
produits par l'application se vérifient-ils dans les faits ?

La lecture se fait de haut en bas :
  - le bilan global ;
  - le détail par tranche de score, qui répond à la vraie question — un score
    élevé prédit-il mieux qu'un score faible ?
  - le détail par intervalle et par crypto.
"""

from __future__ import annotations

import os
import subprocess
import sys

import customtkinter as ctk

import presentation as pr

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
        self.geometry("1080x680")
        self.journal = journal

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
        self.etiquette_resume.pack(fill="x", padx=16)

        ctk.CTkLabel(
            self,
            text="Le taux de réussite ne compte que les cas tranchés : un score neutre "
                 "(« Non prédictif ») ou un marché immobile (« Indécis ») n'est ni une "
                 "réussite ni un échec.\nLe rendement relatif compare chaque crypto à la "
                 "moyenne de son lot d'analyse : c'est lui qui dit si le score apporte "
                 "vraiment quelque chose.",
            font=POLICE_PETITE, text_color="#7c8695", justify="left", anchor="w",
        ).pack(fill="x", padx=16, pady=(4, 8))

        self.zone = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.zone.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self._rafraichir()

    # -- Contenu ------------------------------------------------------------
    def _rafraichir(self):
        for enfant in self.zone.winfo_children():
            enfant.destroy()

        self.etiquette_resume.configure(text=self.journal.resume())
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
