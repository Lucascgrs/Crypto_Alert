# CryptoDashboard — indicateurs techniques traduits en critères qualitatifs

Récupère les **N cryptos les plus capitalisées**, calcule **20 indicateurs
techniques** sur chacune, et traduit chaque valeur numérique en **critère
qualitatif** lisible, associé à un signal positif / neutre / négatif.

Approche 100 % algorithmique (aucun apprentissage automatique) : chaque critère
est une règle explicite, lisible et modifiable dans le code.

> Exemple de sortie plutôt que de chiffres bruts :
> ```
> Bandes de Bollinger (20, 2)  [Positif, +0.25]
>    -  Position dans les bandes : Au-dessus de la bande supérieure (excès haussier)
>   ++  Prix vs bande médiane   : Nettement au-dessus de la médiane
>    ·  Largeur des bandes      : Expansion extrême (les plus agités de l'historique)
>    ·  Évolution de la largeur : Bandes en forte expansion (mouvement en cours)
> ```

---

## Installation

```bash
cd CryptoDashboard
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

`yfinance` est optionnel : il sert de repli pour les cryptos sans paire USDT sur
Binance. Sans lui, ces cryptos sont simplement signalées comme indisponibles.

## Utilisation

Trois façons de lancer le projet, toutes construites sur le même moteur.

### Interface de bureau (customtkinter)

```bash
python interface_bureau.py
```

Cases à cocher des 20 indicateurs à gauche, tableau de synthèse au centre,
détail de tous les critères à droite. L'analyse tourne dans un thread : la
fenêtre ne se fige pas pendant les téléchargements.

Le tableau central reste volontairement compact — une ligne par crypto :

| Colonne | Contenu |
|---|---|
| Crypto / Prix / 24 h | identité et données de marché |
| Indic. | indicateurs réellement calculés sur ceux demandés, ex. `20/20` |
| Score | score technique global, coloré |
| Tendance · Momentum · Volatilité · Volume | score de chaque famille |

Le détail indicateur par indicateur s'obtient **en cliquant sur une ligne** : il
s'affiche dans le panneau de droite, où les libellés ont la place d'être lus.

La colonne `Indic.` passe en orange quand la couverture est partielle. C'est un
garde-fou : un jeton récent n'a d'historique que sur quelques mois, il est donc
noté sur moins d'indicateurs et son score n'a pas la solidité de celui du BTC.

### Interface web (Streamlit)

```bash
python -m streamlit run interface_web.py
```

Réglages en barre latérale, puis trois onglets : synthèse par indicateur,
classement, détail par crypto.

> Les tableaux web sont rendus en HTML (`Styler.to_html`) plutôt qu'avec
> `st.dataframe`, qui dépend de **pyarrow**. Sur certains postes Windows, la DLL
> de pyarrow est bloquée par une stratégie de contrôle d'application et
> `st.dataframe` lève alors une `ImportError`. Le rendu HTML n'a pas cette
> dépendance.

Les trois alimentent le même suivi de performances (voir plus bas).

### Ligne de commande

```bash
python main.py                          # Top 10, les 20 indicateurs
python main.py 20                       # Top 20
python main.py 5 RSI BOLLINGER MACD     # Top 5, sélection d'indicateurs
```

En Python :

```python
from moteur import AnalyseurMarche

analyseur = AnalyseurMarche(codes=["BOLLINGER", "RSI", "ICHIMOKU"])
resultats = analyseur.analyser_top(20)

