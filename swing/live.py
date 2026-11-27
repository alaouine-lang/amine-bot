"""Exécution réelle de la stratégie retenue, en paper trading (sans argent réel).

Stratégie (choisie le 27/11/2026, voir research/2026-11-27_synthese.md) :
  - 50 % cœur : SPY s'il est en tendance haussière, sinon obligations/or/cash
  - 50 % rotation : 5 actions US les plus fortes, 1 par secteur, volatilité ciblée 18 %
  Rééquilibrage : signal à la clôture du dernier jour de bourse du mois,
  exécution à l'ouverture de la séance suivante.

À lancer chaque soir après la clôture US (≈ 22h30 heure de Paris) :
  python -m swing live
Le programme :
  1. exécute (en simulation) les ordres en attente au cours d'ouverture du jour ;
  2. si c'est le dernier jour de bourse du mois, calcule les nouvelles cibles
     et prépare les ordres pour l'ouverture suivante ;
  3. met à jour la valeur du portefeuille et envoie un résumé sur Telegram.

L'état du portefeuille fictif est dans data/paper/ (state.json, trades.csv, equity.csv).
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import universe as U
from .data import data_dir
from .portfolio import RotationConfig, build_panel, target_weights

log = logging.getLogger(__name__)

STRATEGY_NAME = "coeur50_spy + rotation5_vol18"
CORE_WEIGHT = 0.5
TRADE_COST_BPS = 6.0
STOCKS = [t for v in U.STOCKS.values() for t in v]


def core_config() -> RotationConfig:
    return RotationConfig(name="coeur", risk_assets=["SPY"], top_k=1, market_filter=False)


def rotation_config() -> RotationConfig:
    return RotationConfig(name="rotation", risk_assets=STOCKS, top_k=5, max_per_group=1, target_vol=0.18)


def paper_dir() -> Path:
    p = data_dir() / "paper"
    p.mkdir(parents=True, exist_ok=True)
    return p


@dataclass
class PaperState:
    initial_capital: float
    start_date: str | None = None
    cash: float = 0.0
    positions: dict[str, float] = field(default_factory=dict)
    pending: dict | None = None            # {"signal_date": str, "weights": {ticker: poids}}
    last_signal_date: str | None = None
    spy_start: float | None = None

    @classmethod
    def load(cls, capital: float) -> "PaperState":
        path = paper_dir() / "state.json"
        if path.exists():
            return cls(**json.loads(path.read_text(encoding="utf-8")))
        return cls(initial_capital=capital, cash=capital)

    def save(self) -> None:
        (paper_dir() / "state.json").write_text(json.dumps(self.__dict__, indent=2, ensure_ascii=False), encoding="utf-8")


def is_month_end(day: pd.Timestamp) -> bool:
    """Dernier jour ouvré du mois (les jours fériés de fin de mois sont rares aux États-Unis)."""
    nxt = day + pd.offsets.BDay(1)
    return nxt.month != day.month


def combined_targets(close: pd.DataFrame, signal_date: pd.Timestamp) -> dict[str, float]:
    """Poids cibles de la stratégie à une date de signal (même calcul que le backtest)."""
    out: dict[str, float] = {}
    for cfg, weight in ((core_config(), CORE_WEIGHT), (rotation_config(), 1.0 - CORE_WEIGHT)):
        w = target_weights(close.loc[:signal_date], cfg)
        if w.empty or w.index[-1] != signal_date:
            raise RuntimeError(f"Pas de signal calculable au {signal_date.date()} pour {cfg.name}")
        for t, v in w.iloc[-1].items():
            if abs(v) > 1e-9:
                out[t] = out.get(t, 0.0) + weight * float(v)
    return out


def _append_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    df = pd.DataFrame(rows)
    df.to_csv(path, mode="a", header=not path.exists(), index=False)


def execute_pending(state: PaperState, open_: pd.DataFrame, day: pd.Timestamp) -> list[dict]:
    """Exécute les ordres en attente à l'ouverture de `day` (actions entières, frais inclus)."""
    if not state.pending or pd.Timestamp(state.pending["signal_date"]) >= day:
        return []
    px = open_.loc[day]
    value = state.cash + sum(sh * float(px.get(t, float("nan"))) for t, sh in state.positions.items() if not math.isnan(float(px.get(t, float("nan")))))
    targets = state.pending["weights"]
    cost = TRADE_COST_BPS / 10_000.0
    trades = []
    for t in sorted(set(targets) | set(state.positions)):
        p = float(px.get(t, float("nan")))
        if math.isnan(p) or p <= 0:
            log.warning("Pas de cours d'ouverture pour %s : position inchangée", t)
            continue
        want = math.floor(value * targets.get(t, 0.0) / p)
        have = state.positions.get(t, 0.0)
        delta = want - have
        if delta == 0:
            continue
        fill = p * (1 + cost) if delta > 0 else p * (1 - cost)
        state.cash -= delta * fill
        if want == 0:
            state.positions.pop(t, None)
        else:
            state.positions[t] = want
        trades.append({"date": day.date().isoformat(), "ticker": t, "action": "ACHAT" if delta > 0 else "VENTE",
                       "quantite": abs(delta), "prix": round(fill, 4), "montant": round(abs(delta) * fill, 2)})
    state.pending = None
    _append_csv(paper_dir() / "trades.csv", trades)
    return trades


