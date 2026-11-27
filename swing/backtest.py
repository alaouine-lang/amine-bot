"""Moteur de backtest de portefeuille, en données journalières.

Règles de simulation (prudentes, pour ne pas embellir les résultats) :
  - Signal calculé à la clôture du jour J, ordre exécuté à l'OUVERTURE de J+1.
  - Frais de courtage et glissement de prix (slippage) appliqués à chaque transaction.
  - Stop vérifié en séance sur le plus bas du jour ; si le titre ouvre sous le stop
    (gap baissier), la sortie se fait au prix d'ouverture, donc PLUS BAS que le stop.
  - Taille de position : on risque un % fixe du capital entre l'entrée et le stop,
    plafonné par un % maximum du capital et par le cash disponible.
  - Long uniquement, sans levier.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .strategies import Strategy

TRADING_DAYS = 252


@dataclass
class BacktestConfig:
    initial_capital: float = 100_000.0
    risk_per_trade: float = 0.01      # 1 % du capital risqué par position
    max_position_pct: float = 0.20    # 20 % du capital maximum par position
    max_positions: int = 8
    commission_bps: float = 1.0       # 0,01 % par transaction
    slippage_bps: float = 5.0         # 0,05 % de glissement par transaction
    min_price: float = 5.0            # ignore les titres sous 5 $


@dataclass
class Trade:
    ticker: str
    entry_date: pd.Timestamp
    entry_price: float
    shares: int
    initial_stop: float
    exit_date: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str | None = None

    @property
    def pnl(self) -> float:
        return (self.exit_price - self.entry_price) * self.shares if self.exit_price is not None else 0.0

    @property
    def return_pct(self) -> float:
        return self.exit_price / self.entry_price - 1.0 if self.exit_price is not None else 0.0

    @property
    def r_multiple(self) -> float:
        """Gain exprimé en multiples du risque initial (1R = distance entrée-stop)."""
        risk = self.entry_price - self.initial_stop
        if self.exit_price is None or risk <= 0:
            return 0.0
        return (self.exit_price - self.entry_price) / risk


@dataclass
class _Position:
    trade: Trade
    stop: float
    highest_close: float
    days_held: int = 0


@dataclass
class BacktestResult:
    strategy: str
    config: BacktestConfig
    equity: pd.Series
    trades: list[Trade]
    benchmark: pd.Series | None = None
    exposure: pd.Series | None = None   # part du capital investie chaque jour (0 à 1)

    def trades_frame(self) -> pd.DataFrame:
        rows = []
        for t in self.trades:
            row = asdict(t)
            row.update(pnl=t.pnl, return_pct=t.return_pct, r_multiple=t.r_multiple)
            rows.append(row)
        return pd.DataFrame(rows)

    def metrics(self, start=None, end=None) -> dict:
        return compute_metrics(self.equity, self.trades, start=start, end=end, exposure=self.exposure)

    def benchmark_metrics(self, start=None, end=None) -> dict:
        if self.benchmark is None:
            return {}
        return compute_metrics(self.benchmark, [], start=start, end=end)


def _arrays(df: pd.DataFrame, sig: pd.DataFrame, calendar: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    d = df.reindex(calendar)
    s = sig.reindex(calendar)
    return {
        "open": d["Open"].to_numpy(float),
        "high": d["High"].to_numpy(float),
        "low": d["Low"].to_numpy(float),
        "close": d["Close"].to_numpy(float),
        "entry": s["entry"].fillna(False).to_numpy(bool),
        "exit": s["exit"].fillna(False).to_numpy(bool),
        "score": s["score"].to_numpy(float),
        "atr": s["atr"].to_numpy(float),
    }


def run_backtest(
    data: dict[str, pd.DataFrame],
    strategy: Strategy,
    benchmark: str = "SPY",
    config: BacktestConfig | None = None,
    start: str | None = None,
    end: str | None = None,
) -> BacktestResult:
    cfg = config or BacktestConfig()
    if benchmark not in data:
        raise ValueError(f"L'indice de référence {benchmark} est absent des données")
    bench_close = data[benchmark]["Close"]

    calendar = data[benchmark].index
    if start:
        calendar = calendar[calendar >= pd.Timestamp(start)]
    if end:
        calendar = calendar[calendar <= pd.Timestamp(end)]
    if len(calendar) < 2:
        raise ValueError("Période de backtest trop courte")

    # Signaux calculés sur tout l'historique (préchauffage des moyennes), puis alignés
    arrays: dict[str, dict[str, np.ndarray]] = {}
    for ticker, df in data.items():
        if df.empty:
            continue
        sig = strategy.compute(df, bench_close)
        arrays[ticker] = _arrays(df, sig, calendar)

    cost = (cfg.commission_bps + cfg.slippage_bps) / 10_000.0
    cash = cfg.initial_capital
    positions: dict[str, _Position] = {}
    pending_entries: list[tuple[float, str]] = []
    pending_exits: set[str] = set()
    last_close: dict[str, float] = {}
    trades: list[Trade] = []
    equity = np.empty(len(calendar))
    invested = np.empty(len(calendar))
    prev_equity = cfg.initial_capital

    def close_position(ticker: str, price: float, day: pd.Timestamp, reason: str) -> None:
        nonlocal cash
        pos = positions.pop(ticker)
        fill = price * (1.0 - cost)
        cash += fill * pos.trade.shares
        pos.trade.exit_date, pos.trade.exit_price, pos.trade.exit_reason = day, fill, reason

    for i, day in enumerate(calendar):
        # 1) Sorties programmées la veille, à l'ouverture
        for ticker in sorted(pending_exits):
            if ticker in positions:
                o = arrays[ticker]["open"][i]
                if not math.isnan(o):
                    close_position(ticker, o, day, "signal")
        pending_exits = {t for t in pending_exits if t in positions}

        # 2) Entrées programmées la veille, à l'ouverture, par score décroissant
        for _score, ticker in sorted(pending_entries, reverse=True):
            if len(positions) >= cfg.max_positions or ticker in positions:
                continue
            a = arrays[ticker]
            o, atr_prev = a["open"][i], a["atr"][i - 1]
            if math.isnan(o) or math.isnan(atr_prev) or atr_prev <= 0:
                continue
            fill = o * (1.0 + cost)
            stop = fill - strategy.stop_atr_mult * atr_prev
            risk_per_share = fill - stop
            if stop <= 0 or risk_per_share <= 0:
                continue
            shares = math.floor(prev_equity * cfg.risk_per_trade / risk_per_share)
            shares = min(shares, math.floor(prev_equity * cfg.max_position_pct / fill), math.floor(cash / fill))
            if shares < 1:
                continue
            cash -= fill * shares
            trade = Trade(ticker, day, fill, shares, stop)
            trades.append(trade)
            positions[ticker] = _Position(trade, stop, highest_close=o)
        pending_entries = []

        # 3) Stops touchés pendant la séance
        for ticker in list(positions):
            pos = positions[ticker]
            a = arrays[ticker]
            o, lo = a["open"][i], a["low"][i]
            if math.isnan(lo):
                continue
            if lo <= pos.stop:
                price = o if (not math.isnan(o) and o < pos.stop) else pos.stop
                close_position(ticker, price, day, "stop")

        # 4) Clôture : mise à jour des stops suiveurs et des signaux pour demain
        for ticker, pos in positions.items():
            a = arrays[ticker]
            c, atr_now = a["close"][i], a["atr"][i]
            if math.isnan(c):
                continue
            pos.days_held += 1
            pos.highest_close = max(pos.highest_close, c)
            if strategy.trailing and not math.isnan(atr_now):
                pos.stop = max(pos.stop, pos.highest_close - strategy.stop_atr_mult * atr_now)
            too_long = strategy.max_hold_days is not None and pos.days_held >= strategy.max_hold_days
            if a["exit"][i] or too_long:
                pending_exits.add(ticker)

        if i < len(calendar) - 1:
            for ticker, a in arrays.items():
                if ticker in positions or not a["entry"][i]:
                    continue
                c = a["close"][i]
                if math.isnan(c) or c < cfg.min_price:
                    continue
                score = a["score"][i]
                pending_entries.append((-math.inf if math.isnan(score) else score, ticker))

        # 5) Valeur du portefeuille à la clôture
        value = cash
        for ticker, pos in positions.items():
            c = arrays[ticker]["close"][i]
            if not math.isnan(c):
                last_close[ticker] = c
            value += pos.trade.shares * last_close.get(ticker, pos.trade.entry_price)
        equity[i] = value
        invested[i] = (value - cash) / value if value > 0 else 0.0
        prev_equity = value

    # Positions encore ouvertes : clôturées au dernier cours pour le bilan
    for ticker in list(positions):
        price = last_close.get(ticker, positions[ticker].trade.entry_price)
        close_position(ticker, price, calendar[-1], "fin")

    eq = pd.Series(equity, index=calendar, name=strategy.name)
    bench = bench_close.reindex(calendar).ffill()
    bench = bench / bench.iloc[0] * cfg.initial_capital
    expo = pd.Series(invested, index=calendar, name="exposure")
    return BacktestResult(strategy.name, cfg, eq, trades, bench.rename(benchmark), expo)


def compute_metrics(
    equity: pd.Series, trades: list[Trade], start=None, end=None, exposure: pd.Series | None = None
) -> dict:
    eq = equity.dropna()
    if start:
        eq = eq[eq.index >= pd.Timestamp(start)]
    if end:
        eq = eq[eq.index <= pd.Timestamp(end)]
    if len(eq) < 2:
        return {}
    rets = eq.pct_change().dropna()
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    total = eq.iloc[-1] / eq.iloc[0] - 1.0
    cagr = (1.0 + total) ** (1.0 / years) - 1.0 if years > 0 and total > -1 else float("nan")
    vol = rets.std() * math.sqrt(TRADING_DAYS)
    sharpe = rets.mean() / rets.std() * math.sqrt(TRADING_DAYS) if rets.std() > 0 else float("nan")
    drawdown = eq / eq.cummax() - 1.0
    max_dd = drawdown.min()

    m = {
        "debut": eq.index[0].date().isoformat(),
        "fin": eq.index[-1].date().isoformat(),
        "rendement_total": total,
        "cagr": cagr,
        "volatilite": vol,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "calmar": cagr / abs(max_dd) if max_dd < 0 else float("nan"),
    }
    if exposure is not None:
        m["exposition_moyenne"] = float(exposure.reindex(eq.index).mean())

    closed = [
        t for t in trades
        if t.exit_date is not None and eq.index[0] <= t.entry_date <= eq.index[-1]
    ]
    if closed or trades:
        wins = [t for t in closed if t.pnl > 0]
        losses = [t for t in closed if t.pnl <= 0]
        gross_win = sum(t.pnl for t in wins)
        gross_loss = -sum(t.pnl for t in losses)
        m.update(
            {
                "nb_trades": len(closed),
                "taux_reussite": len(wins) / len(closed) if closed else float("nan"),
                "gain_moyen": float(np.mean([t.return_pct for t in wins])) if wins else float("nan"),
                "perte_moyenne": float(np.mean([t.return_pct for t in losses])) if losses else float("nan"),
                "profit_factor": gross_win / gross_loss if gross_loss > 0 else float("nan"),
                "r_moyen": float(np.mean([t.r_multiple for t in closed])) if closed else float("nan"),
                "duree_moyenne_jours": float(np.mean([(t.exit_date - t.entry_date).days for t in closed])) if closed else float("nan"),
            }
        )
    return m
