"""
Diagnostic : les scores prédisent-ils quoi que ce soit — et dans quel sens ?

Ce module ne simule pas une stratégie, il pose la question en amont : quand le
score vaut +0,50, que fait le prix ensuite ? Une simulation qui perd peut perdre
pour trois raisons très différentes, et seule la mesure directe les sépare :

  1. le score n'a AUCUNE information -> corrélation nulle, la perte vient des frais ;
  2. le score a une information INVERSÉE -> corrélation négative, il faut le retourner ;
  3. le score a de l'information mais les RÉGLAGES la gâchent -> corrélation
     positive alors que la simulation perd (seuils, durée, frais, sens).

On mesure donc, sur des milliers de barres :

  - la corrélation entre le score à la barre t et le rendement des H barres
    suivantes, globalement et par famille d'indicateurs ;
  - le rendement moyen par tranche de score : un score fort doit faire mieux
    qu'un score faible, sinon le score ne classe rien ;
  - la même chose indicateur par indicateur, pour identifier les coupables ;
  - le rendement RELATIF (écart à la moyenne des cryptos au même instant) :
    les cryptos montent et descendent ensemble, un score qui ne fait que suivre
    le marché n'apporte rien en propre.

Tout est mesuré DEUX FOIS, une par approche (cf. `indicateurs.Approche`) : les
20 indicateurs suiveurs d'un côté, les 7 indicateurs d'anticipation de l'autre,
sur exactement les mêmes barres. C'est cette comparaison qui dit si la seconde
approche apporte quelque chose, ou si elle se contente de décrire le passé
autrement.

Tout est écrit dans un classeur Excel, une feuille par question.

    python diagnostic.py
"""

from __future__ import annotations

import time

import pandas as pd

from donnees import SourceDonnees
from indicateurs import REGISTRE, Approche, Categorie, creer, periodes_requises
from moteur import ResultatCrypto

# --- Ce que l'on mesure -----------------------------------------------------
FICHIER = "diagnostic_scores.xlsx"

# Horizons de mesure, en bougies. 6 est l'horizon de vérification du projet
# (config.HORIZON_BOUGIES) ; les autres disent si l'information apparaît plus
# tôt ou plus tard.
HORIZONS = [1, 3, 6, 12, 24]

# Bornes des tranches de score, alignées sur le vocabulaire du tableau de bord.
TRANCHES = [-1.01, -0.45, -0.15, 0.15, 0.45, 1.01]
NOMS_TRANCHES = ["Fortement négatif", "Négatif", "Neutre", "Positif", "Fortement positif"]

# Les scores mesurés, sous la forme (approche, catégorie ou None pour le total).
#
# Les deux premiers sont les scores d'ENSEMBLE de chaque approche : ce sont eux
# que l'on compare, tout le reste sert à comprendre d'où vient l'écart. Les
# familles d'une approche ne sont détaillées que là où elles existent : côté
# anticipation, la seule « tendance » est l'efficience, qui est contextuelle et
# ne produit donc aucun score.
SCORES = {
    "Suiveurs": (Approche.SUIVEUSE, None),
    "Anticipation": (Approche.ANTICIPATION, None),
    "Suiveurs Tendance": (Approche.SUIVEUSE, Categorie.TENDANCE),
    "Suiveurs Momentum": (Approche.SUIVEUSE, Categorie.MOMENTUM),
    "Suiveurs Volatilité": (Approche.SUIVEUSE, Categorie.VOLATILITE),
    "Suiveurs Volume": (Approche.SUIVEUSE, Categorie.VOLUME),
    "Anticip. Momentum": (Approche.ANTICIPATION, Categorie.MOMENTUM),
    "Anticip. Volatilité": (Approche.ANTICIPATION, Categorie.VOLATILITE),
    "Anticip. Volume": (Approche.ANTICIPATION, Categorie.VOLUME),
}

# Les deux scores d'ensemble, ceux que l'on met face à face.
PRINCIPAUX = ["Suiveurs", "Anticipation"]


