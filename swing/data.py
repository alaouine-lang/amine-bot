"""Téléchargement des cours (Yahoo Finance via yfinance) avec cache local en CSV.

Les cours sont ajustés des dividendes et des splits (auto_adjust=True), ce qui
est nécessaire pour un backtest correct.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

DEFAULT_START = "2007-01-01"
CACHE_MAX_AGE_HOURS = 12
COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def data_dir() -> Path:
    base = os.environ.get("SWING_DATA_DIR")
    path = Path(base) if base else Path(__file__).resolve().parent.parent / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = data_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_file(ticker: str) -> Path:
    return cache_dir() / f"{ticker.replace('/', '_')}.csv"


def _is_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    age_hours = (time.time() - path.stat().st_mtime) / 3600.0
    return age_hours < CACHE_MAX_AGE_HOURS


def _extract(raw: pd.DataFrame, ticker: str) -> pd.DataFrame | None:
    """Extrait le DataFrame OHLCV d'un ticker du résultat de yf.download."""
    if raw is None or raw.empty:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        lvl0 = raw.columns.get_level_values(0)
        lvl1 = raw.columns.get_level_values(1)
        if ticker in lvl0:
            sub = raw[ticker]
        elif ticker in lvl1:
            sub = raw.xs(ticker, axis=1, level=1)
        else:
            return None
    else:
        sub = raw
    missing = [c for c in COLUMNS if c not in sub.columns]
    if missing:
        return None
    sub = sub[COLUMNS].dropna(subset=["Open", "High", "Low", "Close"])
    if sub.empty:
        return None
    sub.index = pd.to_datetime(sub.index).tz_localize(None)
    sub.index.name = "Date"
    return sub.sort_index()


def download(tickers: list[str], start: str = DEFAULT_START, chunk_size: int = 40) -> dict[str, pd.DataFrame]:
    """Télécharge les cours journaliers et les enregistre dans le cache."""
    import yfinance as yf  # import tardif : les tests n'en ont pas besoin

    result: dict[str, pd.DataFrame] = {}
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i : i + chunk_size]
        raw = yf.download(
            chunk,
            start=start,
            auto_adjust=True,
            group_by="ticker",
            progress=False,
            threads=True,
        )
        for t in chunk:
            df = _extract(raw, t)
            if df is not None:
                df.to_csv(_cache_file(t))
                result[t] = df

    # Nouvelles tentatives, une action à la fois et sans parallélisme : les échecs
    # « database is locked » de yfinance (fréquents sous Windows) viennent du téléchargement parallèle.
    failed = [t for t in tickers if t not in result]
    for attempt in range(2):
        if not failed:
            break
        time.sleep(2)
        still = []
        for t in failed:
            raw = yf.download(t, start=start, auto_adjust=True, group_by="ticker", progress=False, threads=False)
            df = _extract(raw, t)
            if df is None:
                still.append(t)
                continue
            df.to_csv(_cache_file(t))
            result[t] = df
        failed = still
    for t in failed:
        if _cache_file(t).exists():
            log.warning("Téléchargement raté pour %s : utilisation des données en cache (plus anciennes)", t)
        else:
            log.warning("Aucune donnée pour %s (ticker invalide, retiré de la cote, ou erreur réseau)", t)
    return result


def clean_spikes(df: pd.DataFrame, threshold: float = 0.2, revert_tol: float = 0.05) -> pd.DataFrame:
    """Corrige les points aberrants d'un jour (erreurs de données Yahoo).

    Un point est aberrant si le cours bouge de plus de `threshold` dans un sens puis
    revient le lendemain presque au niveau de l'avant-veille (écart < `revert_tol`).
    La ligne est alors remplacée par celle de la veille. Les vrais krachs, qui ne
    reviennent pas le lendemain, ne sont pas touchés.
    """
    c = df["Close"]
    r_in = c / c.shift(1) - 1.0
    r_out = c.shift(-1) / c - 1.0
    back = (c.shift(-1) / c.shift(1) - 1.0).abs()
    spike = (r_in.abs() > threshold) & (r_out.abs() > threshold) & (r_in * r_out < 0) & (back < revert_tol)
    if not spike.any():
        return df
    out = df.copy()
    for d in spike[spike].index:
        i = out.index.get_loc(d)
        # la séance aberrante est remplacée par une séance plate au cours de clôture de la veille
        out.iloc[i, out.columns.get_indexer(["Open", "High", "Low", "Close"])] = [out["Close"].iloc[i - 1]] * 4
        log.info("Point aberrant corrigé : %s", d.date())
    return out


def read_cached(ticker: str) -> pd.DataFrame | None:
    path = _cache_file(ticker)
    if not path.exists():
        return None
    df = pd.read_csv(path, index_col="Date", parse_dates=["Date"])
    return clean_spikes(df[COLUMNS].sort_index())


def load_prices(
    tickers: list[str],
    start: str = DEFAULT_START,
    refresh: bool = False,
    offline: bool = False,
) -> dict[str, pd.DataFrame]:
    """Cours de chaque ticker, depuis le cache s'il est récent, sinon téléchargés.

    offline=True : n'utilise que le cache, sans connexion internet.
    """
    stale = [] if offline else [t for t in tickers if refresh or not _is_fresh(_cache_file(t))]
    if stale:
        log.info("Téléchargement de %d tickers…", len(stale))
        download(stale, start=start)
    out: dict[str, pd.DataFrame] = {}
    for t in tickers:
        df = read_cached(t)
        if df is not None and not df.empty:
            out[t] = df
    return out
