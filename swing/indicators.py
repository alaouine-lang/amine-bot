"""Indicateurs techniques calculés en pandas pur (aucune bibliothèque externe).

Toutes les fonctions n'utilisent que les données disponibles jusqu'à la date t
(pas de regard vers le futur). Les premières valeurs sont NaN tant que la
fenêtre de calcul n'est pas remplie.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False, min_periods=window).mean()


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """RSI de Wilder (0-100)."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    # Aucune baisse sur la fenêtre : RSI = 100 (ou 50 si le prix n'a pas bougé du tout)
    flat_up = (avg_loss == 0.0) & avg_gain.notna()
    out = out.mask(flat_up & (avg_gain > 0.0), 100.0)
    out = out.mask(flat_up & (avg_gain == 0.0), 50.0)
    return out


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["Close"].shift(1)
    ranges = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1, skipna=False).fillna(df["High"] - df["Low"])


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Average True Range de Wilder : mesure de la volatilité en dollars."""
    return true_range(df).ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()


def roc(series: pd.Series, window: int) -> pd.Series:
    """Variation en % sur `window` séances (0.10 = +10 %)."""
    return series / series.shift(window) - 1.0


def rolling_high(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).max()


def volume_ratio(volume: pd.Series, window: int = 20) -> pd.Series:
    """Volume du jour / volume moyen des `window` séances PRÉCÉDENTES."""
    avg = volume.rolling(window, min_periods=window).mean().shift(1)
    return volume / avg.replace(0.0, np.nan)
