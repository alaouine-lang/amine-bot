# Suivi du projet : système de swing trading

Ce fichier permet de reprendre le travail à tout moment. Il est mis à jour à chaque étape.

## Cahier des charges
- **Marchés :** actions US, ETF sectoriels, matières premières (via ETF).
- **Horizon :** swing trading, positions de quelques jours à quelques semaines.
- **Budget API Claude :** 150 $/mois au départ.
- **Rôle de l'utilisateur :** arbitrage final uniquement. Le système propose quoi acheter ou vendre, quand entrer et sortir, le stop et l'objectif.
- **Validation :** backtest des règles quantitatives, puis paper trading pour la partie IA (les jugements d'un modèle ne se backtestent pas de façon fiable).
- **Exécution :** sur le PC de l'utilisateur (Windows, Python 3.13).

## Architecture cible
1. **Contexte :** régime macro (FRED), calendrier économique, événements, thèmes émergents (signaux faibles).
2. **Sélection :** screener quantitatif → agents Actualités (Haiku), Technique (Sonnet), Macro (Sonnet) → Comité (Opus).
3. **Sorties :** propositions d'entrée et alertes de sortie → Telegram → décision de l'utilisateur.
4. **Mémoire :** journal des signaux et mesure mensuelle des performances.

## Avancement

### Phase 1 : socle quantitatif (EN COURS)
- [x] Module `swing/` séparé du bot Telegram (`main.py` reste inchangé, hors sécurité)
- [x] Univers : ~180 actions US, ETF sectoriels, matières premières, obligations (`swing/universe.py`)
- [x] Téléchargement des cours Yahoo Finance + cache CSV (`swing/data.py`)
- [x] Indicateurs : MM, RSI, ATR, ROC, volume relatif (`swing/indicators.py`)
- [x] 2 stratégies : `momentum` (cassure de plus haut) et `pullback` (repli en tendance) (`swing/strategies.py`)
- [x] Moteur de backtest de portefeuille : exécution à l'ouverture J+1, frais, slippage, stops avec gaps, taille par le risque (`swing/backtest.py`)
- [x] Séparation entraînement / test (`--split`)
- [x] Screener du soir + journal des signaux (`swing/screener.py`)
- [x] 14 tests automatiques (`tests/test_swing.py`)
- [x] Token Telegram retiré du code (`main.py`)
- [x] Exposition mesurée : momentum ~80 % investi, pullback ~59 % → l'argent qui dort n'est PAS la cause principale
- [x] Optimiseur sur la période d'entraînement uniquement : `python -m swing optimize --strategy momentum`
- [ ] Stratégies supplémentaires : force relative sectorielle, rotation, sortie sur objectif
- [ ] Module macro FRED (régime croissance/inflation) — nécessite une clé FRED gratuite

### Phase 2 : agents IA — à faire
### Phase 3 : paper trading + journal de performance — à faire
### Phase 4 : passage en réel (si les mesures sont bonnes) — à faire

## Résultats des premiers backtests (26/11/2026)
Univers actuel de 181 actifs, capital 100 000 $, risque 1 %/trade, max 8 positions.
Entraînement 2012-2020, test 2021-25/11/2026.

| | Momentum (test) | Pullback (test) | S&P 500 (test) |
|---|---|---|---|
| Rendement annuel | 4,2 % | 3,7 % | 13,4 % |
| Sharpe | 0,34 | 0,34 | 0,83 |
| Perte max | -24,9 % | -27,8 % | -24,5 % |

**Conclusion :** les deux stratégies de base ne battent pas le S&P 500 sur la période de test.
Elles ne doivent PAS être utilisées telles quelles. Pistes : capital trop peu investi
(à mesurer), stop suiveur trop serré, filtre de marché, combinaison des stratégies.
Rappel : l'univers actuel crée un biais du survivant qui rend ces chiffres optimistes.

Situation de marché au 25/11/2026 : SPY (716,7) sous sa MM200 (730,8) → filtre baissier actif, aucun signal.

## Diagnostic du 27/11/2026
**Optimisation momentum** (24 réglages, classés sur 2012-2020) : le meilleur en entraînement
(Sharpe 1,02) tombe à 0,24 en test → **surapprentissage**. Aucun réglage ne bat le SPY en test.
Seule tendance robuste : stops plus larges (5 ATR) → Sharpe test 0,51-0,55, perte max -15 à -19 %.

**Année par année** (momentum, stop 5 ATR, 12 positions, vs SPY) :
- Protège dans les baisses : 2022 -3,6 % (SPY -18,2 %), 2018 -0,5 % (SPY -4,6 %).
- Gros retard dans les hausses : 2019 +11,8 % (SPY +31,2 %), 2023 +4,8 % (+26,2 %), 2024 +2,9 % (+24,9 %).
- Hypothèse : beaucoup d'allers-retours coupés par les stops et retard sur les hausses
  très concentrées sur quelques géants (à vérifier).

**Prochaine étape proposée :**
1. Stratégie de **rotation** : chaque mois, détenir les N actifs les plus forts sur 6-12 mois,
   avec un repli vers obligations/or/cash si le marché est baissier (« dual momentum »).
2. Structure **cœur + satellites** : un cœur indiciel (SPY) quand le marché est haussier,
   et des positions swing en satellite. Objectif : suivre les hausses ET protéger dans les baisses.
3. Comparer tout cela au SPY en rendement ET en risque (perte max, Sharpe).

## Commandes (sur le PC, dans le dossier du dépôt)
```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r swing\requirements.txt
python -m swing download
python -m swing backtest --strategy momentum --start 2012-01-01 --split 2021-01-01
python -m swing optimize --strategy momentum
python -m swing screen --strategy momentum --capital 130000
python -m pytest -q tests
```

## Actions en attente côté utilisateur
- [x] Ancien token Telegram révoqué via @BotFather, nouveau token créé (27/11/2026).
- [x] `TELEGRAM_TOKEN` et `CHAT_ID` ajoutés dans les variables Railway (27/11/2026).
- [ ] Créer une clé FRED gratuite (pour le module macro).
