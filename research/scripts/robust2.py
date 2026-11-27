import math
import pandas as pd
from swing import universe as U
from swing.data import load_prices
from swing.portfolio import RotationConfig, CostConfig, run_rotation, blend
from swing.research import STOCKS, START
data = load_prices(U.all_tickers(), offline=True)
c = CostConfig()
s = run_rotation(data, RotationConfig(risk_assets=STOCKS, top_k=5, max_per_group=1, target_vol=0.18), c, start=START)
core = run_rotation(data, RotationConfig(risk_assets=["SPY"], top_k=1, market_filter=False), c, start=START)
eq = blend({"c": (core.equity, .5), "s": (s.equity, .5)}, c.initial_capital); b = s.benchmark.reindex(eq.index)
dd = eq/eq.cummax()-1; tr = dd.idxmin(); pk = eq[:tr].idxmax()
print("perte max", round(dd.min()*100,1), "du", pk.date(), "au", tr.date())
for lo, hi in [("2008-01-01","2009-12-31"),("2020-01-01","2020-12-31"),("2022-01-01","2022-12-31"),("2018-09-01","2018-12-31")]:
    x=eq[lo:hi]; y=b[lo:hi]
    print(lo[:7], "->", hi[:7], "candidat DD", round((x/x.cummax()-1).min()*100,1), "% | SPY DD", round((y/y.cummax()-1).min()*100,1), "%")
yr = eq.resample("YE").last(); yr = pd.concat([pd.Series([c.initial_capital], index=[eq.index[0]]), yr]).pct_change().dropna()
yb = b.resample("YE").last(); yb = pd.concat([pd.Series([c.initial_capital], index=[b.index[0]]), yb]).pct_change().dropna()
print(" ".join(f"{d.year}:{a*100:+.0f}/{e*100:+.0f}" for d,a,e in zip(yr.index, yr, yb)))
w = s.weights.iloc[-1]; print("positions actuelles poche actions:", w[w.abs()>0.001].round(3).to_dict())
wc = core.weights.iloc[-1]; print("poche coeur:", wc[wc.abs()>0.001].round(3).to_dict())
