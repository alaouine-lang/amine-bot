"""Tests du système swing sur données synthétiques (aucun accès internet)."""

import math

import numpy as np
import pandas as pd
import pytest

from swing import indicators as ind
from swing.backtest import BacktestConfig, compute_metrics, run_backtest
from swing.screener import screen
from swing.strategies import MomentumBreakout, Strategy, TrendPullback


def make_df(closes, start="2020-01-01", spread=0.01, volume=1_000_000):
    closes = np.asarray(closes, dtype=float)
    idx = pd.bdate_range(start, periods=len(closes))
    opens = np.concatenate([[closes[0]], closes[:-1]])
    return pd.DataFrame(
        {
            "Open": opens,
            "High": np.maximum(opens, closes) * (1 + spread),
            "Low": np.minimum(opens, closes) * (1 - spread),
            "Close": closes,
            "Volume": np.full(len(closes), volume, dtype=float),
        },
        index=idx,
    )


# ---------- Indicateurs ----------

def test_sma_and_roc():
    s = pd.Series([1.0, 2, 3, 4, 5])
    assert ind.sma(s, 3).tolist()[2:] == [2.0, 3.0, 4.0]
    assert math.isnan(ind.sma(s, 3).iloc[1])
    assert ind.roc(s, 2).iloc[-1] == pytest.approx(5 / 3 - 1)


def test_rsi_bounds_and_extremes():
    up = pd.Series(np.arange(1, 50, dtype=float))
    down = pd.Series(np.arange(50, 1, -1, dtype=float))
    noisy = pd.Series(100 + np.random.default_rng(0).normal(0, 1, 300).cumsum())
    assert ind.rsi(up, 14).iloc[-1] == pytest.approx(100.0)
    assert ind.rsi(down, 14).iloc[-1] == pytest.approx(0.0)
    r = ind.rsi(noisy, 14).dropna()
    assert ((r >= 0) & (r <= 100)).all()


def test_atr_positive():
    df = make_df(100 + np.random.default_rng(1).normal(0, 1, 100).cumsum())
    a = ind.atr(df, 14).dropna()
    assert (a > 0).all()


def test_volume_ratio_uses_previous_days_only():
    vol = pd.Series([100.0] * 20 + [300.0])
    assert ind.volume_ratio(vol, 20).iloc[-1] == pytest.approx(3.0)


# ---------- Moteur de backtest ----------

class ScriptedStrategy(Strategy):
    """Stratégie de test : achat le jour `buy_on`, vente le jour `sell_on` (indices)."""

    def __init__(self, buy_on, sell_on=None, stop_atr_mult=0.5):
        super().__init__(name="scripted", stop_atr_mult=stop_atr_mult)
        self.buy_on, self.sell_on = buy_on, sell_on

    def compute(self, df, bench_close):
        n = len(df)
        entry = np.zeros(n, bool)
        exit_ = np.zeros(n, bool)
        if df["Close"].equals(bench_close):  # on ne trade pas l'indice de référence dans ces tests
            return pd.DataFrame({"entry": entry, "exit": exit_, "score": 1.0, "atr": 1.0}, index=df.index)
        entry[self.buy_on] = True
        if self.sell_on is not None:
            exit_[self.sell_on] = True
        return pd.DataFrame(
            {"entry": entry, "exit": exit_, "score": 1.0, "atr": 1.0}, index=df.index
        )


def zero_cost_config(**kw):
    base = dict(commission_bps=0.0, slippage_bps=0.0, min_price=0.0, risk_per_trade=1.0, max_position_pct=1.0)
    base.update(kw)
    return BacktestConfig(**base)


def test_entry_executes_at_next_open_not_same_close():
    closes = [10, 10, 10, 20, 20, 20, 20, 20]
    data = {"SPY": make_df([100] * 8), "AAA": make_df(closes)}
    # Signal à la clôture du jour 3 (prix 20) : l'achat doit se faire à l'ouverture du jour 4 (20),
    # jamais au prix du jour du signal ni avant.
    res = run_backtest(data, ScriptedStrategy(buy_on=3, sell_on=6), "SPY", zero_cost_config())
    trade = [t for t in res.trades if t.ticker == "AAA"][0]
    assert trade.entry_date == data["AAA"].index[4]
    assert trade.entry_price == pytest.approx(20.0)
    assert trade.exit_date == data["AAA"].index[7]