# ===========================================================================
# COLLECTE
# ===========================================================================
def observer(symbole: str, intervalle: str, periodes: int, source: SourceDonnees,
             indicateurs) -> pd.DataFrame:
    """
    Une ligne par barre : les scores à cet instant, et ce que le prix a fait après.

    Les scores sont calculés exactement comme dans le tableau de bord, avec les
    seules données disponibles à la barre (cf. `Indicateur.analyser_serie`).
    """
    echauffement = periodes_requises(indicateurs)
    horizon_max = max(HORIZONS)
    # Pas de plafond ici : `SourceDonnees._binance` pagine au-delà de 1000 bougies.
    nb_bougies = echauffement + periodes + horizon_max

    df = source.historique(symbole, intervalle, nb_bougies)
    if df is None or df.empty:
        return pd.DataFrame()

    derniere = len(df) - 1 - horizon_max
    premiere = max(echauffement - 1, derniere - periodes + 1)
    if derniere < premiere:
        return pd.DataFrame()

    positions = list(range(premiere, derniere + 1))
    par_indicateur = {
        indicateur.code: indicateur.analyser_serie(df, positions)
        for indicateur in indicateurs
    }
    cloture = df["Close"]

    lignes = []
    for position in positions:
        photo = ResultatCrypto(symbole=symbole)
        photo.resultats = {code: res[position] for code, res in par_indicateur.items()}
        if not photo.indicateurs_notes:
            continue

        ligne = {
            "symbole": symbole,
            "intervalle": intervalle,
            "horodatage": df.index[position],
        }
        for nom, (approche, categorie) in SCORES.items():
            ligne[nom] = (
                photo.score_approche(approche) if categorie is None
                else photo.score_categorie(categorie, approche)
            )
        # Score de chaque indicateur pris isolément : c'est ce qui permet de
        # désigner les coupables au lieu de condamner le score global en bloc.
        for code, resultat in photo.resultats.items():
            if not resultat.erreur and resultat.porte_une_direction:
                ligne["i_" + code] = resultat.score

        prix = float(cloture.iloc[position])
        for horizon in HORIZONS:
            futur = float(cloture.iloc[position + horizon])
            ligne["r" + str(horizon)] = 100 * (futur - prix) / prix
        lignes.append(ligne)

    return pd.DataFrame(lignes)


def collecter(symboles, intervalles, periodes: int, verbeux: bool = True) -> pd.DataFrame:
    """Assemble les observations de toutes les cryptos et de tous les intervalles."""
    source = SourceDonnees(verbeux=False)
    # Explicitement TOUT le registre : `creer(None)` ne donnerait que la
    # sélection par défaut, or on veut mesurer les deux approches d'un coup.
    indicateurs = creer(list(REGISTRE))

    morceaux = []
    for intervalle in intervalles:
        for symbole in symboles:
            debut = time.time()
            table = observer(symbole, intervalle, periodes, source, indicateurs)
            if verbeux:
                etat = f"{len(table)} barres" if len(table) else "aucune donnée"
                print(f"  {intervalle} {symbole:<6} : {etat} ({time.time() - debut:.1f}s)")
            if not table.empty:
                morceaux.append(table)

    if not morceaux:
        return pd.DataFrame()
    table = pd.concat(morceaux, ignore_index=True)

    # Rendement RELATIF : écart à la moyenne des cryptos observées au même
    # instant. Sans lui, un score qui ne fait que suivre le marché paraîtrait
    # informatif alors qu'il ne classe rien.
    for horizon in HORIZONS:
        colonne = f"r{horizon}"
        moyenne = table.groupby(["intervalle", "horodatage"])[colonne].transform("mean")
        table[f"rel{horizon}"] = table[colonne] - moyenne
    return table


# ===========================================================================
# ANALYSES
# ===========================================================================
def correlations(table: pd.DataFrame) -> pd.DataFrame:
    """
    Corrélation entre chaque score et le rendement futur, par intervalle.

    La corrélation de RANG (Spearman) est la mesure de référence ici : elle ne
    demande pas que la relation soit linéaire, seulement que « plus le score est
    haut, plus le rendement l'est ». C'est exactement la promesse d'un score.
    """
    lignes = []
    for intervalle, groupe in table.groupby("intervalle"):
        for score in SCORES:
            for horizon in HORIZONS:
                for etiquette, prefixe in [("absolu", "r"), ("relatif", "rel")]:
                    paire = groupe[[score, f"{prefixe}{horizon}"]].dropna()
                    if len(paire) < 50:
                        continue
                    lignes.append({
                        "Intervalle": intervalle,
                        "Score": score,
                        "Horizon (bougies)": horizon,
                        "Rendement": etiquette,
                        "Observations": len(paire),
                        "Spearman": round(paire.corr(method="spearman").iloc[0, 1], 4),
                        "Pearson": round(paire.corr(method="pearson").iloc[0, 1], 4),
                    })
    return pd.DataFrame(lignes)