def portfolio_value(state: PaperState, close_row: pd.Series) -> float:
    v = state.cash
    for t, sh in state.positions.items():
        c = float(close_row.get(t, float("nan")))
        if not math.isnan(c):
            v += sh * c
    return v


def planned_orders(state: PaperState, targets: dict[str, float], close_row: pd.Series) -> list[dict]:
    """Ordres indicatifs calculés au cours de clôture (les quantités finales se font à l'ouverture)."""
    value = portfolio_value(state, close_row)
    orders = []
    for t in sorted(set(targets) | set(state.positions)):
        c = float(close_row.get(t, float("nan")))
        if math.isnan(c) or c <= 0:
            continue
        want = math.floor(value * targets.get(t, 0.0) / c)
        delta = want - state.positions.get(t, 0.0)
        if delta:
            orders.append({"ticker": t, "action": "ACHAT" if delta > 0 else "VENTE", "quantite": int(abs(delta)),
                           "cours_ref": round(c, 2), "poids_cible": round(targets.get(t, 0.0), 4)})
    return orders


@dataclass
class DailyReport:
    day: pd.Timestamp
    value: float
    spy_value: float | None
    fills: list[dict]
    signal: bool
    targets: dict[str, float] | None
    orders: list[dict]
    spy_above_ma200: bool

    def message(self, state: PaperState) -> str:
        perf = self.value / state.initial_capital - 1
        lines = [f"<b>SWING — paper trading</b> ({self.day.date()})",
                 f"Portefeuille fictif : <b>{self.value:,.0f} $</b> ({perf:+.1%} depuis le {state.start_date})"]
        if self.spy_value is not None:
            lines.append(f"S&P 500 sur la même période : {self.spy_value / state.initial_capital - 1:+.1%}")
        lines.append("Marché : " + ("🟢 SPY au-dessus de sa MM200" if self.spy_above_ma200 else "🔴 SPY sous sa MM200"))
        if self.fills:
            lines.append("\n<b>Ordres exécutés ce matin (simulation)</b>")
            lines += [f"• {f['action']} {f['quantite']} {f['ticker']} à {f['prix']:.2f} $" for f in self.fills]
        if self.signal and self.targets is not None:
            lines.append("\n<b>🔔 Rééquilibrage mensuel — cibles</b>")
            for t, w in sorted(self.targets.items(), key=lambda x: -x[1]):
                lines.append(f"• {t} ({U.group_of(t)}) : {w:.1%}")
            cash_w = 1 - sum(self.targets.values())
            if cash_w > 0.005:
                lines.append(f"• Cash : {cash_w:.1%}")
            lines.append("\n<b>Ordres prévus à l'ouverture de demain</b>")
            lines += [f"• {o['action']} {o['quantite']} {o['ticker']} (réf. {o['cours_ref']} $)" for o in self.orders] or ["• aucun"]
            lines.append("\nPaper trading : aucun ordre réel n'est passé.")
        return "\n".join(lines)


def run_daily(data: dict[str, pd.DataFrame], capital: float = 50_000.0, force_signal: bool = False) -> tuple[DailyReport, PaperState]:
    state = PaperState.load(capital)
    open_, close = build_panel(data, U.BENCHMARK)
    day = close.index[-1]

    if state.start_date is None:
        state.start_date = day.date().isoformat()
        state.spy_start = float(close.at[day, "SPY"])

    fills = execute_pending(state, open_, day)

    signal = (is_month_end(day) or force_signal) and state.last_signal_date != day.date().isoformat()
    targets, orders = None, []
    if signal:
        targets = combined_targets(close, day)
        orders = planned_orders(state, targets, close.loc[day])
        state.pending = {"signal_date": day.date().isoformat(), "weights": targets}
        state.last_signal_date = day.date().isoformat()
        (paper_dir() / f"orders_{day.date().isoformat()}.json").write_text(
            json.dumps({"signal_date": day.date().isoformat(), "targets": targets, "orders": orders}, indent=2), encoding="utf-8"
        )

    value = portfolio_value(state, close.loc[day])
    spy_value = state.initial_capital * float(close.at[day, "SPY"]) / state.spy_start if state.spy_start else None
    spy = close["SPY"]
    above = bool(spy.iloc[-1] > spy.rolling(200).mean().iloc[-1])
    eq_path = paper_dir() / "equity.csv"
    if not eq_path.exists() or day.date().isoformat() not in eq_path.read_text():
        _append_csv(eq_path, [{"date": day.date().isoformat(), "valeur": round(value, 2),
                               "spy_equivalent": round(spy_value, 2) if spy_value else None}])
    state.save()
    return DailyReport(day, value, spy_value, fills, signal, targets, orders, above), state


def send_telegram(text: str) -> bool:
    """Envoie un message si TELEGRAM_TOKEN et CHAT_ID sont définis. Renvoie True si envoyé."""
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("CHAT_ID")
    if not token or not chat:
        return False
    import requests

    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text, "parse_mode": "HTML"}, timeout=15)
        return r.ok
    except Exception as e:  # le rapport reste disponible dans les fichiers même si Telegram échoue
        log.warning("Envoi Telegram impossible : %s", e)
        return False
