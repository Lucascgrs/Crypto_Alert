"""
Démonstration en ligne de commande.

    python main.py                 # Top 10, tous les indicateurs
    python main.py 20              # Top 20
    python main.py 5 RSI BOLLINGER MACD    # Top 5, sélection d'indicateurs

Ce fichier ne sert qu'à vérifier le moteur : l'interface graphique viendra
consommer les mêmes objets (AnalyseurMarche + tableaux pandas).
"""

from __future__ import annotations

import sys

import pandas as pd

import suivi
from indicateurs import APPROCHE_DEFAUT, catalogue
from moteur import AnalyseurMarche

# La console Windows n'est pas toujours en UTF-8 : on force l'encodage pour
# que les accents et les symboles s'affichent correctement.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass


def afficher_catalogue():
    """
    Liste les indicateurs disponibles (ce que l'UI proposera à cocher).

    Groupés d'abord par APPROCHE : les deux jeux ne se mélangent jamais dans
    un score, les afficher mêlés laisserait croire le contraire.
    """
    print("=" * 78)
    print("INDICATEURS DISPONIBLES")
    print("=" * 78)
    fiche = catalogue()
    for approche, jeu in fiche.groupby("approche", sort=False):
        defaut = " (sélection par défaut)" if approche == APPROCHE_DEFAUT.value else ""
        print(f"\n--- Approche {approche} : {len(jeu)} indicateurs{defaut} ---")
        for categorie, groupe in jeu.groupby("categorie", sort=False):
            print(f"\n[{categorie}]")
            for _, ligne in groupe.iterrows():
                print(f"  {ligne['code']:<16} {ligne['nom']}")
    print(f"\nTotal : {len(fiche)} indicateurs.\n")


def afficher_detail(resultat):
    """Affiche tous les critères qualitatifs d'une crypto, groupés par indicateur."""
    print("=" * 78)
    entete = f"DÉTAIL — {resultat.symbole} ({resultat.nom})"
    if resultat.prix:
        entete += f" — {resultat.prix:,.2f} $"
    print(entete)
    print(f"Score global : {resultat.score_global:+.2f}  ->  {resultat.synthese}")
    print("=" * 78)

    categorie_courante = None
    for indicateur in resultat.resultats.values():
        if indicateur.categorie.value != categorie_courante:
            categorie_courante = indicateur.categorie.value
            print(f"\n--- {categorie_courante.upper()} ---")

        if indicateur.erreur:
            print(f"\n  {indicateur.nom} : {indicateur.erreur}")
            continue

        print(f"\n  {indicateur.nom}  [{indicateur.synthese}, {indicateur.score:+.2f}]")
        for critere in indicateur.criteres:
            marque = critere.signal.symbole if critere.directionnel else "·"
            chiffre = "" if critere.valeur_num is None else f"  ({critere.valeur_num:,.4g})"
            print(f"    {marque:>2}  {critere.libelle} : {critere.valeur}{chiffre}")


def main():
    arguments = sys.argv[1:]
    nombre = int(arguments[0]) if arguments and arguments[0].isdigit() else 10
    codes = [a.upper() for a in arguments[1:]] or None

    afficher_catalogue()

    analyseur = AnalyseurMarche(codes=codes)
    resultats = analyseur.analyser_top(nombre)

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 40)

    print("\n" + "=" * 78)
    print("CLASSEMENT PAR SCORE TECHNIQUE")
    print("=" * 78)
    print(analyseur.classement(resultats).to_string(index=False))

    print("\n" + "=" * 78)
    print("SYNTHÈSE PAR INDICATEUR")
    print("=" * 78)
    synthese = analyseur.tableau_synthese(resultats)
    colonnes = ["Symbole", "Score", "Synthèse", "Tendance", "Momentum", "Volatilité", "Volume"]
    print(synthese[colonnes].to_string(index=False))

    # Détail complet de la première crypto exploitable.
    for resultat in resultats:
        if resultat.indicateurs_valides:
            print()
            afficher_detail(resultat)
            break

    criteres = analyseur.tableau_criteres(resultats)
    print(f"\n\n{len(criteres)} critères qualitatifs produits au total "
          f"({len(resultats)} cryptos x {len(analyseur.indicateurs)} indicateurs).")

    # Suivi : chaque exécution alimente le classeur, et vérifie au passage les
    # relevés précédents dont l'échéance est atteinte.
    journal = suivi.JournalSuivi()
    ajoutes = journal.enregistrer(resultats, analyseur.intervalle, codes, origine="cli")
    bilan = journal.verifier(historiques=analyseur.historiques, source=analyseur.source)
    ok, detail = journal.sauvegarder()
    print(f"\n{ajoutes} relevés ajoutés, {bilan['verifies']} vérifiés, "
          f"{bilan['en_attente']} en attente d'échéance.")
    print(detail)

    performance = journal.performance()
    if not performance.empty:
        print("\n" + "=" * 78)
        print("SUIVI DES PERFORMANCES")
        print("=" * 78)
        print(performance.to_string(index=False))


if __name__ == "__main__":
    main()