def par_tranche(table: pd.DataFrame, score: str = "Suiveurs") -> pd.DataFrame:
    """
    Rendement moyen par tranche de score.

    C'est le test décisif, et le plus lisible : si « Fortement positif » rapporte
    moins que « Fortement négatif », le score est inversé. Si toutes les tranches
    rapportent la même chose, il ne dit rien.
    """
    lignes = []
    for intervalle, groupe in table.groupby("intervalle"):
        tranches = pd.cut(groupe[score], bins=TRANCHES, labels=NOMS_TRANCHES)
        for nom in NOMS_TRANCHES:
            sous = groupe[tranches == nom]
            if sous.empty:
                continue
            ligne = {
                "Intervalle": intervalle,
                "Tranche": nom,
                "Observations": len(sous),
                "Part %": round(100 * len(sous) / len(groupe), 1),
            }
            for horizon in HORIZONS:
                ligne[f"Rendement {horizon}b %"] = round(sous[f"r{horizon}"].mean(), 3)
            for horizon in HORIZONS:
                ligne[f"Relatif {horizon}b %"] = round(sous[f"rel{horizon}"].mean(), 3)
            # Part des cas où le prix est monté : une lecture qui ne dépend pas
            # de quelques mouvements extrêmes.
            ligne["Hausses %"] = round(100 * (sous["r6"] > 0).mean(), 1)
            lignes.append(ligne)
    return pd.DataFrame(lignes)


def passe_vs_futur(table: pd.DataFrame) -> pd.DataFrame:
    """
    La mesure décisive : le score décrit-il le passé, ou annonce-t-il l'avenir ?

    Pour chaque horizon H on compare deux corrélations :

      - avec le rendement des H bougies **précédentes** : à quel point le score
        est un thermomètre de ce qui vient de se passer ;
      - avec le rendement des H bougies **suivantes** : à quel point il annonce
        ce qui va se passer.

    Un indicateur technique est par construction une fonction du passé. La
    question n'est donc pas s'il regarde en arrière — il ne peut faire que ça —
    mais si ce regard en arrière contient quelque chose sur la suite. L'écart
    entre les deux colonnes est la réponse.
    """
    table = table.sort_values(["symbole", "intervalle", "horodatage"])
    lignes = []
    for intervalle, groupe in table.groupby("intervalle"):
        for score in PRINCIPAUX:
            for horizon in HORIZONS:
                colonne = f"r{horizon}"
                # Le rendement des H bougies precedentes, c'est le rendement futur
                # decale de H barres vers l'avant.
                passe = groupe.groupby("symbole")[colonne].shift(horizon)
                avant = pd.concat([groupe[score], passe], axis=1).dropna()
                apres = groupe[[score, colonne]].dropna()
                relatif = groupe[[score, f"rel{horizon}"]].dropna()
                if len(avant) < 50 or len(apres) < 50:
                    continue
                lignes.append({
                    "Intervalle": intervalle,
                    "Approche": score,
                    "Horizon (bougies)": horizon,
                    "Corrélation au PASSÉ": round(
                        avant.corr(method="spearman").iloc[0, 1], 3),
                    "Corrélation au FUTUR": round(
                        apres.corr(method="spearman").iloc[0, 1], 3),
                    "Corrélation au FUTUR relatif": round(
                        relatif.corr(method="spearman").iloc[0, 1], 3),
                    "Observations": len(apres),
                })
    return pd.DataFrame(lignes)


