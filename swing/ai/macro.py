"""Agent Macro (Claude Sonnet), hebdomadaire : régime de marché, risques, secteurs.

Il reçoit des CHIFFRES calculés par le code (tendances, performances sectorielles,
volatilité) et des titres de presse macro. Il ne calcule rien lui-même.
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

from .. import universe as U
from .llm import LLM, MODEL_MACRO, ai_dir, strict_object
from .news import Headline, fetch_headlines

MACRO_QUERIES = ["Federal Reserve interest rates", "US inflation CPI", "US jobs report unemployment",
                 "tariffs trade war", "oil prices OPEC", "stock market selloff", "recession risk"]
SECTOR_ETFS = U.ETFS["sectors"] + ["GLD", "SLV", "USO", "TLT", "IEF", "HYG"]

MACRO_SCHEMA = strict_object({
    "regime": {"type": "string", "enum": ["expansion", "ralentissement", "stress", "rebond", "incertain"]},
    "confiance": {"type": "string", "enum": ["faible", "moyenne", "elevee"]},
    "resume": {"type": "string", "description": "5 phrases maximum, en français"},
    "risques": {"type": "array", "items": {"type": "string"}, "description": "3 risques principaux au plus"},
    "secteurs_favorables": {"type": "array", "items": {"type": "string", "enum": SECTOR_ETFS}},
    "secteurs_defavorables": {"type": "array", "items": {"type": "string", "enum": SECTOR_ETFS}},
    "evenements_a_surveiller": {"type": "array", "items": {"type": "string"}},
})

SYSTEM = (
    "Tu es stratégiste macroéconomique pour un investisseur particulier en swing trading (positions de quelques "
    "jours à quelques semaines) sur les actions américaines, les ETF et les matières premières. Appuie-toi "
    "uniquement sur les chiffres et les titres fournis ; tes connaissances générales peuvent servir à interpréter, "
    "mais n'affirme aucun fait récent absent des données. Distingue clairement les faits des interprétations. "
    "Si les données sont contradictoires, choisis 'incertain'. Réponds en français."
)


def market_table(close: pd.DataFrame) -> str:
    rows = []
    for t in ["SPY", "QQQ", "IWM"] + SECTOR_ETFS:
        if t not in close:
            continue
        c = close[t].dropna()
        if len(c) < 210:
            continue
        rows.append(
            f"{t:5} 1 mois {c.iloc[-1] / c.iloc[-22] - 1:+.1%} | 3 mois {c.iloc[-1] / c.iloc[-64] - 1:+.1%} | "
            f"vs MM200 {c.iloc[-1] / c.rolling(200).mean().iloc[-1] - 1:+.1%}"
        )
    spy = close["SPY"].dropna()
    vol = spy.pct_change().iloc[-21:].std() * (252 ** 0.5)
    rows.append(f"Volatilité réalisée du SPY sur 1 mois : {vol:.0%}")
    return "\n".join(rows)


def run_macro(llm: LLM, close: pd.DataFrame, theme_alerts: list[dict], fetch=fetch_headlines) -> dict:
    heads: list[Headline] = []
    for q in MACRO_QUERIES:
        try:
            heads += fetch(q, days=7, limit=6)
        except Exception:
            continue
    news = "\n".join(f"- [{h.published.date() if h.published else '?'}] {h.title} ({h.source})" for h in heads) or "(aucun)"
    themes = "\n".join(f"- {a['theme']} : {a['mentions']} mentions (habituellement {a['moyenne']})" for a in theme_alerts) or "(aucun)"
    prompt = (
        f"Date : {close.index[-1].date()}\n\nCHIFFRES DE MARCHÉ (calculés) :\n{market_table(close)}\n\n"
        f"THÈMES EN ACCÉLÉRATION dans la presse sur nos actions :\n{themes}\n\nTITRES MACRO DE LA SEMAINE :\n{news}"
    )
    res = llm.call_json("macro", MODEL_MACRO, SYSTEM, prompt, MACRO_SCHEMA, effort="medium", max_tokens=16000, est_cost=0.3)
    row = {"date": date.today().isoformat(), **{k: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v for k, v in res.items()}}
    path = ai_dir() / "macro.csv"
    pd.DataFrame([row]).to_csv(path, mode="a", header=not path.exists(), index=False)
    return res