def test_profitable_trade_updates_equity():
    closes = [10, 10, 10, 10, 12, 14, 16, 16]
    data = {"SPY": make_df([100] * 8), "AAA": make_df(closes)}
    res = run_backtest(data, ScriptedStrategy(buy_on=2, sell_on=6), "SPY", zero_cost_config(initial_capital=1000))
    trade = res.trades[0]
    assert trade.entry_price == pytest.approx(10.0)  # ouverture du jour 3 = clôture du jour 2
    assert trade.exit_price == pytest.approx(16.0)   # ouverture du jour 7 = clôture du jour 6
    assert res.equity.iloc[-1] == pytest.approx(1000 + trade.shares * 6.0)


def test_stop_loss_triggers_and_gap_fills_below_stop():
    closes = [10, 10, 10, 10, 6, 6, 6, 6]  # gap baissier à l'ouverture du jour 5
    df = make_df(closes, spread=0.0)
    df.iloc[5, df.columns.get_loc("Open")] = 6.0
    data = {"SPY": make_df([100] * 8), "AAA": df}
    strat = ScriptedStrategy(buy_on=2, stop_atr_mult=2.0)  # stop = 10 - 2 × 1 = 8
    res = run_backtest(data, strat, "SPY", zero_cost_config(initial_capital=1000))
    trade = res.trades[0]
    assert trade.exit_reason == "stop"
    # le jour 4, le plus bas (6) passe sous le stop 8 → sortie au stop
    assert trade.exit_price == pytest.approx(8.0)


def test_gap_below_stop_exits_at_open():
    closes = [10, 10, 10, 10, 10, 5, 5]
    df = make_df(closes, spread=0.0)
    data = {"SPY": make_df([100] * 7), "AAA": df}
    strat = ScriptedStrategy(buy_on=2, stop_atr_mult=2.0)  # stop 8 ; ouverture jour 5 = 10, jour 6 = 5
    df.iloc[5, df.columns.get_loc("Open")] = 5.0
    df.iloc[5, df.columns.get_loc("Low")] = 5.0
    res = run_backtest(data, strat, "SPY", zero_cost_config(initial_capital=1000))
    trade = res.trades[0]
    assert trade.exit_reason == "stop"
    assert trade.exit_price == pytest.approx(5.0)  # gap : sortie à l'ouverture, sous le stop


def test_costs_reduce_result():
    closes = [10, 10, 10, 10, 12, 14, 16, 16]
    data = {"SPY": make_df([100] * 8), "AAA": make_df(closes)}
    free = run_backtest(data, ScriptedStrategy(2, 6), "SPY", zero_cost_config(initial_capital=1000))
    paid = run_backtest(
        data, ScriptedStrategy(2, 6), "SPY", zero_cost_config(initial_capital=1000, commission_bps=10, slippage_bps=10)
    )
    assert paid.equity.iloc[-1] < free.equity.iloc[-1]


def test_max_positions_respected():
    closes = [10] * 10
    data = {"SPY": make_df([100] * 10)}
    for k in range(5):
        data[f"T{k}"] = make_df(closes)
    cfg = zero_cost_config(max_positions=2, risk_per_trade=0.01, max_position_pct=0.1)
    res = run_backtest(data, ScriptedStrategy(buy_on=2), "SPY", cfg)
    stock_trades = [t for t in res.trades if t.ticker != "SPY"]
    assert len(stock_trades) == 2


def test_metrics_basic():
    idx = pd.bdate_range("2020-01-01", periods=253)
    eq = pd.Series(np.linspace(100, 110, 253), index=idx)
    m = compute_metrics(eq, [])
    assert m["rendement_total"] == pytest.approx(0.10)
    assert m["max_drawdown"] == pytest.approx(0.0)


# ---------- Stratégies réelles sur données synthétiques ----------

def trending_market(n=600, seed=0):
    rng = np.random.default_rng(seed)
    bench = 100 * np.exp(np.cumsum(rng.normal(0.0006, 0.008, n)))
    strong = 50 * np.exp(np.cumsum(rng.normal(0.0012, 0.015, n)))
    weak = 50 * np.exp(np.cumsum(rng.normal(-0.0008, 0.015, n)))
    return {"SPY": make_df(bench), "STRONG": make_df(strong), "WEAK": make_df(weak)}


