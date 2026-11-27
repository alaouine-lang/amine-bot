"""Banc d'essai : teste toutes les variantes de stratégies et les juge sur les critères de l'utilisateur.

Critères (définis le 27/11/2026, objectif « mieux que le S&P 500, moins risqué ») :
  1. Rendement annuel en test ≥ rendement du SPY - 2 points
  2. Ratio de Sharpe en test > Sharpe du SPY
  3. Perte maximale ≤ 20 % en test
  + information : perte maximale sur toute la période, crise de 2008 incluse

Méthode : entraînement 2008-2020, test 2021 → aujourd'hui. Le choix d'une variante
« recommandée » se fait sur l'ENTRAÎNEMENT uniquement ; le test sert de vérification.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import pandas as pd

from . import universe as U
from .backtest import BacktestConfig, compute_metrics, run_backtest
from .portfolio import CostConfig, RotationConfig, blend, run_rotation
from .strategies import get_strategy

START = "2008-01-01"
SPLIT = "2021-01-01"
TRAIN_END = "2020-12-31"
MAX_DD = -0.20
CAGR_TOLERANCE = 0.02

ETF_RISK = U.ETFS["index"] + U.ETFS["sectors"] + U.ETFS["commodities"]
STOCKS = [t for v in U.STOCKS.values() for t in v]


def rotation_variants() -> dict[str, RotationConfig]:
    v = {
        "spy_timing": RotationConfig(risk_assets=["SPY"], top_k=1, market_filter=False),
        "spy_timing_inverse": RotationConfig(risk_assets=["SPY"], top_k=1, bear_mode="inverse", bear_weight=0.5),
        "etf_k3": RotationConfig(risk_assets=ETF_RISK, top_k=3),
        "etf_k5_cap1": RotationConfig(risk_assets=ETF_RISK, top_k=5, max_per_group=1),
        "etf_k5_cap1_vol12": RotationConfig(risk_assets=ETF_RISK, top_k=5, max_per_group=1, target_vol=0.12),
        "etf_k5_cap1_vol12_lev15": RotationConfig(
            risk_assets=ETF_RISK, top_k=5, max_per_group=1, target_vol=0.12, max_leverage=1.5
        ),
        "stk_k10": RotationConfig(risk_assets=STOCKS, top_k=10),
        "stk_k10_cap2": RotationConfig(risk_assets=STOCKS, top_k=10, max_per_group=2),
        "stk_k5_cap1": RotationConfig(risk_assets=STOCKS, top_k=5, max_per_group=1),
        "stk_k15_cap3": RotationConfig(risk_assets=STOCKS, top_k=15, max_per_group=3),
        "stk_k10_cap2_vol12": RotationConfig(risk_assets=STOCKS, top_k=10, max_per_group=2, target_vol=0.12),
        "stk_k10_cap2_vol15_lev15": RotationConfig(
            risk_assets=STOCKS, top_k=10, max_per_group=2, target_vol=0.15, max_leverage=1.5
        ),
        "stk_k10_cap2_inverse": RotationConfig(
            risk_assets=STOCKS, top_k=10, max_per_group=2, bear_mode="inverse", bear_weight=0.5
        ),
        "stk_k10_cap2_short": RotationConfig(
            risk_assets=STOCKS, top_k=10, max_per_group=2, bear_mode="short_weakest", bear_weight=0.5
        ),
        "all_k10_cap2_vol12": RotationConfig(
            risk_assets=STOCKS + ETF_RISK, top_k=10, max_per_group=2, target_vol=0.12
        ),
    }
    return {name: replace(cfg, name=name) for name, cfg in v.items()}


@dataclass
class Row:
    name: str
    train: dict
    test: dict
    full: dict

    def passes(self, spy_test: dict) -> dict[str, bool]:
        t = self.test
        return {
            "rendement": t.get("cagr", -1) >= spy_test["cagr"] - CAGR_TOLERANCE,
            "sharpe": t.get("sharpe", -1) > spy_test["sharpe"],
            "perte_max": t.get("max_drawdown", -1) >= MAX_DD,
        }


def _row(name: str, equity: pd.Series) -> Row:
    return Row(
        name,
        compute_metrics(equity, [], end=TRAIN_END),
        compute_metrics(equity, [], start=SPLIT),
        compute_metrics(equity, []),
    )


def run_all(data: dict[str, pd.DataFrame], capital: float = 50_000.0, cost_mult: float = 1.0) -> tuple[list[Row], dict]:
    costs = CostConfig(initial_capital=capital, trade_cost_bps=6.0 * cost_mult)
    rows: list[Row] = []
    curves: dict[str, pd.Series] = {}
    bench = None
    for name, cfg in rotation_variants().items():
        res = run_rotation(data, cfg, costs, start=START)
        curves[name] = res.equity
        rows.append(_row(name, res.equity))
        bench = res.benchmark

    # Swing « momentum » (moteur à signaux) avec les réglages les plus robustes du 27/11
    swing = run_backtest(
        data,
        get_strategy("momentum", stop_atr_mult=5.0, breakout_window=20),
        "SPY",
        BacktestConfig(
            initial_capital=capital,
            max_positions=8,
            commission_bps=1.0 * cost_mult,
            slippage_bps=5.0 * cost_mult,
        ),
        start=START,
    )
    curves["swing_momentum"] = swing.equity
    rows.append(_row("swing_momentum", swing.equity))

    # Cœur + satellites : poches indépendantes rééquilibrées chaque mois
    blends = {
        "coeur50_spytiming+stk_k10_cap2": {"spy_timing": 0.5, "stk_k10_cap2": 0.5},
        "coeur50_spytiming+swing": {"spy_timing": 0.5, "swing_momentum": 0.5},
        "coeur50_spytiming+etf_k5_cap1": {"spy_timing": 0.5, "etf_k5_cap1": 0.5},
        "tiers_spytiming+stk+etf": {"spy_timing": 1 / 3, "stk_k10_cap2": 1 / 3, "etf_k5_cap1": 1 / 3},
    }
    for name, parts in blends.items():
        eq = blend({k: (curves[k], w) for k, w in parts.items()}, capital)
        rows.append(_row(name, eq))

    spy = {
        "train": compute_metrics(bench, [], end=TRAIN_END),
        "test": compute_metrics(bench, [], start=SPLIT),
        "full": compute_metrics(bench, []),
    }
    return rows, spy


def _p(x) -> str:
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 100:.1f} %"


def _n(x) -> str:
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.2f}"


def report(rows: list[Row], spy: dict, title: str) -> str:
    lines = [
        f"# {title}",
        "",
        f"Entraînement {START[:4]}-{TRAIN_END[:4]} · test {SPLIT[:4]} → {spy['test'].get('fin', '')} · "
        "critères : rendement ≥ SPY - 2 pts, Sharpe > SPY, perte max ≤ 20 % (en test).",
        "",
        "| Variante | Ent. rendement | Ent. Sharpe | Ent. perte max | Test rendement | Test Sharpe | Test perte max | Perte max 2008-2026 | Critères |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    lines.append(
        f"| **SPY (référence)** | {_p(spy['train']['cagr'])} | {_n(spy['train']['sharpe'])} | {_p(spy['train']['max_drawdown'])} "
        f"| {_p(spy['test']['cagr'])} | {_n(spy['test']['sharpe'])} | {_p(spy['test']['max_drawdown'])} | {_p(spy['full']['max_drawdown'])} | |"
    )
    for r in rows:
        ok = r.passes(spy["test"])
        score = sum(ok.values())
        badge = "✅ 3/3" if score == 3 else f"{score}/3 (" + ", ".join(k for k, v in ok.items() if not v) + " ✗)"
        lines.append(
            f"| {r.name} | {_p(r.train.get('cagr'))} | {_n(r.train.get('sharpe'))} | {_p(r.train.get('max_drawdown'))} "
            f"| {_p(r.test.get('cagr'))} | {_n(r.test.get('sharpe'))} | {_p(r.test.get('max_drawdown'))} "
            f"| {_p(r.full.get('max_drawdown'))} | {badge} |"
        )

    eligible = [r for r in rows if r.train.get("max_drawdown", -1) >= MAX_DD]
    pool = eligible or rows
    pick = max(pool, key=lambda r: r.train.get("sharpe", -math.inf))
    lines += [
        "",
        "## Choix sur l'entraînement uniquement",
        f"Parmi les variantes dont la perte max d'entraînement respecte -20 % ({len(eligible)} sur {len(rows)}), "
        f"la meilleure en Sharpe d'entraînement est **{pick.name}** "
        f"(Sharpe ent. {_n(pick.train.get('sharpe'))}).",
        f"En test, elle obtient : rendement {_p(pick.test.get('cagr'))}, Sharpe {_n(pick.test.get('sharpe'))}, "
        f"perte max {_p(pick.test.get('max_drawdown'))} → critères : "
        + ", ".join(f"{k} {'✅' if v else '✗'}" for k, v in pick.passes(spy["test"]).items()),
    ]
    return "\n".join(lines) + "\n"


def save_report(text: str, stem: str) -> Path:
    out = Path(__file__).resolve().parent.parent / "research"
    out.mkdir(exist_ok=True)
    path = out / f"{date.today().isoformat()}_{stem}.md"
    path.write_text(text, encoding="utf-8")
    return path
