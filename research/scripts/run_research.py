import time, sys
from swing import universe as U
from swing.data import load_prices
from swing.research import run_all, report, save_report
data = load_prices(U.all_tickers(), offline=True)
t = time.time()
rows, spy = run_all(data)
txt = report(rows, spy, "Banc d'essai des stratégies — coûts normaux")
print(txt); print(save_report(txt, "banc_essai"), f"{time.time()-t:.0f}s")