@pytest.mark.parametrize("strategy", [MomentumBreakout(), TrendPullback()])
def test_strategies_run_without_lookahead(strategy):
    data = trending_market()
    full = strategy.compute(data["STRONG"], data["SPY"]["Close"])
    # Recalculer sur des données tronquées doit donner les mêmes signaux passés
    cut = 450
    truncated = {k: v.iloc[:cut] for k, v in data.items()}
    partial = strategy.compute(truncated["STRONG"], truncated["SPY"]["Close"])
    pd.testing.assert_series_equal(full["entry"].iloc[:cut], partial["entry"], check_names=False)
    pd.testing.assert_series_equal(full["exit"].iloc[:cut], partial["exit"], check_names=False)
    res = run_backtest(data, strategy, "SPY", BacktestConfig())
    assert len(res.equity) == len(data["SPY"])
    assert (res.equity > 0).all()


def test_screener_returns_valid_proposals():
    data = trending_market(seed=3)
    proposals = screen(data, MomentumBreakout(min_volume_ratio=0.0), capital=100_000)
    for p in proposals:
        assert p.stop < p.close
        assert p.position_value <= 20_000 + 1e-6


def test_optimizer_ranks_on_training_only():
    from swing.optimize import optimize

    data = trending_market(n=700, seed=5)
    split = data["SPY"].index[450].date().isoformat()
    grid = {"stop_atr_mult": [2.0, 4.0], "cfg.max_positions": [1, 2]}
    cands = optimize(data, "momentum", split=split, start=None, grid=grid, min_trades=0)
    assert len(cands) == 4
    sharpes = [c.train.get("sharpe", float("-inf")) for c in cands]
    finite = [s for s in sharpes if s == s]
    assert finite == sorted(finite, reverse=True)
    assert all(c.train.get("fin", split) <= split for c in cands)


# ---------- Moteur de rotation ----------

def _flat_data(n=400):
    idx = pd.bdate_range("2015-01-01", periods=n)
    up = 100 * np.exp(np.linspace(0, 0.5, n))
    flat = np.full(n, 50.0)
    def df(c):
        return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": 1e6}, index=idx)
    return {"SPY": df(up), "UP": df(up * 0.5), "FLAT": df(flat), "TLT": df(flat), "IEF": df(flat), "GLD": df(flat)}


def test_rotation_picks_rising_asset_and_costs_apply():
    from swing.portfolio import CostConfig, RotationConfig, run_rotation

    data = _flat_data()
    cfg = RotationConfig(risk_assets=["UP", "FLAT"], top_k=1)
    res = run_rotation(data, cfg, CostConfig(initial_capital=10_000, trade_cost_bps=0.0))
    w = res.weights.iloc[-1]
    assert w["UP"] == pytest.approx(1.0, abs=1e-6)
    assert w["FLAT"] == pytest.approx(0.0)
    paid = run_rotation(data, cfg, CostConfig(initial_capital=10_000, trade_cost_bps=50.0))
    assert paid.equity.iloc[-1] < res.equity.iloc[-1]


def test_leverage_costs_margin_interest():
    from swing.portfolio import CostConfig, RotationConfig, run_rotation

    data = _flat_data()
    # actif plat avec levier 2 : le capital doit baisser du coût du crédit
    for t in ("UP", "SPY"):
        data[t] = data["FLAT"].copy()
    cfg = RotationConfig(risk_assets=["FLAT"], top_k=1, abs_momentum=False, market_filter=False, max_leverage=2.0)
    res = run_rotation(data, cfg, CostConfig(initial_capital=10_000, trade_cost_bps=0.0, margin_rate=0.10))
    assert res.equity.iloc[-1] < 10_000


def test_inverse_moves_opposite_to_spy():
    from swing.portfolio import INVERSE, build_panel

    data = _flat_data(50)
    _, close = build_panel(data, inverse_fee=0.0)
    r_spy = close["SPY"].pct_change().iloc[1:]
    r_inv = close[INVERSE].pct_change().iloc[1:]
    assert np.allclose(r_inv, -r_spy, atol=1e-9)


def test_clean_spikes_fixes_one_day_error_but_keeps_real_crash():
    from swing.data import clean_spikes

    idx = pd.bdate_range("2020-01-01", periods=6)
    spike = pd.DataFrame({c: [20, 20, 13, 20, 20, 20] for c in ["Open", "High", "Low", "Close"]}, index=idx, dtype=float)
    spike["Volume"] = 1.0
    assert clean_spikes(spike)["Close"].iloc[2] == pytest.approx(20.0)
    crash = spike.copy()
    crash[["Open", "High", "Low", "Close"]] = [[20] * 4, [20] * 4, [13] * 4, [13] * 4, [13] * 4, [13] * 4]
    assert clean_spikes(crash)["Close"].iloc[2] == pytest.approx(13.0)