def par_regime(table: pd.DataFrame, score: str = "Suiveurs", horizon: int = 6,
               seuil: float = 0.30) -> pd.DataFrame:
    """
    Le score marche-t-il mieux selon que le marché monte ou descend ?

    Un suiveur de tendance est censé briller en tendance et se faire hacher dans
    le plat. On coupe donc les observations en deux régimes — marché globalement
    haussier ou baissier sur les 24 bougies écoulées — et on compare ce que
    rapportent les scores forts et les scores faibles dans chacun.

    Surveiller la colonne « Observations » : plusieurs cases reposent sur
    quelques dizaines de barres qui se recouvrent, ce qui ne prouve rien.
    """
    table = table.sort_values(["symbole", "intervalle", "horodatage"])
    passe = table.groupby(["symbole", "intervalle"])["r24"].shift(24)
    table = table.assign(passe24=passe).dropna(subset=["passe24"])
    moyenne = table.groupby(["intervalle", "horodatage"])["passe24"].transform("mean")
    table = table.assign(
        regime=pd.Series(moyenne > 0, index=table.index).map(
            {True: "Marché haussier", False: "Marché baissier"})
    )

    lignes = []
    for (intervalle, regime), groupe in table.groupby(["intervalle", "regime"]):
        haut = groupe[groupe[score] >= seuil]
        bas = groupe[groupe[score] <= -seuil]
        if len(haut) < 40 or len(bas) < 40:
            continue
        lignes.append({
            "Intervalle": intervalle,
            "Approche": score,
            "Régime": regime,
            "Score fort : rendement %": round(haut[f"r{horizon}"].mean(), 3),
            "Score faible : rendement %": round(bas[f"r{horizon}"].mean(), 3),
            "Écart %": round(haut[f"r{horizon}"].mean() - bas[f"r{horizon}"].mean(), 3),
            "Écart relatif %": round(
                haut[f"rel{horizon}"].mean() - bas[f"rel{horizon}"].mean(), 3),
            "Observations fortes": len(haut),
            "Observations faibles": len(bas),
        })
    return pd.DataFrame(lignes)


def par_indicateur(table: pd.DataFrame, horizon: int = 6) -> pd.DataFrame:
    """
    Corrélation de chaque indicateur pris isolément avec le rendement futur.

    Un score global médiocre peut cacher deux moitiés qui s'annulent : des
    indicateurs utiles et des indicateurs franchement contre-productifs.

    La colonne « Spearman passé » est le contrôle de construction du module
    `anticipation.py` : un indicateur d'anticipation qui afficherait +0,80 au
    passé comme un Supertrend ne serait qu'un suiveur déguisé, quel que soit le
    nom qu'on lui donne.
    """
    table = table.sort_values(["symbole", "intervalle", "horodatage"])
    codes = [c for c in table.columns if c.startswith("i_")]
    lignes = []
    for intervalle, groupe in table.groupby("intervalle"):
        futur = groupe[f"r{horizon}"]
        passe = groupe.groupby("symbole")[f"r{horizon}"].shift(horizon)
        for code in codes:
            paire = pd.concat([groupe[code], futur], axis=1).dropna()
            relatif = groupe[[code, f"rel{horizon}"]].dropna()
            avant = pd.concat([groupe[code], passe], axis=1).dropna()
            if len(paire) < 50 or len(avant) < 50:
                continue
            classe = REGISTRE.get(code[2:])
            lignes.append({
                "Intervalle": intervalle,
                "Indicateur": code[2:],
                "Approche": "" if classe is None else classe.approche.value,
                "Observations": len(paire),
                "Spearman passé": round(avant.corr(method="spearman").iloc[0, 1], 4),
                "Spearman absolu": round(paire.corr(method="spearman").iloc[0, 1], 4),
                "Spearman relatif": round(relatif.corr(method="spearman").iloc[0, 1], 4),
                "Score moyen": round(paire[code].mean(), 3),
            })
    resultat = pd.DataFrame(lignes)
    if resultat.empty:
        return resultat
    return resultat.sort_values(
        ["Intervalle", "Spearman relatif"], ascending=[True, False]
    ).reset_index(drop=True)


