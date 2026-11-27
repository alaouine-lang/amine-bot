import itertools
from dataclasses import replace
from swing import universe as U
from swing.data import load_prices
from swing.portfolio import RotationConfig, CostConfig, run_rotation, blend
from swing.research import STOCKS, Row, _row, report, save_report, START
from swing.backtest import compute_metrics
data = load_prices(U.all_tickers(), offline=True)
costs = CostConfig()
rows = []; bench=None
spy_t = run_rotation(data, RotationConfig(name="spy_timing", risk_assets=["SPY"], top_k=1, market_filter=False), costs, start=START)
spy_tw = run_rotation(data, RotationConfig(name="spy_timing_W", risk_assets=["SPY"], top_k=1, market_filter=False, rebalance="W"), costs, start=START)
rows += [_row("spy_timing_W", spy_tw.equity)]
for (k,cap), tv, lev, freq in itertools.product([(5,1),(10,2)], [None,0.15,0.18,0.20], [1.0,1.5], ["M","W"]):
    if tv is None and lev != 1.0: continue
    name = f"stk_k{k}_cap{cap}_vol{int(tv*100) if tv else 'X'}_lev{lev}_{freq}"
    cfg = RotationConfig(name=name, risk_assets=STOCKS, top_k=k, max_per_group=cap, target_vol=tv, max_leverage=lev, rebalance=freq)
    r = run_rotation(data, cfg, costs, start=START); bench = r.benchmark
    rows.append(_row(name, r.equity))
    for cw in (0.5,):
        core = spy_tw if freq=="W" else spy_t
        rows.append(_row(f"coeur50+{name}", blend({"c": (core.equity, cw), "s": (r.equity, 1-cw)}, costs.initial_capital)))
spy = {"train": compute_metrics(bench, [], end="2020-12-31"), "test": compute_metrics(bench, [], start="2021-01-01"), "full": compute_metrics(bench, [])}
txt = report(rows, spy, "Série 2 — ciblage de volatilité, levier, fréquence")
print(save_report(txt, "serie2"))
for line in txt.splitlines():
    if "3/3" in line or "SPY (réf" in line or "Choix" in line or "meilleure" in line or "En test" in line: print(line)
print("nb 2/3:", sum("2/3" in l for l in txt.splitlines()))
