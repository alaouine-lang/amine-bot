"""Stratégies de swing trading (long uniquement en phase 1).

Chaque stratégie calcule, pour un actif, une table de signaux indexée par date :
  - entry : True si les conditions d'achat sont réunies à la CLÔTURE du jour
  - exit  : True si les conditions de sortie sont réunies à la clôture du jour
  - score : force du signal (sert à classer les candidats quand il y en a trop)
  - atr   : volatilité du jour, utilisée pour placer le stop

Les ordres sont exécutés par le backtest à l'OUVERTURE du lendemain :
aucune décision n'utilise une information du futur.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import indicators as ind


@dataclass
class Strategy:
    name: str = "base"
    stop_atr_mult: float = 3.0   # stop initial = prix d'entrée - k × ATR
    trailing: bool = False       # stop suiveur : plus haut depuis l'entrée - k × ATR
    max_hold_days: int | None = None
    params: dict = field(default_factory=dict)

    def compute(self, df: pd.DataFrame, bench_close: pd.Series) -> pd.DataFrame:
        raise NotImplementedError


def _regime_ok(bench_close: pd.Series, index: pd.Index, window: int = 200) -> pd.Series:
    """Filtre de marché : True quand l'indice de référence est au-dessus de sa moyenne 200 jours."""
    ok = bench_close > ind.sma(bench_close, window)
    return ok.reindex(index).ffill().fillna(False).astype(bool)


def _relative_strength(close: pd.Series, bench_close: pd.Series, window: int) -> pd.Series:
    bench = bench_close.reindex(close.index).ffill()
    return ind.roc(close, window) - ind.roc(bench, window)


@dataclass
class MomentumBreakout(Strategy):
    """Cassure de plus haut sur N jours, dans une tendance haussière confirmée.

    Achat : clôture au-dessus du plus haut des N séances précédentes,
            prix > MM200, MM50 > MM200, volume ≥ moyenne, marché haussier.
    Sortie : clôture sous la MM50, ou stop suiveur à k × ATR.
    Score : surperformance sur 6 mois par rapport au S&P 500.
    """

    name: str = "momentum"
    stop_atr_mult: float = 3.0
    trailing: bool = True
    breakout_window: int = 55
    fast_sma: int = 50
    slow_sma: int = 200
    min_volume_ratio: float = 1.0
    rs_window: int = 126

    def compute(self, df: pd.DataFrame, bench_close: pd.Series) -> pd.DataFrame:
        close = df["Close"]
        sma_fast = ind.sma(close, self.fast_sma)
        sma_slow = ind.sma(close, self.slow_sma)
        prior_high = ind.rolling_high(close, self.breakout_window).shift(1)
        vol_ok = ind.volume_ratio(df["Volume"]) >= self.min_volume_ratio
        # Les ETF de matières premières ont parfois un volume nul ou absent : on ne filtre pas dans ce cas
        vol_ok = vol_ok | df["Volume"].fillna(0).eq(0)

        entry = (
            (close > prior_high)
            & (close > sma_slow)
            & (sma_fast > sma_slow)
            & vol_ok
            & _regime_ok(bench_close, df.index)
        )
        exit_ = close < sma_fast
        return pd.DataFrame(
            {
                "entry": entry.fillna(False),
                "exit": exit_.fillna(False),
                "score": _relative_strength(close, bench_close, self.rs_window),
                "atr": ind.atr(df),
            },
            index=df.index,
        )


@dataclass
class TrendPullback(Strategy):
    """Achat d'un repli de court terme dans une tendance haussière de fond.

    Achat : prix > MM200, RSI(3) < seuil (repli marqué), marché haussier.
    Sortie : clôture au-dessus de la MM5 ou RSI(3) > 70, ou au bout de N jours.
    Score : surperformance sur 6 mois (on préfère les actions fortes qui reculent).
    """

    name: str = "pullback"
    stop_atr_mult: float = 2.5
    trailing: bool = False
    max_hold_days: int | None = 10
    slow_sma: int = 200
    rsi_window: int = 3
    rsi_entry: float = 15.0
    rsi_exit: float = 70.0
    exit_sma: int = 5
    rs_window: int = 126

    def compute(self, df: pd.DataFrame, bench_close: pd.Series) -> pd.DataFrame:
        close = df["Close"]
        r = ind.rsi(close, self.rsi_window)
        entry = (
            (close > ind.sma(close, self.slow_sma))
            & (r < self.rsi_entry)
            & _regime_ok(bench_close, df.index)
        )
        exit_ = (close > ind.sma(close, self.exit_sma)) | (r > self.rsi_exit)
        return pd.DataFrame(
            {
                "entry": entry.fillna(False),
                "exit": exit_.fillna(False),
                "score": _relative_strength(close, bench_close, self.rs_window),
                "atr": ind.atr(df),
            },
            index=df.index,
        )


STRATEGIES: dict[str, type[Strategy]] = {
    "momentum": MomentumBreakout,
    "pullback": TrendPullback,
}


def get_strategy(name: str, **overrides) -> Strategy:
    if name not in STRATEGIES:
        raise ValueError(f"Stratégie inconnue : {name}. Choix : {', '.join(STRATEGIES)}")
    return STRATEGIES[name](**overrides)