def _rejouer(groupe: pd.DataFrame, score: str, seuil: float, duree: int,
             achat: bool, frais_pct: float) -> tuple[int, int, float]:
    """
    Rejoue la même règle que `simulation.py` sur une crypto déjà observée.

    Renvoie `(trades, gagnants, rendement composé en %)`.

    On travaille sur les observations déjà calculées plutôt que de relancer le
    simulateur : celui-ci recalculerait les scores pour CHAQUE case de la
    grille, soit 162 fois les mêmes indicateurs. Les règles reproduites sont les
    mêmes — entrée à la clôture, sortie `duree` bougies plus tard, aucun
    chevauchement, frais à l'entrée et à la sortie.
    """
    valeurs = groupe[score].to_numpy()
    rendements = groupe[f"r{duree}"].to_numpy()
    frais = frais_pct / 100

    capital, trades, gagnants, libre = 1.0, 0, 0, 0
    for rang in range(len(valeurs)):
        if rang < libre:
            continue
        score_barre = valeurs[rang]
        if score_barre != score_barre or abs(score_barre) < seuil:
            continue
        if (score_barre > 0) != achat:
            continue
        # Le rendement stocké est celui du prix ; à découvert on gagne l'inverse.
        brut = rendements[rang] / 100
        net = (brut if achat else -brut) - 2 * frais
        capital *= 1 + net
        trades += 1
        gagnants += net > 0
        libre = rang + duree + 1
    return trades, gagnants, 100 * (capital - 1)


def grille(table: pd.DataFrame, frais_pct: float = 0.10) -> pd.DataFrame:
    """
    Un résultat par jeu de réglages : le même signal, monté à l'endroit puis à
    l'envers, avec des seuils et des durées différentes.

    Si le sens « vente » gagne systématiquement là où « achat » perd, le score
    porte de l'information, simplement retournée. Si les deux perdent, il n'y a
    pas d'information à retourner.
    """
    lignes = []
    for intervalle, bloc in table.groupby("intervalle"):
        # Référence : ce qu'aurait rapporté un simple achat-conservation.
        marche = bloc.groupby("symbole").apply(
            lambda g: g["r1"].mean() * len(g), include_groups=False
        ).mean()

        for score in SCORES:
            if score not in bloc.columns or bloc[score].notna().sum() < 50:
                continue
            for seuil in [0.15, 0.30, 0.45]:
                for duree in [3, 6, 12]:
                    for achat in [True, False]:
                        totaux = [
                            _rejouer(groupe.sort_values("horodatage"), score,
                                     seuil, duree, achat, frais_pct)
                            for _, groupe in bloc.groupby("symbole")
                        ]
                        trades = sum(t for t, _, _ in totaux)
                        if not trades:
                            continue
                        gagnants = sum(g for _, g, _ in totaux)
                        gain = sum(r for _, _, r in totaux) / len(totaux)
                        classe = SCORES[score][0]
                        lignes.append({
                            "Intervalle": intervalle,
                            "Approche": classe.value,
                            "Score": score,
                            "Seuil min": seuil,
                            "Détention": duree,
                            "Sens": "Achat" if achat else "Vente",
                            "Trades": trades,
                            "Réussite %": round(100 * gagnants / trades, 1),
                            "Gain %": round(gain, 2),
                            "Marché %": round(marche, 2),
                            "Écart %": round(gain - marche, 2),
                        })
    return pd.DataFrame(lignes)


