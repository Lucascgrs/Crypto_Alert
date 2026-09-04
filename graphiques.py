"""
Graphiques d'évolution des scores.

Une seule fonction publique, `figure_evolution`, partagée par les deux
interfaces : le graphique doit être identique au bureau et sur le web.

Choix de forme : les données décrivent une ÉVOLUTION DANS LE TEMPS de plusieurs
entités comparables — c'est une courbe multi-séries, sur un axe unique (tous les
scores partagent la même échelle [-1, 1], il n'y a donc jamais de second axe).

La couleur encode une IDENTITÉ (quelle crypto), pas une magnitude : palette
catégorielle à emplacements fixes, définie et validée dans `presentation.py`.

On construit un objet `Figure` sans passer par pyplot : cela évite tout état
global et rend le module utilisable aussi bien embarqué dans Tkinter que rendu
en image par Streamlit.
"""

from __future__ import annotations

import matplotlib.dates as mdates
from matplotlib.figure import Figure

import config
import presentation as pr

# Épaisseurs et tailles, en points matplotlib (1 pt = 1/72 pouce).
# Traits fins, marqueurs discrets : un graphique de tableau de bord doit
# respirer, pas crier.
EPAISSEUR_COURBE = 2.0
TAILLE_MARQUEUR = 6.0
EPAISSEUR_GRILLE = 0.6


def figure_evolution(table, type_score: str = "Global", attribution=None,
                     mode: str = "sombre", intervalle: str = "",
                     largeur: float = 11.0, hauteur: float = 5.2) -> Figure:
    """
    Trace l'évolution d'un score pour plusieurs cryptos.

    table       : DataFrame indexé par horodatage, une colonne par crypto
                  (tel que renvoyé par JournalSuivi.evolution).
    attribution : presentation.AttributionCouleurs, pour que chaque crypto
                  garde sa couleur quand la sélection change.
    """
    attribution = attribution or pr.AttributionCouleurs(mode)
    surface = pr.SURFACES[mode]
    encre = pr.ENCRES[mode]

    figure = Figure(figsize=(largeur, hauteur), dpi=100, facecolor=surface)
    axes = figure.add_subplot(111, facecolor=surface)

    if table is None or table.empty:
        axes.text(
            0.5, 0.5,
            "Aucun relevé pour cette sélection.\n"
            "Lancez une analyse : chaque exécution ajoute un point.",
            ha="center", va="center", color=encre["secondaire"], fontsize=11,
        )
        _depouiller(axes, encre)
        return figure

    _fond(axes, encre)

    colonnes = list(table.columns)[: pr.MAX_SERIES]
    # Étiquetage direct au bout des courbes tant qu'elles sont peu nombreuses :
    # au-delà, les étiquettes se chevauchent et la légende suffit.
    etiqueter = len(colonnes) <= 4

    fins = []
    for symbole in colonnes:
        serie = table[symbole].dropna()
        if serie.empty:
            continue
        axes.plot(
            serie.index, serie.values,
            color=attribution.couleur(symbole), linewidth=EPAISSEUR_COURBE, label=symbole,
            marker="o", markersize=TAILLE_MARQUEUR,
            # Anneau de la couleur du fond : sépare les marqueurs qui se
            # superposent sans dessiner de contour sombre autour d'eux.
            markeredgecolor=surface, markeredgewidth=1.5,
            solid_capstyle="round", zorder=3,
        )
        fins.append((serie.index[-1], float(serie.values[-1]), symbole))

    if etiqueter:
        _etiqueter_fins(axes, fins, encre)

    _axes(axes, table, encre, type_score, intervalle)

    # Légende dès deux séries : l'identité ne doit jamais reposer sur la seule
    # couleur. Une série unique est déjà nommée par le titre.
    if len(colonnes) >= 2:
        legende = axes.legend(
            loc="upper left", bbox_to_anchor=(1.01, 1.0), frameon=False,
            fontsize=9, labelcolor=encre["secondaire"], handlelength=1.6,
        )
        for texte in legende.get_texts():
            texte.set_color(encre["secondaire"])

    figure.tight_layout()
    return figure


def figure_capital(table, attribution=None, mode: str = "sombre",
                   largeur: float = 11.0, hauteur: float = 4.6) -> Figure:
    """
    Courbes de capital d'une simulation, en pourcentage du capital de départ.

    Même forme et même palette que l'évolution des scores : ce sont deux
    trajectoires dans le temps, et une crypto garde sa couleur d'un graphique à
    l'autre. Seule l'échelle diffère — elle s'ajuste ici, un gain n'ayant pas de
    borne naturelle, contrairement à un score.
    """
    attribution = attribution or pr.AttributionCouleurs(mode)
    surface = pr.SURFACES[mode]
    encre = pr.ENCRES[mode]

    figure = Figure(figsize=(largeur, hauteur), dpi=100, facecolor=surface)
    axes = figure.add_subplot(111, facecolor=surface)

    if table is None or table.empty:
        axes.text(
            0.5, 0.5, "Aucun trade déclenché avec ces paramètres.",
            ha="center", va="center", color=encre["secondaire"], fontsize=11,
        )
        _depouiller(axes, encre)
        return figure

    # Le zéro sépare le gain de la perte : c'est le repère qui compte ici.
    axes.axhline(0, color=encre["discrete"], linewidth=0.9, zorder=1)

    colonnes = list(table.columns)[: pr.MAX_SERIES]
    fins = []
    for symbole in colonnes:
        serie = table[symbole].dropna()
        if serie.empty:
            continue
        axes.step(
            serie.index, serie.values, where="post",
            color=attribution.couleur(symbole), linewidth=EPAISSEUR_COURBE,
            label=symbole, solid_capstyle="round", zorder=3,
        )
        fins.append((serie.index[-1], float(serie.values[-1]), symbole))

    if len(colonnes) <= 4:
        amplitude = float(table.max().max() - table.min().min())
        _etiqueter_fins(axes, fins, encre, ecart=max(1.0, 0.06 * amplitude))

    axes.set_title(
        "Capital simulé", color=encre["primaire"], fontsize=13,
        fontweight="bold", loc="left", pad=12,
    )
    axes.set_ylabel("Gain / perte (%)", color=encre["secondaire"], fontsize=10)

    # L'axe reçoit déjà de l'heure de Paris (Simulateur.courbes convertit
    # avant de renvoyer) : l'étiquette le dit, pour ne jamais laisser deviner.
    localisateur = mdates.AutoDateLocator(minticks=3, maxticks=8)
    axes.xaxis.set_major_locator(localisateur)
    axes.xaxis.set_major_formatter(mdates.ConciseDateFormatter(localisateur))
    axes.set_xlabel("Heure (FR)", color=encre["secondaire"], fontsize=9)
    _depouiller(axes, encre)

    if len(colonnes) >= 2:
        legende = axes.legend(
            loc="upper left", bbox_to_anchor=(1.01, 1.0), frameon=False,
            fontsize=9, handlelength=1.6,
        )
        for texte in legende.get_texts():
            texte.set_color(encre["secondaire"])

    figure.tight_layout()
    return figure


