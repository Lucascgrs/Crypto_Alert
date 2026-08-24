"""
Interface web (Streamlit).

    python -m streamlit run interface_web.py

Même moteur et mêmes couleurs que l'interface de bureau : seul l'affichage
change. Les résultats sont conservés dans `st.session_state` plutôt que dans un
cache Streamlit, car ils contiennent des objets métier (dataclasses, énumérations)
qu'il est plus simple de garder tels quels que de sérialiser.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import graphiques
import notifications as notif
import presentation as pr
import suivi
from indicateurs import CODES_PAR_DEFAUT, Categorie, catalogue, codes_par_categorie
from moteur import AnalyseurMarche

st.set_page_config(
    page_title="CryptoDashboard", page_icon="📊", layout="wide",
    initial_sidebar_state="expanded",
)


# ===========================================================================
# BARRE LATÉRALE : LES RÉGLAGES
# ===========================================================================
def barre_laterale() -> tuple[list[str], int, str]:
    """Affiche les réglages et renvoie (indicateurs cochés, nombre, intervalle)."""
    st.sidebar.title("Réglages")

    nombre = st.sidebar.slider("Cryptos analysées (Top capitalisation)", 5, 50, 20, step=5)
    libelle = st.sidebar.selectbox("Intervalle des bougies", list(pr.INTERVALLES))
    intervalle = pr.INTERVALLES[libelle]

    st.sidebar.divider()
    st.sidebar.subheader("Indicateurs")

    # Les boutons Tout / Rien agissent en préremplissant l'état des cases, qui
    # est ensuite lu par les widgets eux-mêmes.
    colonne_tout, colonne_rien = st.sidebar.columns(2)
    if colonne_tout.button("Tout", width="stretch"):
        for code in CODES_PAR_DEFAUT:
            st.session_state[f"case_{code}"] = True
    if colonne_rien.button("Rien", width="stretch"):
        for code in CODES_PAR_DEFAUT:
            st.session_state[f"case_{code}"] = False

    fiches = catalogue().set_index("code")
    coches = []
    for categorie in Categorie:
        codes = codes_par_categorie(categorie)
        if not codes:
            continue
        with st.sidebar.expander(f"{categorie.value} ({len(codes)})", expanded=True):
            for code in codes:
                if st.checkbox(
                    fiches.loc[code, "nom"],
                    value=st.session_state.get(f"case_{code}", True),
                    key=f"case_{code}",
                    help=fiches.loc[code, "description"],
                ):
                    coches.append(code)

    st.sidebar.divider()
    st.sidebar.caption(f"{len(coches)} indicateur(s) sélectionné(s) sur {len(CODES_PAR_DEFAUT)}.")
    return coches, nombre, intervalle


def bloc_discord(resultats, intervalle: str):
    """
    Envoi manuel sur Discord, avec les mêmes réglages que l'interface de bureau
    (même fichier de configuration, mêmes fonctions d'envoi).

    L'envoi AUTOMATIQUE reste réservé à l'interface de bureau : il suppose un
    programme qui tourne en continu, ce qu'une page web rechargée à chaque
    interaction ne permet pas.
    """
    with st.sidebar.expander("Alertes Discord", expanded=False):
        config = notif.charger_config()

        webhook = st.text_input(
            "Webhook", value=config.get("webhook", ""), type="password",
            help="Discord → Paramètres du salon → Intégrations → Webhooks → Copier l'URL.",
        )
        nb = st.slider("Cryptos par alerte", 1, 10, int(config.get("nb_cryptos", 5)))
        seuil = st.slider(
            "Score minimum (valeur absolue)", 0.0, 1.0,
            float(config.get("score_min", 0.30)), step=0.05,
        )
        sens = st.selectbox(
            "Signaler", ["tous", "haussier", "baissier"],
            index=["tous", "haussier", "baissier"].index(config.get("sens", "tous")),
        )
        criteres = st.checkbox(
            "Inclure les critères marquants", value=config.get("inclure_criteres", True)
        )

        config.update(
            {
                "webhook": webhook, "nb_cryptos": nb, "score_min": seuil,
                "sens": sens, "inclure_criteres": criteres,
            }
        )

        gauche, droite = st.columns(2)
        if gauche.button("Enregistrer", width="stretch"):
            ok, detail = notif.enregistrer_config(config)
            (st.success if ok else st.error)(detail)

        if droite.button("Envoyer", width="stretch", type="primary"):
            if not resultats:
                st.warning("Lancez d'abord une analyse.")
            else:
                ok, detail = notif.envoyer_alerte(resultats, config, intervalle)
                (st.success if ok else st.error)(detail)


# ===========================================================================
# TABLEAUX
# ===========================================================================
# Les tableaux sont rendus en HTML plutôt qu'avec st.dataframe : ce dernier
# repose sur pyarrow, dont la DLL est bloquée par la stratégie de contrôle
# d'application de certains postes Windows. Styler.to_html() ne dépend que de
# pandas et jinja2, et donne en prime la main sur la mise en forme.
CSS_TABLEAU = """
<style>
.conteneur-tableau { overflow-x: auto; max-height: 660px; margin-bottom: 0.5rem; }
.tableau-crypto { width: 100%; border-collapse: collapse; font-size: 0.86rem; }
.tableau-crypto th {
    position: sticky; top: 0; z-index: 1;
    background: rgba(128, 128, 128, 0.22); backdrop-filter: blur(6px);
    padding: 6px 8px; font-weight: 600; text-align: center; white-space: nowrap;
    border-bottom: 2px solid rgba(128, 128, 128, 0.4);
}
.tableau-crypto td {
    padding: 5px 8px; text-align: center; white-space: nowrap;
    border-bottom: 1px solid rgba(128, 128, 128, 0.18);
}
.tableau-crypto tbody th { text-align: left; font-weight: 700; }
</style>
"""


def afficher_tableau_html(style):
    """Rend un Styler pandas sous forme de tableau HTML défilable."""
    html = style.set_table_attributes('class="tableau-crypto"').to_html()
    st.markdown(
        CSS_TABLEAU + f'<div class="conteneur-tableau">{html}</div>',
        unsafe_allow_html=True,
    )


def tableau_synthese(resultats, codes: list[str]):
    """Grille colorée : une ligne par crypto, une colonne par indicateur."""
    lignes = []
    for resultat in sorted(resultats, key=lambda r: -r.score_global):
        if not resultat.indicateurs_notes:
            continue
        ligne = {
            "Crypto": resultat.symbole,
            "Prix": pr.formater_prix(resultat.prix),
            "24 h": pr.formater_variation(resultat.variation_24h),
            "Score": round(resultat.score_global, 2),
        }
        for code in codes:
            indicateur = resultat.resultats.get(code)
            ligne[code] = indicateur.synthese if indicateur else "Non disponible"
        lignes.append(ligne)

    if not lignes:
        st.warning("Aucune crypto n'a d'historique exploitable.")
        return

    tableau = pd.DataFrame(lignes).set_index("Crypto")

    # Les colonnes d'indicateurs sont abrégées (++ / + / = / - / --) : avec 20
    # indicateurs, les libellés complets rendraient le tableau illisible.
    # La couleur est calculée AVANT l'abréviation, sur la synthèse d'origine.
    couleurs = {code: tableau[code].map(pr.couleur_synthese) for code in codes}
    for code in codes:
        tableau[code] = tableau[code].map(pr.abreger)

    def colorer_indicateur(colonne):
        """Fond coloré d'une colonne d'indicateur, cellule par cellule."""
        return [
            f"background-color: {c}; color: white;" for c in couleurs[colonne.name]
        ]

    style = (
        tableau.style
        .apply(colorer_indicateur, subset=codes)
        .map(lambda v: f"background-color: {pr.couleur_score(v)}; color: white;", subset=["Score"])
        .format({"Score": "{:+.2f}"})
    )
    afficher_tableau_html(style)


def tableau_classement(resultats):
    """Classement du plus haussier au plus baissier, avec le décompte de signaux."""
    tableau = AnalyseurMarche.classement(resultats)
    if tableau.empty:
        return
    style = (
        tableau.style
        .hide(axis="index")
        .map(lambda v: f"background-color: {pr.couleur_score(v)}; color: white;", subset=["Score"])
        .format({"Score": "{:+.2f}"})
    )
    afficher_tableau_html(style)


# ===========================================================================
# DÉTAIL D'UNE CRYPTO
# ===========================================================================
def badge(texte: str, couleur: str) -> str:
    """Petite pastille HTML colorée, pour rester cohérent avec l'autre interface."""
    return (
        f"<span style='background-color:{couleur};color:white;padding:2px 8px;"
        f"border-radius:4px;font-size:0.85em;font-weight:600;'>{texte}</span>"
    )


def detail_crypto(resultat):
    """Tous les critères qualitatifs d'une crypto, groupés par catégorie."""
    entete = st.columns(4)
    entete[0].metric("Score technique", pr.formater_score(resultat.score_global), resultat.synthese)
    entete[1].metric("Prix", pr.formater_prix(resultat.prix))
    entete[2].metric("Variation 24 h", pr.formater_variation(resultat.variation_24h))
    entete[3].metric("Capitalisation", pr.formater_capitalisation(resultat.capitalisation))

    if not resultat.indicateurs_notes:
        st.error(resultat.raison_indisponible)
        return

    compte = resultat.compter_signaux()
    st.caption(
        f"{compte['positifs']} critères positifs · {compte['neutres']} neutres "
        f"· {compte['negatifs']} négatifs"
    )

    # Un onglet par catégorie : on ne montre que celles réellement sélectionnées.
    categories = [c for c in Categorie
                  if any(i.categorie == c for i in resultat.resultats.values())]
    onglets = st.tabs([c.value for c in categories])

    for onglet, categorie in zip(onglets, categories):
        with onglet:
            for indicateur in resultat.resultats.values():
                if indicateur.categorie != categorie:
                    continue

                gauche, droite = st.columns([3, 1])
                gauche.markdown(f"**{indicateur.nom}**")
                droite.markdown(
                    badge(indicateur.synthese, pr.couleur_synthese(indicateur.synthese)),
                    unsafe_allow_html=True,
                )

                if indicateur.erreur:
                    st.caption(indicateur.erreur)
                    st.divider()
                    continue

                for critere in indicateur.criteres:
                    marque = critere.signal.symbole if critere.directionnel else "·"
                    valeur = pr.formater_valeur_critere(critere.valeur_num)
                    suffixe = f" <span style='opacity:0.5'>({valeur})</span>" if valeur else ""
                    st.markdown(
                        f"{badge(marque, pr.couleur_critere(critere))} "
                        f"**{critere.libelle}** : {critere.valeur}{suffixe}",
                        unsafe_allow_html=True,
                    )
                st.divider()


# ===========================================================================
# SUIVI DES PERFORMANCES
# ===========================================================================
def journaliser(resultats, analyseur, intervalle: str, codes: list[str]):
    """
    Alimente le classeur de suivi après chaque analyse : on photographie les
    scores, puis on confronte au marché les relevés arrivés à échéance.
    """
    try:
        journal = suivi.JournalSuivi()
        ajoutes = journal.enregistrer(resultats, intervalle, codes, origine="web")
        # `source` sert de recours pour les relevés d'un autre intervalle, que
        # les bougies de cette analyse ne couvrent pas.
        bilan = journal.verifier(historiques=analyseur.historiques, source=analyseur.source)
        ok, detail = journal.sauvegarder()
    except Exception as e:
        st.warning(f"Suivi indisponible : {type(e).__name__} — {e}")
        return

    st.session_state.journal = journal
    if not ok:
        st.warning(detail)   # le plus souvent : classeur ouvert dans Excel
    else:
        st.caption(
            f"Suivi : +{ajoutes} relevés, {bilan['verifies']} vérifiés, "
            f"{bilan['en_attente']} en attente d'échéance."
        )


def onglet_suivi():
    """Tableau des performances mesurées, tel qu'il figure dans le classeur."""
    journal = st.session_state.get("journal") or suivi.JournalSuivi()
    st.caption(journal.resume())

    performance = journal.performance()
    if performance.empty:
        st.info(
            "Aucune vérification pour l'instant. Les relevés sont confrontés au marché "
            "lorsque leur échéance est atteinte, quelques bougies après l'analyse qui "
            "les a produits — relancez une analyse après ce délai."
        )
        return

    st.caption(
        "Le taux de réussite ne compte que les cas tranchés : un score neutre "
        "(« Non prédictif ») ou un marché immobile (« Indécis ») n'est ni une réussite "
        "ni un échec. Le rendement relatif compare chaque crypto à la moyenne de son "
        "lot d'analyse : c'est lui qui dit si le score apporte vraiment quelque chose."
    )

    def colorer_taux(valeur):
        if valeur is None or valeur != valeur:
            return ""
        # Un taux se juge par rapport à 50 % (le pile ou face), pas par rapport à 0.
        couleur = "#157f3d" if valeur >= 60 else (
            "#2e8b57" if valeur >= 52 else (
                "#6b7280" if valeur >= 48 else "#d1495b"))
        return f"background-color: {couleur}; color: white;"

    for regroupement in ["Global", "Tranche de score", "Intervalle", "Crypto"]:
        sous = performance[performance["Regroupement"] == regroupement]
        if sous.empty:
            continue
        st.markdown(f"**{regroupement}**")
        style = (
            sous.drop(columns=["Regroupement"]).style
            .hide(axis="index")
            .map(colorer_taux, subset=["Taux de réussite %"])
            .format({
                "Taux de réussite %": lambda v: "—" if v != v else f"{v:.1f} %",
                "Rendement moyen %": "{:+.2f} %",
                "Rendement relatif moyen %": lambda v: "—" if v != v else f"{v:+.2f} %",
            })
        )
        afficher_tableau_html(style)


def onglet_evolution():
    """
    Trajectoire des scores dans le temps : on choisit les cryptos, le type de
    score et l'intervalle. Chaque analyse ajoute un point.
    """
    journal = st.session_state.get("journal") or suivi.JournalSuivi()
    intervalles = journal.intervalles_suivis()
    if not intervalles:
        st.info(
            "Aucun relevé pour l'instant. Lancez une analyse : chaque exécution "
            "ajoute un point à la courbe."
        )
        return

    reglages = st.columns([1, 1, 3])
    type_score = reglages[0].selectbox("Score", list(suivi.TYPES_SCORE))
    intervalle = reglages[1].selectbox("Intervalle", intervalles)

    disponibles = journal.symboles_suivis(intervalle)
    choisies = reglages[2].multiselect(
        "Cryptos", disponibles, default=disponibles[: pr.MAX_SERIES],
        help=f"Au plus {pr.MAX_SERIES} : au-delà, deux teintes deviendraient "
             "indiscernables pour un lecteur daltonien.",
    )
    if len(choisies) > pr.MAX_SERIES:
        st.warning(
            f"Seules les {pr.MAX_SERIES} premières cryptos sont tracées "
            f"({len(choisies) - pr.MAX_SERIES} laissée(s) de côté)."
        )
        choisies = choisies[: pr.MAX_SERIES]

    table = journal.evolution(type_score, choisies, intervalle)

    # L'attribution vit dans la session : une crypto garde sa couleur quand on
    # modifie la sélection ou le type de score.
    mode = "clair" if st.get_option("theme.base") == "light" else "sombre"
    if st.session_state.get("mode_graphique") != mode:
        st.session_state.mode_graphique = mode
        st.session_state.couleurs = pr.AttributionCouleurs(mode)
    couleurs = st.session_state.couleurs
    couleurs.oublier(choisies)

    st.pyplot(
        graphiques.figure_evolution(
            table, type_score, couleurs, mode=mode, intervalle=intervalle
        ),
        width="stretch",
    )
    st.caption(
        "La bande grise est la zone neutre : entre -0,15 et +0,15, l'application "
        "n'annonce aucune direction. L'échelle est fixée à [-1, +1] pour qu'une même "
        "variation garde la même ampleur d'un relevé à l'autre."
    )

    # Tableau des valeurs : il double l'information portée par la couleur.
    if not table.empty:
        st.markdown("**Derniers relevés**")
        valeurs = table.tail(12).sort_index(ascending=False).copy()
        valeurs.index = valeurs.index.strftime("%d/%m/%Y %H:%M")
        valeurs.index.name = "Relevé"
        afficher_tableau_html(
            valeurs.style.format(lambda v: "—" if v != v else f"{v:+.2f}")
        )


# ===========================================================================
# PAGE
# ===========================================================================
def main():
    st.title("CryptoDashboard")
    st.caption(
        "Les indicateurs techniques des cryptos les plus capitalisées, "
        "traduits en critères qualitatifs."
    )

    codes, nombre, intervalle = barre_laterale()
    bloc_discord(st.session_state.get("resultats"), intervalle)

    if st.button("Lancer l'analyse", type="primary"):
        if not codes:
            st.warning("Sélectionnez au moins un indicateur.")
        else:
            bougies = pr.BOUGIES_PAR_INTERVALLE.get(intervalle, 400)
            analyseur = AnalyseurMarche(
                codes=codes, intervalle=intervalle, nb_bougies=bougies, verbeux=False
            )
            with st.spinner(f"Téléchargement et analyse de {nombre} cryptos..."):
                try:
                    st.session_state.resultats = analyseur.analyser_top(nombre)
                    st.session_state.codes = codes
                    journaliser(st.session_state.resultats, analyseur, intervalle, codes)
                except Exception as e:
                    st.error(f"Échec de l'analyse : {type(e).__name__} — {e}")

    resultats = st.session_state.get("resultats")
    if not resultats:
        st.info("Choisissez vos indicateurs dans la barre latérale, puis lancez l'analyse.")
        return

    # On réaffiche avec les indicateurs réellement analysés, pas ceux cochés
    # depuis : l'utilisateur peut avoir modifié la sélection sans relancer.
    codes_analyses = [c for c in st.session_state.get("codes", codes) if c in CODES_PAR_DEFAUT]
    exploitables = [r for r in resultats if r.indicateurs_notes]

    resume = st.columns(3)
    resume[0].metric("Cryptos analysées", f"{len(exploitables)} / {len(resultats)}")
    resume[1].metric("Indicateurs", len(codes_analyses))
    resume[2].metric(
        "Critères produits",
        sum(len(i.criteres) for r in resultats for i in r.resultats.values()),
    )

    onglet_synthese, onglet_classement, onglet_detail, onglet_perf, onglet_evo = st.tabs(
        ["Synthèse par indicateur", "Classement", "Détail par crypto",
         "Suivi des performances", "Évolution des scores"]
    )

    with onglet_synthese:
        tableau_synthese(resultats, codes_analyses)
        st.caption("++ fortement positif · + positif · = neutre · − négatif · −− fortement négatif")

    with onglet_classement:
        tableau_classement(resultats)

    with onglet_detail:
        if not exploitables:
            st.warning("Aucune crypto exploitable.")
        else:
            symbole = st.selectbox(
                "Crypto", [r.symbole for r in exploitables],
                format_func=lambda s: next(
                    (f"{r.symbole} — {r.nom}" for r in exploitables if r.symbole == s), s
                ),
            )
            detail_crypto(next(r for r in exploitables if r.symbole == symbole))

    with onglet_perf:
        onglet_suivi()

    with onglet_evo:
        onglet_evolution()


if __name__ == "__main__":
    main()