# ===========================================================================
# EXPORT
# ===========================================================================
def lecture() -> pd.DataFrame:
    """Feuille d'explication, pour que le classeur se lise sans ce fichier source."""
    return pd.DataFrame([
        {"Question": "Le score décrit-il le passé ou l'avenir ?",
         "Où regarder": "Passé vs futur",
         "Comment lire": "LA feuille décisive. Corrélation au passé élevée et "
                         "corrélation au futur nulle : le score est un "
                         "thermomètre de ce qui vient de se passer, pas une "
                         "prévision. C'est le cas des suiveurs (environ +0,80 "
                         "contre 0,00)."},
        {"Question": "L'approche anticipation change-t-elle quelque chose ?",
         "Où regarder": "Passé vs futur, colonne Approche",
         "Comment lire": "Deux lectures, dans cet ordre. 1) La corrélation au "
                         "PASSÉ de l'anticipation doit être proche de zéro : "
                         "sinon elle n'est qu'un suiveur déguisé et le reste ne "
                         "vaut rien. 2) Seulement ensuite, sa corrélation au "
                         "FUTUR relatif : c'est là, et nulle part ailleurs, que "
                         "se verrait un vrai gain."},
        {"Question": "Un indicateur d'anticipation en est-il vraiment un ?",
         "Où regarder": "Par indicateur, colonne Spearman passé",
         "Comment lire": "Contrôle de construction. Un indicateur étiqueté "
                         "Anticipation dont le Spearman passé dépasse 0,40 en "
                         "valeur absolue est mal classé : il redécrit le "
                         "mouvement au lieu de chercher ce qui le retournerait."},
        {"Question": "Le score est-il inversé ?",
         "Où regarder": "Corrélations / Par tranche",
         "Comment lire": "Spearman nettement négatif, ou « Fortement positif » qui "
                         "rapporte moins que « Fortement négatif » : le score dit "
                         "l'inverse de ce qui se passe. Il faut que ce soit vrai "
                         "sur PLUSIEURS intervalles : un seul, c'est du hasard."},
        {"Question": "Le score marche-t-il selon le régime ?",
         "Où regarder": "Par régime",
         "Comment lire": "Un suiveur de tendance devrait briller en tendance. Si "
                         "les écarts changent de signe d'un intervalle à l'autre, "
                         "il n'y a pas d'effet de régime, seulement du bruit. "
                         "Vérifier la colonne Observations."},
        {"Question": "Le score dit-il quelque chose ?",
         "Où regarder": "Corrélations",
         "Comment lire": "Spearman entre -0,03 et +0,03 : le score et le rendement "
                         "futur sont indépendants. Ce n'est pas une inversion, "
                         "c'est une absence d'information."},
        {"Question": "Quels indicateurs nuisent ?",
         "Où regarder": "Par indicateur",
         "Comment lire": "Trié par corrélation relative. Le haut du tableau aide, "
                         "le bas nuit. Un indicateur négatif sur plusieurs "
                         "intervalles est un vrai coupable."},
        {"Question": "Est-ce un problème de réglages ?",
         "Où regarder": "Grille de simulation",
         "Comment lire": "Si « Vente » gagne partout où « Achat » perd, le signal "
                         "est retourné. Si les deux perdent, ce sont les frais ou "
                         "l'absence d'information."},
        {"Question": "Pourquoi « relatif » ?",
         "Où regarder": "toutes les feuilles",
         "Comment lire": "Les cryptos montent et descendent ensemble. Le rendement "
                         "absolu récompense un score qui suit simplement le marché. "
                         "Le relatif mesure ce que le score apporte en propre."},
        {"Question": "Combien d'observations faut-il ?",
         "Où regarder": "colonne Observations",
         "Comment lire": "Les barres successives d'une même crypto se ressemblent : "
                         "1000 barres ne sont pas 1000 observations indépendantes. "
                         "Une corrélation sous 0,05 en valeur absolue ne prouve rien."},
    ])


def exporter(chemin: str, feuilles: dict) -> None:
    """Écrit chaque tableau dans sa feuille, en sautant les tableaux vides."""
    with pd.ExcelWriter(chemin, engine="openpyxl") as writer:
        for nom, table in feuilles.items():
            if table is None or table.empty:
                continue
            table.to_excel(writer, sheet_name=nom[:31], index=False)
    print(f"Écrit : {chemin}")


# ===========================================================================
# EXÉCUTION
# ===========================================================================
def main(symboles=None, intervalles=("1d", "4h", "1h"), periodes: int = 250):
    symboles = list(symboles or ["BTC", "ETH", "BNB", "XRP", "SOL", "ADA",
                                 "DOGE", "TRX", "LINK", "AVAX", "DOT", "LTC"])
    print(f"Collecte : {len(symboles)} cryptos x {len(intervalles)} intervalles "
          f"x {periodes} barres")
    table = collecter(symboles, intervalles, periodes)
    if table.empty:
        print("Aucune observation collectée.")
        return

    print(f"\n{len(table)} observations.")
    resultats_grille = grille(table)
    print(f"{len(resultats_grille)} jeux de réglages rejoués.\n")

    exporter(FICHIER, {
        "Lecture": lecture(),
        "Passé vs futur": passe_vs_futur(table),
        "Corrélations": correlations(table),
        "Par régime": pd.concat(
            [par_regime(table, score) for score in PRINCIPAUX], ignore_index=True
        ),
        "Par tranche (Suiveurs)": par_tranche(table, "Suiveurs"),
        "Par tranche (Anticipation)": par_tranche(table, "Anticipation"),
        "Par tranche (Anticip. Mom.)": par_tranche(table, "Anticip. Momentum"),
        "Par indicateur": par_indicateur(table),
        "Grille de simulation": resultats_grille,
        "Observations": table,
    })


if __name__ == "__main__":
    main()
