# CryptoDashboard — indicateurs techniques traduits en critères qualitatifs

Récupère les **N cryptos les plus capitalisées**, calcule des **indicateurs
techniques** sur chacune, et traduit chaque valeur numérique en **critère
qualitatif** lisible, associé à un signal positif / neutre / négatif.

Approche 100 % algorithmique (aucun apprentissage automatique) : chaque critère
est une règle explicite, lisible et modifiable dans le code.

Deux jeux d'indicateurs cohabitent, sélectionnables par un interrupteur dans les
deux interfaces : les **20 suiveurs** historiques, et les **7 indicateurs
d'anticipation** ajoutés ensuite. Voir [Les deux approches](#les-deux-approches)
— et surtout ce que le diagnostic en dit, qui n'est pas flatteur.

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

Réglages en barre latérale, puis cinq onglets : synthèse par indicateur,
classement, détail par crypto, évolution des scores et simulation.

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
├── simulation.py        Simulation historique : rejoue la stratégie sur le passé
├── diagnostic.py        Diagnostic : les scores prédisent-ils quoi que ce soit ?
├── graphiques.py        Courbes d'évolution et de capital (partagées par les 2 interfaces)
├── interface_bureau.py  Tableau de bord customtkinter
├── fenetre_alertes.py   Fenêtre de configuration des alertes Discord
├── fenetre_suivi.py     Fenêtre de suivi : évolution des scores et simulation
├── interface_web.py     Tableau de bord Streamlit
├── main.py              Démonstration en ligne de commande
└── indicateurs/
    ├── base.py          Signal, Critere, Indicateur + outils de traduction
    ├── outils.py        Fonctions numériques partagées (moyennes, ATR, rangs...)
    ├── tendance.py      7 indicateurs suiveurs
    ├── momentum.py      5 indicateurs suiveurs
    ├── volatilite.py    4 indicateurs suiveurs
    ├── volume.py        4 indicateurs suiveurs
    ├── anticipation.py  7 indicateurs de l'approche « anticipation »
    └── registre.py      Catalogue, approches et instanciation de la sélection
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
2. L'ajouter à `CLASSES_SUIVEUSES` ou `CLASSES_ANTICIPATION` dans
   `indicateurs/registre.py`, selon son approche.

Rien d'autre à toucher : le catalogue, la sélection et les tableaux se mettent à
jour automatiquement.

---

## Les 20 indicateurs suiveurs et leurs 56 critères