analyseur.classement(resultats)         # cryptos triées par score technique
analyseur.tableau_synthese(resultats)   # 1 ligne / crypto, 1 colonne / indicateur
analyseur.tableau_criteres(resultats)   # format long : 1 ligne / critère
```

Réglages personnalisés d'un indicateur :

```python
AnalyseurMarche(
    codes=["RSI", "BOLLINGER"],
    reglages={"RSI": {"periode": 21}, "BOLLINGER": {"ecarts": 2.5}},
    intervalle="4h",
)
```

---

## Structure

```
CryptoDashboard/
├── config.py            Paramètres globaux (source, profondeur, seuils de score)
├── donnees.py           Top N CoinGecko + OHLCV Binance (repli Yahoo) + cache disque
├── moteur.py            Orchestration et mise en forme des tableaux
├── presentation.py      Couleurs, libellés et formats partagés par les 2 interfaces
├── notifications.py     Alertes Discord : webhook, message, réglages
├── suivi.py             Suivi des performances : journal Excel et vérification
├── interface_bureau.py  Tableau de bord customtkinter
├── fenetre_alertes.py   Fenêtre de configuration des alertes Discord
├── fenetre_suivi.py     Fenêtre de consultation des performances
├── interface_web.py     Tableau de bord Streamlit
├── main.py              Démonstration en ligne de commande
└── indicateurs/
    ├── base.py          Signal, Critere, Indicateur + outils de traduction
    ├── outils.py        Fonctions numériques partagées (moyennes, ATR, rangs...)
    ├── tendance.py      7 indicateurs
    ├── momentum.py      5 indicateurs
    ├── volatilite.py    4 indicateurs
    ├── volume.py        4 indicateurs
    └── registre.py      Catalogue et instanciation de la sélection
