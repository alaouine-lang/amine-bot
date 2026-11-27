"""Stratégies de ROTATION de portefeuille, rééquilibrées chaque mois.

Principe (« dual momentum ») :
  - Momentum relatif : on classe les actifs selon leur performance sur 3, 6 et 12 mois
    et on garde les K meilleurs.
  - Momentum absolu : un actif n'est retenu que s'il monte vraiment (performance > 0
    et prix au-dessus de sa moyenne 200 jours). Sinon, sa part va aux actifs défensifs.
  - Filtre de marché (optionnel) : si le S&P 500 est sous sa MM200, la poche risquée
    passe en défensif, ou en position inverse si c'est autorisé.
  - Ciblage de volatilité (optionnel) : on ajuste l'exposition totale pour viser un
    niveau de risque, avec un levier plafonné.

Règles de simulation :
  - Signal à la clôture du dernier jour du mois, exécution à l'ouverture suivante.
  - Frais + glissement sur chaque montant échangé.
  - Levier : le cash négatif coûte un taux d'emprunt annuel.
  - Ventes à découvert : frais d'emprunt de titres annuels sur la valeur vendue.
  - ETF inverse synthétique : -1 × la variation quotidienne du SPY, moins des frais annuels.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .backtest import compute_metrics
from .universe import group_of

INVERSE = "SPY_INV"


@dataclass
class RotationConfig:
    name: str = "rotation"
    risk_assets: list[str] = field(default_factory=list)
    defensive_assets: list[str] = field(default_factory=lambda: ["TLT", "IEF", "GLD"])
    top_k: int = 5
    lookbacks: tuple[int, ...] = (63, 126, 252)   # 3, 6 et 12 mois de bourse
    trend_sma: int = 200
    abs_momentum: bool = True
    market_filter: bool = True                     # SPY < MM200 → poche risquée en défensif
    bear_mode: str = "defensive"                  # "defensive" | "inverse" | "short_weakest"
    bear_weight: float = 0.5                      # part du capital en inverse / à découvert en marché baissier
    target_vol: float | None = None               # ex. 0.12 pour viser 12 % de volatilité annuelle
    max_leverage: float = 1.0                     # 1.0 = sans levier
    vol_window: int = 63
    max_per_group: int | None = None              # ex. 1 = un seul actif par famille corrélée
    rebalance: str = "M"                          # "M" = mensuel, "W" = hebdomadaire
    benchmark: str = "SPY"


@dataclass
class CostConfig:
    initial_capital: float = 50_000.0
    trade_cost_bps: float = 6.0          # frais 1 pb + glissement 5 pb
    margin_rate: float = 0.06            # coût annuel de l'emprunt (hypothèse à vérifier chez IBKR)
    borrow_fee: float = 0.01             # frais annuels d'emprunt de titres pour la vente à découvert
    inverse_fee: float = 0.009           # frais annuels d'un ETF inverse type SH (approximation)
    cash_rate: float = 0.0               # rémunération du cash (0 = prudent)


@dataclass
class RotationResult:
    name: str
    equity: pd.Series
    weights: pd.DataFrame
    turnover: float
    benchmark: pd.Series

    def metrics(self, start=None, end=None) -> dict:
        m = compute_metrics(self.equity, [], start=start, end=end)
        w = self.weights
        if start:
            w = w[w.index >= pd.Timestamp(start)]
        if end:
            w = w[w.index <= pd.Timestamp(end)]
        if not w.empty:
            m["exposition_brute"] = float(w.abs().sum(axis=1).mean())
            m["exposition_nette"] = float(w.sum(axis=1).mean())
        m["rotation_annuelle"] = self.turnover
        return m

    def benchmark_metrics(self, start=None, end=None) -> dict:
        return compute_metrics(self.benchmark, [], start=start, end=end)


def build_panel(data: dict[str, pd.DataFrame], benchmark: str = "SPY", inverse_fee: float = 0.009):
    """Tableaux alignés (dates × tickers) des ouvertures et clôtures, + ETF inverse synthétique."""
    cal = data[benchmark].index
    close = pd.DataFrame({t: df["Close"].reindex(cal) for t, df in data.items()})
    open_ = pd.DataFrame({t: df["Open"].reindex(cal) for t, df in data.items()})
    spy_c, spy_o = close[benchmark], open_[benchmark]
    # Inverse synthétique : rendement quotidien opposé (de clôture à clôture), frais déduits
    r = spy_c.pct_change().fillna(0.0)
    inv = 100.0 * (1.0 - r - inverse_fee / 252.0).cumprod()
    close[INVERSE] = inv
    # ouverture de l'inverse : on applique l'écart ouverture/clôture veille du SPY, inversé
    gap = (spy_o / spy_c.shift(1) - 1.0).fillna(0.0)
    open_[INVERSE] = inv.shift(1).fillna(100.0) * (1.0 - gap)
    return open_, close


def momentum_score(close: pd.DataFrame, lookbacks: tuple[int, ...]) -> pd.DataFrame:
    parts = [close / close.shift(lb) - 1.0 for lb in lookbacks]
    return sum(parts) / len(parts)


def month_end_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    s = pd.Series(index, index=index)
    return pd.DatetimeIndex(s.groupby([index.year, index.month]).max().values)


def week_end_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    s = pd.Series(index, index=index)
    iso = index.isocalendar()
    return pd.DatetimeIndex(s.groupby([iso.year.values, iso.week.values]).max().sort_values().values)


def rebalance_dates(index: pd.DatetimeIndex, freq: str) -> pd.DatetimeIndex:
    return week_end_dates(index) if freq == "W" else month_end_dates(index)


def target_weights(close: pd.DataFrame, cfg: RotationConfig) -> pd.DataFrame:
    """Poids cibles décidés à chaque fin de mois (index = date du signal)."""
    score = momentum_score(close, cfg.lookbacks)
    sma = close.rolling(cfg.trend_sma, min_periods=cfg.trend_sma).mean()
    rets = close.pct_change()
    bench = close[cfg.benchmark]
    bench_ok = bench > bench.rolling(cfg.trend_sma, min_periods=cfg.trend_sma).mean()
    max_lb = max(cfg.lookbacks)

    rows = {}
    for d in rebalance_dates(close.index, cfg.rebalance):
        i = close.index.get_loc(d)
        if i < max(max_lb, cfg.trend_sma):
            continue
        sc = score.loc[d]
        w = pd.Series(0.0, index=close.columns)
        risk = [t for t in cfg.risk_assets if t in sc.index and not math.isnan(sc[t])]
        bull = bool(bench_ok.loc[d]) or not cfg.market_filter
        slot = 1.0 / cfg.top_k

        chosen: list[str] = []
        if bull and risk:
            ranked = sc[risk].sort_values(ascending=False)
            per_group: dict[str, int] = {}
            for t in ranked.index:
                if len(chosen) >= cfg.top_k:
                    break
                if cfg.abs_momentum and not (ranked[t] > 0 and close.at[d, t] > sma.at[d, t]):
                    continue
                g = group_of(t)
                if cfg.max_per_group is not None and per_group.get(g, 0) >= cfg.max_per_group:
                    continue
                per_group[g] = per_group.get(g, 0) + 1
                chosen.append(t)
            for t in chosen:
                w[t] = slot
        free = 1.0 - slot * len(chosen)

        if not bull and cfg.bear_mode == "inverse":
            w[INVERSE] = cfg.bear_weight
            free -= cfg.bear_weight
        elif not bull and cfg.bear_mode == "short_weakest" and risk:
            weakest = sc[risk].sort_values().index[: cfg.top_k]
            for t in weakest:
                w[t] = -cfg.bear_weight / len(weakest)

        if free > 1e-9:
            defensive = [t for t in cfg.defensive_assets if t in sc.index and not math.isnan(sc[t])]
            good = [t for t in defensive if sc[t] > 0 and close.at[d, t] > sma.at[d, t]]
            if good:
                best = max(good, key=lambda t: sc[t])
                w[best] += free  # le reste en cash si aucun défensif ne monte

        if cfg.target_vol:
            window = rets.iloc[max(0, i - cfg.vol_window + 1) : i + 1]
            active = w[w != 0].index
            if len(active):
                cov = window[active].cov().fillna(0.0).to_numpy() * 252.0
                wv = w[active].to_numpy()
                vol = math.sqrt(max(float(wv @ cov @ wv), 0.0))
                if vol > 0:
                    gross = w.abs().sum()
                    scale = min(cfg.target_vol / vol, cfg.max_leverage / gross if gross > 0 else 0)
                    w = w * scale
        elif cfg.max_leverage != 1.0:
            w = w * cfg.max_leverage
        rows[d] = w
    return pd.DataFrame(rows).T.fillna(0.0)


def simulate(
    open_: pd.DataFrame,
    close: pd.DataFrame,
    weights: pd.DataFrame,
    costs: CostConfig,
    start: str | None = None,
    end: str | None = None,
) -> tuple[pd.Series, pd.DataFrame, float]:
    """Simule le portefeuille : renvoie (capital quotidien, poids quotidiens, rotation annuelle)."""
    cal = close.index
    if start:
        cal = cal[cal >= pd.Timestamp(start)]
    if end:
        cal = cal[cal <= pd.Timestamp(end)]
    cols = list(close.columns)
    col_idx = {c: j for j, c in enumerate(cols)}
    C = close.reindex(cal).ffill().to_numpy(float)
    O = open_.reindex(cal).to_numpy(float)
    O = np.where(np.isnan(O), C, O)

    # date d'exécution = séance qui suit le signal
    exec_map: dict[int, pd.Series] = {}
    for d, w in weights.iterrows():
        pos = cal.searchsorted(d, side="right")
        if pos < len(cal):
            exec_map[pos] = w

    cost = costs.trade_cost_bps / 10_000.0
    shares = np.zeros(len(cols))
    cash = costs.initial_capital
    equity = np.empty(len(cal))
    wdaily = np.zeros((len(cal), len(cols)))
    traded = 0.0
    for i in range(len(cal)):
        if i in exec_map:
            px = O[i]
            px_safe = np.where(np.isnan(px), 0.0, px)
            eq_open = cash + float(np.nansum(shares * px_safe))
            target = np.zeros(len(cols))
            for t, wt in exec_map[i].items():
                if wt != 0 and t in col_idx and not math.isnan(px[col_idx[t]]) and px[col_idx[t]] > 0:
                    target[col_idx[t]] = eq_open * wt / px[col_idx[t]]
            delta_val = np.abs(target - shares) * px_safe
            traded += float(delta_val.sum())
            cash -= float(((target - shares) * px_safe).sum()) + float(delta_val.sum()) * cost
            shares = target
        # coûts de portage quotidiens
        px_c = np.where(np.isnan(C[i]), 0.0, C[i])
        short_val = float(-(shares[shares < 0] * px_c[shares < 0]).sum())
        if cash < 0:
            cash -= -cash * costs.margin_rate / 252.0
        else:
            cash += cash * costs.cash_rate / 252.0
        cash -= short_val * costs.borrow_fee / 252.0
        value = cash + float((shares * px_c).sum())
        equity[i] = value
        if value > 0:
            wdaily[i] = shares * px_c / value
    eq = pd.Series(equity, index=cal)
    years = max((cal[-1] - cal[0]).days / 365.25, 1e-9)
    turnover = traded / float(np.mean(equity)) / years
    return eq, pd.DataFrame(wdaily, index=cal, columns=cols), turnover


def run_rotation(
    data: dict[str, pd.DataFrame],
    cfg: RotationConfig,
    costs: CostConfig | None = None,
    start: str | None = None,
    end: str | None = None,
) -> RotationResult:
    costs = costs or CostConfig()
    open_, close = build_panel(data, cfg.benchmark, costs.inverse_fee)
    w = target_weights(close, cfg)
    eq, wd, turnover = simulate(open_, close, w, costs, start=start, end=end)
    bench = close[cfg.benchmark].reindex(eq.index).ffill()
    bench = bench / bench.iloc[0] * costs.initial_capital
    return RotationResult(cfg.name, eq.rename(cfg.name), wd, turnover, bench.rename(cfg.benchmark))


def blend(curves: dict[str, tuple[pd.Series, float]], initial_capital: float) -> pd.Series:
    """Combine plusieurs courbes de capital (poches indépendantes) avec des poids fixes,
    rééquilibrées chaque mois. Approximation : chaque poche suit son propre rendement."""
    rets = pd.DataFrame({k: s.pct_change() for k, (s, _) in curves.items()}).dropna()
    weights = pd.Series({k: w for k, (_, w) in curves.items()})
    value = initial_capital
    alloc = weights * value
    out = []
    last_month = None
    for d, r in rets.iterrows():
        if last_month is not None and d.month != last_month:
            alloc = weights * alloc.sum()
        alloc = alloc * (1.0 + r)
        out.append(alloc.sum())
        last_month = d.month
    return pd.Series(out, index=rets.index)
