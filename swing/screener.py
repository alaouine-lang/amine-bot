"""Screener du soir : applique une stratégie à la dernière séance et propose des entrées.

Chaque proposition contient la zone d'entrée, le stop calculé sur la volatilité (ATR)
et une taille de position indicative. Les propositions sont ajoutées au journal
(data/journal/signals.csv) pour mesurer plus tard leur performance réelle.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import pandas as pd

from .data import data_dir
from .strategies import Strategy
from .universe import category_of


@dataclass
class Proposal:
    date: str
    strategy: str
    ticker: str
    category: str
    close: float
    stop: float
    risk_pct: float          # distance au stop, en % du prix
    shares: int              # taille indicative pour le capital et le risque donnés
    position_value: float
    score: float


def screen(
    data: dict[str, pd.DataFrame],
    strategy: Strategy,
    benchmark: str = "SPY",
    capital: float = 100_000.0,
    risk_per_trade: float = 0.01,
    max_position_pct: float = 0.20,
    min_price: float = 5.0,
) -> list[Proposal]:
    bench_close = data[benchmark]["Close"]
    last_day = bench_close.index[-1]
    proposals: list[Proposal] = []
    for ticker, df in data.items():
        if df.empty or df.index[-1] != last_day:
            continue  # pas de cours à jour pour ce ticker
        sig = strategy.compute(df, bench_close).iloc[-1]
        close = float(df["Close"].iloc[-1])
        atr = float(sig["atr"])
        if not bool(sig["entry"]) or close < min_price or math.isnan(atr) or atr <= 0:
            continue
        stop = close - strategy.stop_atr_mult * atr
        if stop <= 0:
            continue
        risk_per_share = close - stop
        shares = min(
            math.floor(capital * risk_per_trade / risk_per_share),
            math.floor(capital * max_position_pct / close),
        )
        score = float(sig["score"])
        proposals.append(
            Proposal(
                date=last_day.date().isoformat(),
                strategy=strategy.name,
                ticker=ticker,
                category=category_of(ticker),
                close=round(close, 2),
                stop=round(stop, 2),
                risk_pct=round(risk_per_share / close, 4),
                shares=max(shares, 0),
                position_value=round(max(shares, 0) * close, 2),
                score=round(score, 4) if not math.isnan(score) else float("nan"),
            )
        )
    proposals.sort(key=lambda p: (-math.inf if math.isnan(p.score) else p.score), reverse=True)
    return proposals


def append_to_journal(proposals: list[Proposal]) -> str:
    """Ajoute les propositions au journal, sans doublon (date, stratégie, ticker)."""
    path = data_dir() / "journal" / "signals.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    new = pd.DataFrame([asdict(p) for p in proposals])
    if path.exists():
        old = pd.read_csv(path)
        merged = pd.concat([old, new], ignore_index=True) if not new.empty else old
    else:
        merged = new
    if not merged.empty:
        merged = merged.drop_duplicates(subset=["date", "strategy", "ticker"], keep="last")
    merged.to_csv(path, index=False)
    return str(path)