```

### Le contrat d'un indicateur

Chaque indicateur implémente deux méthodes, et rien d'autre :

```python
def calculer(self, df) -> pd.DataFrame       # les colonnes numériques
def interpreter(self, df, calc) -> [Critere] # la traduction en qualitatif
```

Cette séparation permet de réutiliser les valeurs numériques (graphiques, export)
tout en gardant l'interprétation isolée et facile à ajuster.

### Ajouter un indicateur

1. Écrire la classe dans le module de sa catégorie (elle hérite de `Indicateur`).
2. L'ajouter à la liste `CLASSES` dans `indicateurs/registre.py`.

Rien d'autre à toucher : le catalogue, la sélection et les tableaux se mettent à
jour automatiquement.

---

## Les 20 indicateurs et leurs 56 critères

`ctx` = critère de **contexte** : il décrit l'état du marché (volatilité, force
de tendance, niveau de volume) sans dire s'il est haussier ou baissier. Ces
critères sont affichés mais exclus du calcul de score.

### Tendance — 7 indicateurs

| Code | Indicateur | Critères | Détail |
|---|---|---|---|
| `MM` | Moyennes mobiles 20/50/200 | 5 | position vs MM20, nombre de moyennes dominées, alignement, golden/death cross, orientation de la MM200 |
| `MACD` | MACD 12/26/9 | 4 | position vs zéro, vs ligne de signal, dynamique de l'histogramme, fraîcheur du croisement |
| `ADX` | ADX / +DI / -DI (14) | 1 + 2 ctx | domination acheteurs/vendeurs ; force de la tendance et son évolution en contexte |
| `ICHIMOKU` | Ichimoku Kinko Hyo | 5 | position vs nuage, Tenkan/Kijun, prix vs Kijun, orientation du nuage futur, Chikou span |
| `SUPERTREND` | Supertrend (10, 3) | 2 | sens de la tendance, retournement récent |
| `PSAR` | Parabolic SAR | 2 + 1 ctx | sens du SAR, bascule récente ; distance au SAR en contexte |
| `AROON` | Aroon (25) | 2 | dominance Up/Down, configuration (tendance franche ou consolidation) |

### Momentum — 5 indicateurs

| Code | Indicateur | Critères | Détail |
|---|---|---|---|
| `RSI` | RSI (14) | 3 | zone surachat/survente, orientation, divergence prix/RSI |
| `STOCH` | Stochastique 14/3/3 | 2 | zone, croisement %K/%D |
| `CCI` | CCI (20) | 2 | zone (impulsion au-delà de ±100, excès au-delà de ±200), orientation |
| `WILLIAMS_R` | Williams %R (14) | 2 | zone, orientation |
| `ROC` | Performance 7/30/90 | 4 | performance court / moyen / long terme, cohérence entre les trois |

### Volatilité — 4 indicateurs

| Code | Indicateur | Critères | Détail |
|---|---|---|---|
| `BOLLINGER` | Bandes de Bollinger 20/2 | 2 + 2 ctx | position dans les bandes, prix vs médiane ; largeur (resserrement/expansion) et son évolution en contexte |
| `ATR` | ATR (14) | 3 ctx | volatilité en % du prix, régime de volatilité, évolution — **purement contextuel** |
| `KELTNER` | Canaux de Keltner | 1 + 1 ctx | position dans le canal ; squeeze Bollinger/Keltner en contexte |
| `DONCHIAN` | Canal de Donchian (20) | 2 | position dans le range, cassure de range |

### Volume — 4 indicateurs

| Code | Indicateur | Critères | Détail |
|---|---|---|---|
| `OBV` | On Balance Volume | 2 | OBV vs sa moyenne (accumulation/distribution), cohérence volume/prix |
| `RVOL` | Volume relatif (20) | 1 + 1 ctx | volume à l'appui du mouvement ; intensité brute en contexte |
| `CMF` | Chaikin Money Flow (20) | 2 | pression acheteuse/vendeuse, évolution |
| `MFI` | Money Flow Index (14) | 2 | zone (RSI pondéré par les volumes), orientation des flux |

---

## Conventions de lecture

### Les 5 niveaux de signal

| Signal | Valeur | Symbole |
|---|---|---|
| Très positif | +2 | `++` |
| Positif | +1 | `+` |
| Neutre | 0 | `=` |
| Négatif | -1 | `-` |
| Très négatif | -2 | `--` |

Les critères de contexte s'affichent avec `·` et ne sont jamais comptés.

### Calcul des scores

- **Score d'un indicateur** = moyenne de ses critères directionnels, ramenée
  dans `[-1, 1]`.
- **Score d'une crypto** = moyenne des scores d'**indicateurs** (et non de
  critères). Sans cela, Ichimoku et ses 5 critères pèserait deux fois et demie
  plus lourd que le stochastique et ses 2, sans justification.
- Les indicateurs purement contextuels (`ATR`) sont exclus de ces moyennes :
  leur score étant toujours nul, ils tireraient tous les scores vers le neutre.
- La traduction score → libellé (« Positif », « Fortement négatif »...) se règle
  dans `config.SEUILS_SYNTHESE`.

### Oscillateurs : lecture en moyenne-réversion

Les oscillateurs bornés (`RSI`, `STOCH`, `WILLIAMS_R`, `MFI`, `CCI`) sont lus en
**moyenne-réversion** : une zone de surachat est un critère **négatif** (risque
de reflux), une zone de survente un critère **positif** (potentiel de rebond).

Deux choix de pondération en découlent, volontaires :

- Les zones d'excès valent un simple `+1` / `-1`, jamais `±2`. Une lecture
  contrarienne est moins fiable qu'une lecture de tendance : en crypto, un RSI à
  85 peut le rester des semaines. L'intensité reste portée par le **libellé**,
  qui est de toute façon l'information réellement affichée.
- Pour Bollinger, **toucher** une bande relève du momentum (le prix « longe » la
  bande dans une tendance saine) ; seule une clôture **à l'extérieur** des
  bandes constitue un excès statistique et bascule en lecture contrarienne.

**Conséquence à connaître** : dans une tendance haussière puissante, les
oscillateurs virent au négatif pendant que les indicateurs de tendance restent
au vert. Ce n'est pas une incohérence, c'est le message du tableau de bord :
*« tendance solide, mais prix étiré »*. Le score global, qui moyenne les deux
familles, est donc à lire comme un **résumé**, pas comme un signal d'achat — la
valeur du projet est dans le détail des critères, pas dans le chiffre agrégé.

---

## Données

| Besoin | Source | Remarque |
|---|---|---|
| Classement par capitalisation | CoinGecko `/coins/markets` | stablecoins exclus par défaut |
| Historique OHLCV | Binance `/api/v3/klines` | 1000 bougies max par appel, largement suffisant |
| Repli OHLCV | Yahoo Finance (`yfinance`) | pour les cryptos sans paire USDT |

Un cache disque (`cache/`, 15 min par défaut) évite de re-télécharger 20
historiques à chaque exécution. Il se désactive avec
`SourceDonnees(utiliser_cache=False)`.

### Pourquoi certaines cryptos affichent « Historique indisponible »

La source principale est Binance, qui **ne cote pas les jetons des plateformes
concurrentes**. Interrogé sur ces symboles, son API répond `400 Invalid symbol` :

| Jeton | Plateforme d'origine |
|---|---|
| `CRO` | Crypto.com |
| `MNT` | Mantle / Bybit |
| `OKB` | OKX |
| `LEO` | Bitfinex |
| `BGB` | Bitget |

Ce ne sont pas des erreurs du projet : ces jetons n'existent tout simplement pas
sur Binance. **C'est à cela que sert le repli Yahoo Finance** — avec `yfinance`
installé, CRO, OKB, LEO et BGB reviennent avec 400 bougies et sont analysés
normalement.

Il reste deux cas irréductibles :

- **Historique trop court.** `MNT` n'a que ~77 bougies chez Yahoo. Les
  indicateurs qui exigent davantage (MM 200, Ichimoku) renvoient chacun
  « Historique insuffisant (77 bougies, 210 requises) », les autres fonctionnent.
  La crypto est notée, mais sur une couverture partielle — d'où la colonne
  `Indic.`.
- **Jeton trop récent.** `RAIN`, listé de la veille, n'a qu'une bougie :
  « Historique insuffisant (1 bougie, 60 requises) ».
- **Aucune source.** `HYPE` (Hyperliquid, échangé sur son propre DEX) ou
  `FIGR_HELOC` (actif tokenisé) ne sont ni sur Binance ni sur Yahoo.

Dans tous les cas la crypto reste affichée **avec sa raison** plutôt que d'être
masquée : une absence inexpliquée est plus déroutante qu'une absence motivée.

### Stablecoins

Ils sont écartés du classement — l'analyse technique n'a aucun sens sur un actif
arrimé au dollar. Deux filets : une liste explicite (`config.STABLECOINS`) et un
motif `^[A-Z0-9]{0,3}USD[A-Z0-9]{0,3}$` qui rattrape automatiquement les
nouveaux venus (`USDG`, `RLUSD`, `USD1`...), une liste figée se périmant vite.

### Intervalles disponibles

`1d`, `4h`, `1h`, `30m`, `15m`, `5m`, `1m`. Les intervalles en minutes ne sont
servis que par Binance — Yahoo ne remonte pas assez loin en intraday pour
alimenter une MM 200. La profondeur téléchargée s'adapte (`1000` bougies pour
les intervalles courts, plafond imposé par Binance), et le cache disque ne
survit jamais à la bougie en cours : conserver 15 minutes des chandeliers d'une
minute donnerait des prix périmés.

Par défaut : 400 bougies journalières, soit la profondeur nécessaire pour que la
MM200 et les rangs-percentiles sur 250 périodes soient fiables. Un indicateur
qui ne dispose pas de son minimum de bougies (`periodes_min`) renvoie une erreur
explicite plutôt qu'une valeur fausse.

---

## Alertes Discord

Envoi d'un récapitulatif des cryptos les mieux (ou les plus mal) notées dans un
salon Discord, **manuellement** ou **automatiquement toutes les X minutes/heures**.
Même principe que `PokemonScraper` : un simple webhook, rien à héberger.

### Configuration

Dans l'interface de bureau, bouton **⚙ Alertes**. La fenêtre règle trois choses :

**1. Le webhook.** Dans Discord : *Paramètres du salon → Intégrations → Webhooks
→ Nouveau webhook → Copier l'URL*. Attention, ce n'est **pas** un lien
d'invitation `discord.gg/...` — le projet le détecte et vous le dit. Le bouton
*Tester le webhook* envoie un message de contrôle.

**2. L'envoi automatique.** Case à cocher + intervalle (minimum 1 minute, pour
ménager les API). À chaque échéance, l'analyse complète est **relancée** avant
l'envoi : les données sont donc toujours fraîches. Si une analyse manuelle est
déjà en cours, le tour est sauté plutôt que d'en lancer deux en parallèle.

**3. Le contenu.**

| Réglage | Effet |
|---|---|
| Cryptos par alerte | combien de cryptos au maximum dans le message (1 à 10) |
| Score minimum | seuil sur la **valeur absolue** du score : une crypto très baissière alerte autant qu'une très haussière |
| Signaler | `tous`, `haussier` ou `baissier` |
| Scores par famille | ajoute la ligne `Tendance +0.85 · Momentum +0.41 · ...` |
| Critères marquants | ajoute les critères qui expliquent le score (1 à 10) |
| Mention | `@here`, `<@&role_id>`... préfixé au message |
| Silencieux si vide | ne rien envoyer quand aucune crypto ne passe le seuil |

Les réglages sont enregistrés dans `config_alertes.json`, **listé dans
`.gitignore`** puisqu'il contient l'URL du webhook (un secret).

### Ce que reçoit Discord

Un embed coloré par crypto, teinté selon la synthèse :

```
📊 Alerte CryptoDashboard (Journalier (1d)) — 24/08/2026 à 18:09
3 crypto(s) au-dessus du seuil de 0.30.