# ===========================================================================
# HABILLAGE
# ===========================================================================
def _fond(axes, encre):
    """
    Repères de lecture : le zéro, et la bande à l'intérieur de laquelle
    l'application n'annonce aucune direction.

    La bande n'est pas légendée dans le tracé : une étiquette posée là se fait
    systématiquement traverser par une courbe. L'explication figure dans les
    deux interfaces, sous le graphique, où elle est réellement lue.
    """
    seuil = config.SEUIL_PREDICTION
    axes.axhspan(-seuil, seuil, color=encre["grille"], alpha=0.55, zorder=0)
    axes.axhline(0, color=encre["discrete"], linewidth=0.9, zorder=1)


# Écart vertical minimal entre deux étiquettes de fin, en unités de l'axe.
# Les scores vivent dans [-1, 1] : un écart fixe convient. Le capital n'a pas
# d'amplitude bornée, son écart est donc calculé à partir des données.
ECART_ETIQUETTES_SCORE = 0.10


def _etiqueter_fins(axes, fins, encre, ecart: float = ECART_ETIQUETTES_SCORE):
    """
    Étiquettes au bout des courbes, écartées si elles se chevauchent.

    Deux cryptos finissant à des scores voisins (−0,66 et −0,69) verraient leurs
    étiquettes se superposer : on repousse la suivante d'un écart minimal. Le
    léger décalage vis-à-vis du point réel se lit sans ambiguïté, le marqueur
    coloré restant à sa place.

    Le texte porte une couleur de TEXTE, jamais celle de la série : c'est le
    marqueur coloré immédiatement à sa gauche qui porte l'identité.
    """
    if not fins:
        return

    ordonnees = sorted(fins, key=lambda fin: -fin[1])   # du plus haut au plus bas
    positions = [fin[1] for fin in ordonnees]
    for rang in range(1, len(positions)):
        if positions[rang - 1] - positions[rang] < ecart:
            positions[rang] = positions[rang - 1] - ecart

    for (abscisse, _, symbole), ordonnee in zip(ordonnees, positions):
        axes.annotate(
            f" {symbole}",
            xy=(abscisse, ordonnee),
            xytext=(6, 0), textcoords="offset points",
            va="center", ha="left", fontsize=9,
            color=encre["primaire"], zorder=4,
        )


def _axes(axes, table, encre, type_score: str, intervalle: str):
    """Titre, échelles, grille et graduations."""
    titre = f"Évolution du score {type_score.lower()}"
    if intervalle:
        titre += f" — bougies {intervalle}"
    axes.set_title(
        titre, color=encre["primaire"], fontsize=13, fontweight="bold",
        loc="left", pad=12,
    )

    # Échelle fixe : un score vit toujours dans [-1, 1]. La laisser s'ajuster
    # ferait paraître énorme une variation de 0,02.
    axes.set_ylim(-1.05, 1.05)
    axes.set_yticks([-1, -0.5, 0, 0.5, 1])
    axes.set_ylabel("Score", color=encre["secondaire"], fontsize=10)

    # Graduations de temps adaptées à l'amplitude réelle des relevés. L'axe
    # reçoit déjà de l'heure de Paris (JournalSuivi.evolution convertit avant
    # de renvoyer) : l'étiquette le dit, pour ne jamais laisser deviner.
    localisateur = mdates.AutoDateLocator(minticks=3, maxticks=8)
    axes.xaxis.set_major_locator(localisateur)
    axes.xaxis.set_major_formatter(mdates.ConciseDateFormatter(localisateur))
    axes.set_xlabel("Heure (FR)", color=encre["secondaire"], fontsize=9)

    _depouiller(axes, encre)


def _depouiller(axes, encre):
    """Grille et cadre discrets : ils situent, ils ne doivent pas se voir."""
    axes.grid(
        axis="y", color=encre["grille"], linewidth=EPAISSEUR_GRILLE,
        linestyle="-", zorder=0,
    )
    axes.set_axisbelow(True)

    for cote in ("top", "right"):
        axes.spines[cote].set_visible(False)
    for cote in ("left", "bottom"):
        axes.spines[cote].set_color(encre["grille"])
        axes.spines[cote].set_linewidth(EPAISSEUR_GRILLE)

    axes.tick_params(colors=encre["secondaire"], labelsize=9, length=0)