C'est la sélection par défaut. Pour les 7 autres, voir
[Les deux approches](#les-deux-approches).

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

## Les deux approches

### D'où vient la question

Le diagnostic (`python diagnostic.py`) a mesuré sur 9 000 barres que le score
des 20 indicateurs suiveurs est corrélé à **+0,84** avec le rendement des 12
bougies **précédentes**, et à **environ 0,00** avec celui des 12 bougies
**suivantes**.

Ce n'est pas un défaut de réglage. Une moyenne mobile, un MACD, un Supertrend
sont par construction des transformations lissées du prix passé : ils décrivent
très bien ce qui vient d'arriver, et c'est exactement pour cela qu'ils ne
l'anticipent pas.

D'où un second jeu d'indicateurs, sélectionnés sur une règle explicite :

> un indicateur entre dans l'approche « anticipation » seulement si son score
> **n'est pas une fonction monotone du rendement des dernières barres**.

Chacun regarde donc autre chose que le premier moment du prix : l'étirement, la
dérivée seconde, le désaccord prix / oscillateurs, la forme des bougies, le
troisième moment des rendements, le régime de volatilité.

### Anticipation — 7 indicateurs, 14 critères

| Code | Indicateur | Catégorie | Critères | Ce qu'il regarde |
|---|---|---|---|---|
| `RETOUR_MOYENNE` | Retour à la moyenne (Z-score 20) | Momentum | 2 | distance du prix à sa moyenne en écarts-types, et vitesse à laquelle l'écart se creuse — lus à contre-courant |
| `ESSOUFFLEMENT` | Essoufflement (dérivée seconde) | Momentum | 2 | la jambe en cours comparée à la précédente (normalisée par l'ATR), et la longueur de la série de bougies de même sens |
| `DIVERGENCES` | Divergences multiples | Momentum | 2 | désaccord prix / RSI, MACD et OBV, sur 20 puis 40 bougies. Trois oscillateurs d'accord valent bien mieux qu'un seul |
| `ASYMETRIE` | Asymétrie des rendements (40) | Volatilité | 2 | skewness des rendements, et part du mouvement portée par la plus grosse bougie de la fenêtre |
| `EPUISEMENT` | Épuisement (climax de volume) | Volume | 2 | volume record sur grande amplitude dont la clôture **contredit** le mouvement (capitulation, distribution) ; mèches de rejet |
| `COMPRESSION` | Compression de volatilité | Volatilité | 2 ctx | largeur des bandes dans son propre historique. Dit **quand**, jamais **dans quel sens** |
| `EFFICIENCE` | Efficience du mouvement | Tendance | 2 ctx | ratio de Kaufman et autocorrélation des rendements : dit laquelle des deux approches est dans son élément |

Les deux derniers sont **purement contextuels** : ils n'entrent dans aucun score.
`EFFICIENCE` est le méta-indicateur du tableau de bord — un marché au chemin
efficient et aux rendements persistants est le terrain des suiveurs, un marché
haché aux rendements qui se contredisent est celui de l'anticipation.

### L'interrupteur

- **Bureau** : bouton segmenté en haut du panneau de gauche.
- **Web** : boutons radio « Approche » dans la barre latérale.
- **Simulation** : menu « Approche » dans la section *Signal d'entrée*, pour
  rejouer la même stratégie avec l'un puis l'autre jeu.

Les deux sélections sont indépendantes : décocher trois indicateurs d'un côté,
aller voir l'autre, revenir — la sélection est toujours là. Les boutons
*Tout* / *Rien* ne touchent qu'à l'approche affichée.

À savoir : côté anticipation, la catégorie **Tendance** ne contient que
`EFFICIENCE`, qui est contextuel. Le score de famille « Tendance » est donc vide
pour cette approche — la simulation le refuse explicitement, et la courbe
d'évolution correspondante reste plate. Ce n'est pas un bug : il n'y a pas de
tendance à mesurer dans un jeu d'indicateurs qui ne suit pas la tendance.

### Pourquoi les deux ne se mélangent jamais

Un Supertrend dit « ça monte » ; un retour à la moyenne dit « ça monte trop ».
Moyennés dans le même score, ils ne se complètent pas : ils s'annulent. Le
résultat serait un zéro permanent, pas une synthèse. D'où un interrupteur et non
des cases à cocher communes.

Conséquence de la même logique, l'échelle de pondération diffère : `momentum.py`
s'interdit les signaux `±2` sur ses lectures contrariennes, pour qu'un excès de
RSI n'annule pas les critères de tendance du même indicateur. Dans
`anticipation.py`, il n'y a rien à annuler — tous les critères sont de même
nature — et brider l'échelle plafonnerait le score de l'approche à 0,5 en valeur
absolue : « Fortement positif » deviendrait inatteignable et les seuils de
simulation ne voudraient plus rien dire.

### Ce que la mesure en dit — honnêtement

`python diagnostic.py` mesure les deux approches sur exactement les mêmes barres :
12 cryptos × 3 intervalles × 250 barres = **9 000 observations**.

**Premier contrôle : la règle de sélection est-elle respectée ?** C'est la
colonne *Spearman passé* de la feuille « Par indicateur », moyennée sur les trois
intervalles.

| Suiveurs | passé | | Anticipation | passé |
|---|---|---|---|---|
| `STOCH` (le moins lié) | +0,23 | | `DIVERGENCES` | **-0,05** |
| `MM` | +0,50 | | `ESSOUFFLEMENT` | **+0,15** |
| `MACD` | +0,74 | | `ASYMETRIE` | **-0,17** |
| moyenne des 19 | **+0,53** | | `EPUISEMENT` | **-0,17** |
| | | | `RETOUR_MOYENNE` | -0,61 |

Quatre des cinq tiennent dans une bande de ±0,17 : ils ne redécrivent pas le
mouvement, contrairement à tous les suiveurs. `RETOUR_MOYENNE` est l'exception
assumée — un Z-score, c'est le rendement récent au signe près, il ne pouvait pas
en être autrement.

> Ce contrôle a servi immédiatement : dans sa première version, `ESSOUFFLEMENT`
> notait aussi l'accélération (« hausse qui accélère » = positif) et affichait
> **+0,34** au passé. C'était un suiveur de tendance déguisé. Seule la
> décélération porte désormais un signal, et la corrélation est tombée à +0,15.

**Second contrôle : ça rapporte quelque chose ?** C'est la corrélation au
rendement futur **relatif** (écart à la moyenne des cryptos au même instant — la
seule qui ne récompense pas le fait de suivre le marché).

| Horizon | 1d suiv. | 1d antic. | 4h suiv. | 4h antic. | 1h suiv. | 1h antic. |
|---|---|---|---|---|---|---|
| 6 bougies | -0,003 | +0,048 | **+0,056** | -0,010 | -0,021 | +0,010 |
| 12 bougies | 0,000 | +0,082 | **+0,085** | -0,024 | -0,002 | +0,007 |
| 24 bougies | -0,006 | **+0,099** | +0,055 | -0,007 | +0,042 | -0,032 |

**Chaque intervalle a un gagnant différent.** L'anticipation domine en 1d (et de
façon régulière : +0,027 → +0,099 quand l'horizon s'allonge), les suiveurs
dominent en 4h, personne ne gagne en 1h. C'est la signature du **bruit**, pas
d'un effet. Sur des barres qui se recouvrent, 3 000 observations valent quelques
dizaines d'observations indépendantes : rien ici n'atteint le seuil de la preuve.

**Le seul point qui mérite qu'on y revienne** : `ASYMETRIE` est le meilleur des
**27** indicateurs sur cette colonne, à **+0,053** de corrélation relative — plus
du double du meilleur suiveur (`AROON`, +0,022) — tout en étant orthogonal au
passé (-0,17). C'est le troisième moment des rendements : quelque chose que
**aucun** des 20 indicateurs d'origine ne regardait.

**Ce que l'anticipation change vraiment**, en revanche, est mesurable et net :

- elle produit **5 fois moins de signaux forts** (132 contre 420 en 1d au-dessus
  de 0,30) et déclenche **2 à 3 fois moins de trades** — ce qui, vu le poids des
  frais, n'est pas rien ;
- elle est **beaucoup moins directionnelle**. À réglages identiques et sens
  identique, l'achat rapporte -4,9 % en 1d (marché à -44,7 %) contre -18,2 % aux
  suiveurs, mais seulement +3,2 % en 4h (marché à +25,0 %) contre +13,8 %.

Autrement dit : elle amortit dans les deux sens. C'est un **bêta plus faible**,
pas davantage d'information. Utile pour perdre moins, pas pour gagner plus.

### En résumé

L'approche anticipation fait ce pour quoi elle a été construite : elle ne
redécrit pas le passé. Elle **ne prédit pas l'avenir pour autant**. Aucun
réglage ne devrait être choisi sur les chiffres ci-dessus : ils viennent d'une
seule fenêtre de 250 barres, et les choisir reviendrait à épouser le hasard de
cette période. Relancez `diagnostic.py` sur une autre fenêtre avant de croire
quoi que ce soit.

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
- Les indicateurs purement contextuels (`ATR`, `COMPRESSION`, `EFFICIENCE`) sont
  exclus de ces moyennes : leur score étant toujours nul, ils tireraient tous les
  scores vers le neutre. Ils portent l'attribut de classe `contextuel = True`, ce
  qui permet à la simulation de refuser un score de famille qui ne contiendrait
  qu'eux, plutôt que de tourner à vide en annonçant zéro trade.
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
| Historique OHLCV | Binance `/api/v3/klines` | 1000 bougies max par appel ; `SourceDonnees._binance` pagine au-delà pour la simulation |
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

### Les quatre feuilles du classeur

**`Relevés`** — le journal brut, une ligne par crypto et par analyse : horodatage,
échéance, prix, score global, les quatre scores de famille, la couverture en
indicateurs, l'origine (`analyse`, `auto`, `web`, `cli`) et le `statut`
(`En attente` / `Vérifié` / `Expiré`).

**`Vérifications`** — les relevés arrivés à échéance : prix initial et final,
rendement, rendement du lot, rendement relatif, sens prédit, sens réel et
`resultat`.

**`Performance`** — le tableau qui répond à la question, découpé par
regroupement : bilan global, **par tranche de score**, par intervalle, par crypto.

**`Évolution`** — le score global de chaque crypto au fil du temps, en tableau
croisé (horodatage et intervalle en lignes, une colonne par crypto). Sélectionnez
le bloc dans Excel et insérez un graphique en courbes : c'est prêt pour ça.

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

Le bilan des vérifications n'a **pas d'onglet dédié** dans les interfaces : il
vit dans le classeur, que le bouton **Ouvrir le classeur** de la fenêtre
📈 Suivi atteint directement. `python main.py` l'affiche aussi en fin
d'exécution. La simulation répond à la même question de façon plus directe, en
rejouant la stratégie sur le passé au lieu d'attendre que le temps passe.

### Évolution des scores

Un onglet dédié trace la trajectoire de chaque crypto dans le temps — bouton
**📈 Suivi** au bureau (onglet *Évolution des scores*), onglet du même nom sur le
web. Chaque analyse ajoute un point.

Trois réglages :

| Réglage | Choix |
|---|---|
| **Score** | `Global`, `Tendance`, `Momentum`, `Volatilité` ou `Volume` |
| **Intervalle** | ceux présents dans le journal |
| **Cryptos** | cases à cocher, 8 au maximum |

L'intervalle doit être choisi : superposer des scores journaliers et des scores
en 5 minutes sur un même axe mélangerait deux échelles de temps, et deux relevés
simultanés d'une même crypto se marcheraient dessus.

**Ce que le graphique respecte, et pourquoi :**

- **Une crypto garde sa couleur.** Décocher une série ne repeint pas les autres :
  un lecteur qui a appris « BTC est bleu » serait sinon induit en erreur.
- **Huit séries au maximum.** Au-delà, deux teintes deviennent indiscernables
  pour un lecteur daltonien. Le projet ne génère jamais une neuvième couleur, il
  tronque et le signale.
- **Palette vérifiée, pas choisie à l'œil.** Les huit teintes sont validées dans
  les deux modes (écart minimal entre voisines de 9,1 en clair et 8,4 en sombre
  sous simulation protanope). Trois teintes claires passent sous 3:1 de
  contraste, d'où l'étiquetage direct des courbes et le tableau de valeurs sous
  le graphique — l'identité ne repose jamais sur la seule couleur.
- **Échelle fixée à [-1, +1].** Un score vit toujours dans cet intervalle ; une
  échelle qui s'ajusterait ferait paraître spectaculaire une variation de 0,02.
- **La bande grise est la zone neutre.** Entre -0,15 et +0,15, l'application
  n'annonce aucune direction — c'est le seuil qui produit les « Non prédictif »
  de la feuille `Performance` du classeur.

### Simulation historique

Le suivi enregistre les scores et attend que le temps passe. La **simulation**
fait l'inverse : elle remonte le temps, recalcule les scores à chaque barre du
passé et rejoue les allers-retours qu'ils auraient déclenchés. Onglet
*Simulation* de la fenêtre 📈 Suivi, ou onglet du même nom sur le web.

#### Règles du jeu

1. À chaque barre de la fenêtre simulée, le score est recalculé **avec les
   seules données disponibles à cet instant**.
2. Si `|score|` tombe entre le seuil minimum et le seuil maximum et que son sens
   est autorisé, une position s'ouvre au cours de clôture.
3. Elle se referme au **premier motif de sortie rempli** (voir ci-dessous).
4. **Aucune position ne se chevauche** : tant qu'une est ouverte, les signaux
   suivants sont ignorés. C'est ce qui permet de faire travailler un capital
   unique et d'obtenir un « combien j'aurais gagné » qui ait un sens.

Chaque crypto est simulée **indépendamment**, avec la même mise de départ.

#### Les quatre sorties

Une position peut se refermer de quatre façons. Elles sont examinées à **chaque
bougie** qui suit l'entrée, dans cet ordre, et la première qui se déclenche
l'emporte. Mettre une condition à 0 la désactive.

| Motif | Déclencheur | Quand |
|---|---|---|
| **Stop** | la perte atteint le pourcentage demandé | en cours de bougie |
| **Objectif** | le gain atteint le pourcentage demandé | en cours de bougie |
| **Retournement** | le score se retourne de X points contre la position, par rapport à sa valeur d'entrée | à la clôture |
| **Durée** | la durée maximale de détention est atteinte | à la clôture |

Trois choix méritent d'être explicités, parce qu'ils changent le résultat :

- **Le stop et l'objectif se cherchent dans le haut et le bas de la bougie**, pas
  seulement à la clôture. Sinon un stop posé à -3 % ne servirait à rien sur une
  bougie qui plonge de 10 % avant de revenir clôturer à -1 %.
- **Quand la même bougie touche les deux, le stop l'emporte.** On ne sait pas
  lequel a été atteint en premier ; retenir le pire des deux ne fait jamais
  paraître la stratégie meilleure qu'elle n'est.
- **Si la bougie ouvre déjà au-delà du stop, la sortie se fait à l'ouverture.**
  Le prix demandé n'existait plus. En pratique le cas est rare : le marché crypto
  est continu, la clôture d'une bougie est l'ouverture de la suivante.

Le **retournement** porte sur le score choisi, pas sur le prix : si vous simulez
le momentum et qu'il passe de +0,60 à +0,28, il s'est retourné de 0,32 point et
une position à seuil 0,30 est coupée. Le score vivant dans [-1, +1], 0,30 est
déjà un franc changement d'avis. Pour une vente à découvert, le retournement est
le score qui **remonte**.

Le tableau de résultats indique par quoi chaque position s'est refermée, et une
ligne récapitule la répartition. Ce n'est pas cosmétique : une stratégie qui ne
gagne que par son stop et une autre qui gagne par son signal donnent le même
capital final sans valoir la même chose.

#### Paramètres

| Paramètre | Effet |
|---|---|
| **Mise par crypto** | capital de départ, en dollars |
| **Intervalle** | taille des bougies (`1d` … `1m`) |
| **Périodes simulées** | nombre de barres passées rejouées — aucun plafond : au-delà de 1000, l'historique est téléchargé en plusieurs appels paginés |
| **Approche** | `Suiveuse` (20 indicateurs) ou `Anticipation` (7) — décide de quels indicateurs composent le score simulé |
| **Score utilisé** | `Global`, `Tendance`, `Momentum`, `Volatilité` ou `Volume`. Côté anticipation, `Tendance` ne contient qu'un indicateur contextuel et est donc refusé |
| **Sens autorisés** | croissant (achat), décroissant (vente à découvert), ou les deux |
| **Seuils min / max** | plage sur la **valeur absolue** du score ; hors de cette plage, aucune position |
| **Durée maximale de détention** | en bougies ; referme ce qui n'a pas été coupé avant |
| **Retournement du score** | en points de score ; `0` désactive |
| **Objectif de gain** | en % du prix d'entrée ; `0` désactive |
| **Stop de perte** | en % du prix d'entrée ; `0` désactive |
| **Frais par transaction** | comptés à l'entrée **et** à la sortie |
| **Cryptos** | cases à cocher |

Les frais ne sont pas un détail : sans eux, une stratégie qui multiplie les
allers-retours paraît toujours rentable. C'est le biais le plus courant d'un
backtest naïf. Sur un exemple à 50 allers-retours, les passer de 0 à 0,10 %
coûte environ 4 points de rendement.

#### Fuseau horaire

Toutes les données de prix (bougies Binance) et tous les horodatages internes
sont en **UTC**. C'est nécessaire : comparer une échéance à une bougie n'a de
sens que si les deux parlent le même référentiel, quel que soit le fuseau de la
machine qui exécute le code.

L'affichage, lui, convertit toujours en **heure de Paris** (gère l'heure
d'été) :

- les colonnes **Entrée** / **Sortie** du détail des trades ;
- l'axe des deux graphiques (étiquetté « Heure (FR) ») — courbe de capital et
  évolution des scores ;
- l'onglet **Évolution** de `evolution()`.

Seul le classeur `suivi_scores.xlsx` (onglets *Relevés*, *Vérifications*,
*Évolution*) garde l'UTC brut — il porte le suffixe **(UTC)** dans ses
en-têtes de colonne pour que ce soit dit, pas deviné.

#### Lire le résultat

| Colonne | Signification |
|---|---|
| Trades | nombre d'allers-retours déclenchés |
| Réussite % | part des trades gagnants |
| Gain % | ce qu'a rapporté la stratégie |
| **Marché %** | ce qu'aurait rapporté un simple achat-conservation sur la même période |
| **Écart %** | `Gain − Marché` — **la seule colonne qui compte vraiment** |

Gagner 8 % quand le marché en a pris 20, c'est avoir perdu 12 points à
s'agiter. L'écart est la mesure honnête.

Le détail des allers-retours porte une colonne **Motif** et la répartition des
sorties est résumée au-dessus du graphique. Deux lectures s'y trouvent :

- **Beaucoup de sorties par stop, peu par durée** : le signal n'a pas le temps
  d'avoir raison, la position est coupée avant. Stop trop serré, ou signal qui
  ne tient pas.
- **Beaucoup de sorties par objectif et un gain qui baisse** : un objectif
  tronque les gagnants sans toucher aux perdants. Sur un exemple à 28 trades,
  poser un objectif à 2 % a fait passer le résultat de +11 % à -2 % : les
  quelques mouvements qui portaient tout le rendement ont été coupés à 2 %,
  pendant que les pertes couraient jusqu'à la durée maximale. Un objectif se
  pose avec un stop, pas seul.

#### Pas d'information future

Le postulat qui rend la simulation praticable — et honnête — est que tous les
indicateurs du projet sont **causaux** : moyennes glissantes, moyennes
exponentielles, décalages vers le passé, boucles Supertrend et SAR. La valeur en
barre *t* est donc identique qu'elle ait été calculée sur la série complète ou
sur la série tronquée à *t*. Le projet calcule donc une fois, puis interprète
chaque barre en tronquant : cinq fois plus rapide qu'un recalcul complet, sans
qu'aucune donnée future ne puisse remonter dans le passé.

Un test (`analyser_serie` vs `analyser` sur série tronquée) vérifie que les deux
chemins donnent **exactement** les mêmes critères, sur les 27 indicateurs des deux
approches et des dizaines de positions.

Le cas délicat est l'OBV de `DIVERGENCES` : c'est un cumul depuis le début de la
série, donc une série tronquée le décale d'une constante. La détection de
divergence ne compare que des extrêmes entre eux, un décalage constant ne change
donc rien — et le test le confirme.

Compter environ **4 secondes par crypto** pour 250 périodes et 20 indicateurs.
La simulation tourne dans un thread : l'interface reste utilisable.

### Précautions de lecture

- Un taux de réussite se juge par rapport à **50 %**, pas par rapport à 0.
- Les cryptos d'un même lot montent et descendent ensemble : 20 vérifications
  issues d'une seule analyse ne sont pas 20 observations indépendantes, plutôt
  deux ou trois. Il faut **beaucoup d'analyses étalées dans le temps** avant que
  les chiffres veuillent dire quoi que ce soit.
- Les intervalles courts font grossir le classeur vite : c'est voulu, ils
  permettent d'accumuler des vérifications en quelques heures au lieu de
  quelques semaines.
- **Une simulation n'est pas une promesse.** Elle est rejouée sur une seule
  trajectoire passée. Essayer vingt jeux de paramètres et garder le meilleur,
  c'est choisir celui qui collait le mieux au hasard de cette période — pas
  celui qui marchera demain. Le réglage qui gagne sur les 150 dernières barres
  perd souvent sur les 150 précédentes : vérifiez-le en changeant la fenêtre.
- L'entrée se fait au **cours de clôture** de la bougie qui produit le signal.
  En pratique on entrerait à l'ouverture suivante, avec un écart. La simulation
  est donc légèrement optimiste, en plus des frais.
- Le stop et l'objectif sont supposés remplis **au prix exact demandé** dès que
  la bougie le touche. Un vrai carnet d'ordres ne le garantit pas : sur un
  mouvement violent, un stop passe plus bas. La simulation est là encore
  légèrement optimiste.
- **Chaque condition de sortie ajoutée est un paramètre de plus à régler**, donc
  une occasion de plus de coller au hasard de la période testée. Quatre sorties
  actives et douze réglages, c'est assez pour faire briller n'importe quelle
  fenêtre de 150 barres. Changez la fenêtre avant de croire au résultat.

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
