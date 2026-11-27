import math, itertools
import numpy as np, pandas as pd
from swing import universe as U
from swing.data import load_prices
from swing.portfolio import RotationConfig, CostConfig, run_rotation, blend
from swing.research import STOCKS, START
from swing.backtest import compute_metrics
data = load_prices(U.all_tickers(), offline=True)

def make(k, cap, tv, freq, costs, start=START, core=True):
    s = run_rotation(data, RotationConfig(risk_assets=STOCKS, top_k=k, max_per_group=cap, target_vol=tv, rebalance=freq), costs, start=start)
    if not core: return s.equity, s.benchmark
    c = run_rotation(data, RotationConfig(risk_assets=["SPY"], top_k=1, market_filter=False, rebalance=freq), costs, start=start)
    return blend({"c": (c.equity, .5), "s": (s.equity, .5)}, costs.initial_capital), s.benchmark

def line(lab, eq, bench, start=None):
    t = compute_metrics(eq, [], start="2021-01-01"); tr = compute_metrics(eq, [], end="2020-12-31"); f = compute_metrics(eq, [])
    print(f"{lab:38} ent {tr['cagr']*100:5.1f}%/{tr['sharpe']:.2f}/{tr['max_drawdown']*100:6.1f}%  test {t['cagr']*100:5.1f}%/{t['sharpe']:.2f}/{t['max_drawdown']*100:6.1f}%  total DD {f['max_drawdown']*100:6.1f}%")

base = CostConfig()
print("== A. Candidat M (k5 cap1 vol18 mensuel) : réglages voisins ==")
for k, tv in itertools.product([4,5,6,8], [0.15,0.18,0.21]):
    eq, b = make(k, 1, tv, "M", base); line(f"k{k} vol{int(tv*100)} M", eq, b)
print("\n== B. Candidat W (k5 cap1 vol15 hebdo) : réglages voisins ==")
for k, tv in itertools.product([4,5,6,8], [0.12,0.15,0.18]):
    eq, b = make(k, 1, tv, "W", base); line(f"k{k} vol{int(tv*100)} W", eq, b)
print("\n== C. Frais triplés (18 pb par transaction) ==")
x3 = CostConfig(trade_cost_bps=18.0)
for k, tv, f in [(5,.18,"M"),(5,.15,"W"),(10,.15,"W")]:
    eq, b = make(k, 1 if k==5 else 2, tv, f, x3); line(f"x3 k{k} vol{int(tv*100)} {f}", eq, b)
print("\n== D. Départ décalé ==")
for st in ["2009-07-01","2011-01-01"]:
    for k, tv, f in [(5,.18,"M"),(5,.15,"W")]:
        eq, b = make(k, 1, tv, f, base, start=st); line(f"{st} k{k} vol{int(tv*100)} {f}", eq, b)
print("\n== E. Fenêtres glissantes de 3 ans (début chaque semestre) : % où le candidat bat SPY en Sharpe et perte max ≤20% ==")
for k, tv, f in [(5,.18,"M"),(5,.15,"W")]:
    eq, b = make(k, 1, tv, f, base)
    wins = dd_ok = n = 0
    for s0 in pd.date_range("2008-07-01", "2023-07-01", freq="6MS"):
        s1 = s0 + pd.DateOffset(years=3)
        m = compute_metrics(eq, [], start=s0, end=s1); mb = compute_metrics(b, [], start=s0, end=s1)
        if not m: continue
        n += 1; wins += m["sharpe"] > mb["sharpe"]; dd_ok += m["max_drawdown"] >= -0.20
    print(f"k{k} vol{int(tv*100)} {f}: bat SPY (Sharpe) dans {wins}/{n} fenêtres ; perte max ≤20 % dans {dd_ok}/{n}")
eq, b = make(5, 1, .18, "M", base)
y = eq.resample("YE").last().pct_change(); yb = b.resample("YE").last().pct_change()
print("\nAnnées (candidat M vs SPY):", {d.year: (round(a*100,1), round(c*100,1)) for d,a,c in zip(y.index,y,yb) if not math.isnan(a)})
