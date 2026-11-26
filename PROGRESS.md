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
- [ ] Mesurer l'exposition (part du capital investie) et le stop de momentum (1000 sorties sur 1078 par le stop)
- [ ] Optimisation des paramètres sur la période d'entraînement uniquement (walk-forward)
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

## Commandes (sur le PC, dans le dossier du dépôt)
```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r swing\requirements.txt
python -m swing download
python -m swing backtest --strategy momentum --start 2012-01-01 --split 2021-01-01
python -m swing screen --strategy momentum --capital 130000
python -m pytest -q tests
```

## Actions en attente côté utilisateur
- [ ] **Révoquer l'ancien token Telegram** via @BotFather (il reste visible dans l'historique git), puis créer un nouveau token.
- [ ] Ajouter `TELEGRAM_TOKEN` et `CHAT_ID` dans les variables Railway (le bot refuse de démarrer sans).
- [ ] Créer une clé FRED gratuite (pour le module macro).
