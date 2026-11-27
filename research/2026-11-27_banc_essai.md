# Banc d'essai des stratégies — coûts normaux

Entraînement 2008-2020 · test 2021 → 2026-11-25 · critères : rendement ≥ SPY - 2 pts, Sharpe > SPY, perte max ≤ 20 % (en test).

| Variante | Ent. rendement | Ent. Sharpe | Ent. perte max | Test rendement | Test Sharpe | Test perte max | Perte max 2008-2026 | Critères |
|---|---|---|---|---|---|---|---|---|
| **SPY (référence)** | 9.8 % | 0.55 | -51.9 % | 13.4 % | 0.83 | -24.5 % | -51.9 % | |
| spy_timing | 6.9 % | 0.49 | -26.2 % | 10.1 % | 0.76 | -19.6 % | -26.2 % | 1/3 (rendement, sharpe ✗) |
| spy_timing_inverse | 5.7 % | 0.41 | -31.2 % | 5.5 % | 0.45 | -26.5 % | -31.2 % | 0/3 (rendement, sharpe, perte_max ✗) |
| etf_k3 | 3.6 % | 0.27 | -44.8 % | 9.5 % | 0.46 | -44.2 % | -44.8 % | 0/3 (rendement, sharpe, perte_max ✗) |
| etf_k5_cap1 | 3.8 % | 0.30 | -35.8 % | 8.9 % | 0.52 | -29.4 % | -35.8 % | 0/3 (rendement, sharpe, perte_max ✗) |
| etf_k5_cap1_vol12 | 3.8 % | 0.35 | -31.4 % | 5.9 % | 0.51 | -20.7 % | -31.4 % | 0/3 (rendement, sharpe, perte_max ✗) |
| etf_k5_cap1_vol12_lev15 | 3.1 % | 0.29 | -39.1 % | 5.5 % | 0.48 | -22.6 % | -39.1 % | 0/3 (rendement, sharpe, perte_max ✗) |
| stk_k10 | 25.2 % | 1.10 | -32.1 % | 17.1 % | 0.69 | -28.3 % | -32.1 % | 1/3 (sharpe, perte_max ✗) |
| stk_k10_cap2 | 24.5 % | 1.12 | -32.8 % | 16.9 % | 0.82 | -25.6 % | -32.8 % | 1/3 (sharpe, perte_max ✗) |
| stk_k5_cap1 | 32.6 % | 1.26 | -33.0 % | 21.3 % | 0.89 | -26.9 % | -33.0 % | 2/3 (perte_max ✗) |
| stk_k15_cap3 | 20.0 % | 1.00 | -32.9 % | 14.4 % | 0.77 | -23.3 % | -32.9 % | 1/3 (sharpe, perte_max ✗) |
| stk_k10_cap2_vol12 | 14.3 % | 1.03 | -20.3 % | 9.1 % | 0.73 | -15.2 % | -20.3 % | 1/3 (rendement, sharpe ✗) |
| stk_k10_cap2_vol15_lev15 | 17.6 % | 1.01 | -25.4 % | 11.0 % | 0.72 | -19.7 % | -25.4 % | 1/3 (rendement, sharpe ✗) |
| stk_k10_cap2_inverse | 23.1 % | 1.05 | -29.6 % | 12.0 % | 0.63 | -32.1 % | -32.1 % | 1/3 (sharpe, perte_max ✗) |
| stk_k10_cap2_short | 18.0 % | 0.72 | -54.4 % | 12.4 % | 0.61 | -37.1 % | -54.4 % | 1/3 (sharpe, perte_max ✗) |
| all_k10_cap2_vol12 | 14.0 % | 1.02 | -21.2 % | 7.8 % | 0.64 | -15.1 % | -21.2 % | 1/3 (rendement, sharpe ✗) |
| swing_momentum | 6.3 % | 0.63 | -16.5 % | 5.6 % | 0.51 | -14.6 % | -16.5 % | 1/3 (rendement, sharpe ✗) |
| coeur50_spytiming+stk_k10_cap2 | 15.6 % | 0.89 | -29.4 % | 13.7 % | 0.85 | -21.1 % | -29.4 % | 2/3 (perte_max ✗) |
| coeur50_spytiming+swing | 6.8 % | 0.62 | -19.0 % | 8.0 % | 0.74 | -15.3 % | -19.0 % | 1/3 (rendement, sharpe ✗) |
| coeur50_spytiming+etf_k5_cap1 | 5.4 % | 0.40 | -28.7 % | 9.7 % | 0.67 | -21.6 % | -28.7 % | 0/3 (rendement, sharpe, perte_max ✗) |
| tiers_spytiming+stk+etf | 11.6 % | 0.71 | -30.1 % | 12.2 % | 0.76 | -19.1 % | -30.1 % | 2/3 (sharpe ✗) |

## Choix sur l'entraînement uniquement
Parmi les variantes dont la perte max d'entraînement respecte -20 % (2 sur 20), la meilleure en Sharpe d'entraînement est **swing_momentum** (Sharpe ent. 0.63).
En test, elle obtient : rendement 5.6 %, Sharpe 0.51, perte max -14.6 % → critères : rendement ✗, sharpe ✗, perte_max ✅