┌─ BTC — Bitcoin ──────────────────────────────────────────┐
│ Score technique : +0.59 — Fortement positif              │
│ Prix : 79 435 $  ·  24 h : +2.86 %                       │
│ Tendance +0.85 · Momentum +0.41 · Volatilité +0.75 ...   │
│                                                          │
│ ++ Prix vs MM20 : Nettement au-dessus de la MM20         │
│ ++ MACD vs ligne zéro : Nettement au-dessus de zéro      │
│ ++ Domination +DI / -DI : Acheteurs nettement dominants  │
│ ++ Position vs nuage : Prix au-dessus du nuage           │
│ 35 critères positifs · 5 négatifs · 19 indicateurs       │
└──────────────────────────────────────────────────────────┘
```

Les critères marquants sont piochés **à tour de rôle dans des indicateurs
différents** : quatre critères issus de quatre indicateurs expliquent bien mieux
un score que les quatre critères d'un même indicateur, qui répètent la même idée.

### Depuis l'interface web

Panneau *Alertes Discord* de la barre latérale : mêmes réglages, même fichier de
configuration, envoi **manuel** uniquement. L'envoi automatique suppose un
programme qui tourne en continu, ce qu'une page web rechargée à chaque
interaction ne permet pas — il reste donc propre à l'interface de bureau.

---

## Suivi des performances (backtest)

Les scores produits valent-ils quelque chose ? Le projet répond à la question en
tenant lui-même le compte de ses prédictions.

**À chaque analyse** (bureau, web ou ligne de commande), deux choses se passent :

1. une photographie de tous les scores est ajoutée au classeur `suivi_scores.xlsx` ;
2. tous les relevés précédents dont l'**échéance** est atteinte sont confrontés
   au prix réellement observé.

Aucune action supplémentaire n'est demandée : le suivi se remplit à l'usage.

### L'échéance

Un score est évalué `HORIZON_BOUGIES` bougies plus tard (6 par défaut). Exprimer
l'horizon en bougies le rend cohérent quel que soit l'intervalle :

| Intervalle | Horizon d'évaluation |
|---|---|
| `1d` | 6 jours |
| `4h` | 24 heures |
| `1h` | 6 heures |
| `15m` | 1 h 30 |
| `5m` | 30 minutes |
| `1m` | 6 minutes |

Le prix d'échéance est lu **dans la bougie correspondante** de l'historique
OHLCV, pas dans le prix du moment : la vérification est donc exacte, même
effectuée longtemps après coup. La colonne `precision_prix` indique `exacte`,
`approchée` (bougie manquante) ou, à défaut, le relevé est marqué `Expiré`.

### Les trois onglets du classeur

**`Relevés`** — le journal brut, une ligne par crypto et par analyse : horodatage,
échéance, prix, score global, les quatre scores de famille, la couverture en
indicateurs, l'origine (`analyse`, `auto`, `web`, `cli`) et le `statut`
(`En attente` / `Vérifié` / `Expiré`).

**`Vérifications`** — les relevés arrivés à échéance : prix initial et final,
rendement, rendement du lot, rendement relatif, sens prédit, sens réel et
`resultat`.

**`Performance`** — le tableau qui répond à la question, découpé par
regroupement : bilan global, **par tranche de score**, par intervalle, par crypto.

### Comment lire le résultat

Quatre issues, volontairement distinctes :

| Résultat | Signification |
|---|---|
| `Correct` | le sens annoncé s'est réalisé |
| `Incorrect` | le sens annoncé était l'inverse |
| `Indécis` | le marché n'a pas bougé (moins de 0,5 %) : ni réussite ni échec |
| `Non prédictif` | le score était neutre (score entre -0,15 et +0,15) : l'application n'annonçait rien |

Le **taux de réussite ne compte que les cas tranchés** (`Correct` /
`Correct + Incorrect`). Compter les indécis et les scores neutres comme des
échecs le tirerait mécaniquement vers le bas et rendrait la mesure inutilisable.

Deux lectures comptent vraiment :

- **La tranche de score.** Un score fort doit mieux prédire qu'un score faible.
  Si `Fortement positif` et `Neutre` affichent le même taux, les scores ne
  portent aucune information — c'est le test décisif.
- **Le rendement relatif.** Il compare chaque crypto à la moyenne de son lot
  d'analyse. Si tout le marché a pris 3 %, une crypto bien notée qui prend 3 %
  n'a rien démontré. Cette colonne est vide sur les lignes `Global` et
  `Intervalle` : elles contiennent des lots entiers, la moyenne des écarts à la
  moyenne y vaut zéro par construction et ne mesurerait rien.

### Consultation

Bouton **📈 Suivi** dans l'interface de bureau (avec un bouton pour ouvrir le
classeur dans Excel), onglet **Suivi des performances** dans l'interface web, ou
affichage direct en fin d'exécution de `python main.py`.

### Précautions de lecture

- Un taux de réussite se juge par rapport à **50 %**, pas par rapport à 0.
- Les cryptos d'un même lot montent et descendent ensemble : 20 vérifications
  issues d'une seule analyse ne sont pas 20 observations indépendantes, plutôt
  deux ou trois. Il faut **beaucoup d'analyses étalées dans le temps** avant que
  les chiffres veuillent dire quoi que ce soit.
- Les intervalles courts font grossir le classeur vite : c'est voulu, ils
  permettent d'accumuler des vérifications en quelques heures au lieu de
  quelques semaines.

---

## Ajouter une troisième interface

Le moteur est indépendant de l'affichage, et `presentation.py` centralise les
couleurs et les formats. Pour brancher une nouvelle interface, trois appels
suffisent :

```python
indicateurs.catalogue()                 # la liste des cases à cocher
AnalyseurMarche(codes=...).analyser_top(n)   # l'analyse
AnalyseurMarche.tableau_criteres(resultats)  # format long, 1 ligne / critère
```

Les couleurs se prennent dans `presentation.couleur_synthese()` et
`presentation.couleur_critere()`, pour rester cohérent avec les deux interfaces
existantes.
