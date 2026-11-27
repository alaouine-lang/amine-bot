"""Recherche de paramètres sur la période d'ENTRAÎNEMENT uniquement.

Méthode :
  1. on teste toutes les combinaisons de la grille sur la période d'entraînement ;
  2. on les classe selon le ratio de Sharpe d'entraînement (avec un nombre minimum de trades) ;
  3. on affiche ENSUITE le résultat sur la période de test, sans s'en servir pour choisir.

Si le meilleur réglage d'entraînement s'effondre en test, c'est du surapprentissage :
le réglage colle au passé et ne vaut rien pour l'avenir.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, replace

import pandas as pd

from .backtest import BacktestConfig, run_backtest
from .strategies import get_strategy

GRIDS: dict[str, dict[str, list]] = {
    "momentum": {
        "breakout_window": [20, 55, 100],
        "stop_atr_mult": [2.5, 3.5, 5.0],
        "fast_sma": [50, 100],
        "cfg.max_positions": [8, 12],
    },
    "pullback": {
        "rsi_entry": [10.0, 20.0, 30.0],
        "max_hold_days": [5, 10, 20],
        "stop_atr_mult": [2.0, 3.0, 4.0],
        "cfg.max_positions": [8, 12],
    },
}


@dataclass
class Candidate:
    params: dict
    train: dict
    test: dict


def _split(params: dict) -> tuple[dict, dict]:
    strat = {k: v for k, v in params.items() if not k.startswith("cfg.")}
    cfg = {k[4:]: v for k, v in params.items() if k.startswith("cfg.")}
    return strat, cfg


def optimize(
    data: dict[str, pd.DataFrame],
    strategy_name: str,
    split: str,
    start: str = "2012-01-01",
    end: str | None = None,
    base_config: BacktestConfig | None = None,
    grid: dict[str, list] | None = None,
    min_trades: int = 50,
    benchmark: str = "SPY",
    progress=None,
) -> list[Candidate]:
    grid = grid or GRIDS[strategy_name]
    base = base_config or BacktestConfig()
    keys = list(grid)
    combos = list(itertools.product(*(grid[k] for k in keys)))
    out: list[Candidate] = []
    for n, values in enumerate(combos, 1):
        params = dict(zip(keys, values))
        strat_kw, cfg_kw = _split(params)
        strategy = get_strategy(strategy_name, **strat_kw)
        cfg = replace(base, **cfg_kw)
        # Un seul backtest continu, découpé ensuite : les positions ouvertes fin 2020
        # sont comptées dans la période où elles ont été ouvertes.
        res = run_backtest(data, strategy, benchmark, cfg, start=start, end=end)
        out.append(Candidate(params, res.metrics(end=split), res.metrics(start=split)))
        if progress:
            progress(n, len(combos))

    def key(c: Candidate) -> float:
        s = c.train.get("sharpe", float("nan"))
        if c.train.get("nb_trades", 0) < min_trades or s is None or math.isnan(s):
            return -math.inf
        return s

    out.sort(key=key, reverse=True)
    return out
