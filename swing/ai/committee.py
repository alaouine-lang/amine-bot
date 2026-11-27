"""Comité (Claude Opus), en fin de mois : revue des positions cibles de la stratégie.

Pour chaque position, le comité confirme, alerte ou suggère un veto, avec une justification.
MODE OBSERVATION : ces avis sont enregistrés (data/ai/committee.csv) mais ne changent pas
les ordres. Dans 3 mois, on comparera la performance des positions « vetoées » et des autres
pour savoir si le comité apporte de la valeur.
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

from .. import universe as U
from .llm import LLM, MODEL_COMMITTEE, ai_dir, strict_object

DECISION = strict_object({
    "ticker": {"type": "string"},
    "decision": {"type": "string", "enum": ["confirmer", "alerte", "veto_suggere"]},
    "niveau_risque": {"type": "string", "enum": ["faible", "moyen", "eleve"]},
    "justification": {"type": "string", "description": "3 phrases maximum, en français, en citant les éléments fournis"},
})
COMMITTEE_SCHEMA = strict_object({
    "decisions": {"type": "array", "items": DECISION},
    "commentaire_global": {"type": "string", "description": "4 phrases maximum, en français"},
})

SYSTEM = (
    "Tu présides le comité d'investissement d'un système de swing trading. Une stratégie quantitative, validée par "
    "backtest, a choisi des positions pour le mois. Ton rôle n'est PAS de refaire la stratégie mais de repérer ce que "
    "les chiffres ne voient pas : un risque sérieux et précis dans l'actualité (enquête, procès, résultats ratés, "
    "rupture de tendance sectorielle, choc macro). Par défaut, confirme. Ne suggère un veto que sur un élément "
    "concret présent dans les données fournies, jamais sur une impression. Réponds en français."
)


def _news_digest(tickers: list[str], days: int = 7) -> str:
    path = ai_dir() / "news.csv"
    if not path.exists():
        return "(aucune analyse d'actualité disponible)"
    df = pd.read_csv(path)
    df = df[df["ticker"].isin(tickers)]
    if df.empty:
        return "(aucune analyse d'actualité disponible pour ces titres)"
    recent_dates = sorted(df["date"].astype(str).unique())[-days:]
    df = df[df["date"].astype(str).isin(recent_dates)]
    lines = []
    for t, g in df.groupby("ticker"):
        last = g.iloc[-1]
        risks = [str(x) for x in g.loc[g["risque_majeur"].astype(str) == "True", "raison_risque"] if str(x) not in ("", "nan")]
        lines.append(
            f"{t} : sentiment récent {last['sentiment']}, catalyseur {last['catalyseur']}. {last['resume']}"
            + (f" RISQUES SIGNALÉS : {' | '.join(risks[-3:])}" if risks else "")
        )
    return "\n".join(lines)


def _macro_digest() -> str:
    path = ai_dir() / "macro.csv"
    if not path.exists():
        return "(aucune analyse macro disponible)"
    last = pd.read_csv(path).iloc[-1]
    return (f"Régime : {last['regime']} (confiance {last['confiance']}). {last['resume']} "
            f"Risques : {last['risques']}. Secteurs défavorables : {last['secteurs_defavorables']}.")


def run_committee(llm: LLM, signal_date: str, targets: dict[str, float], theme_alerts: list[dict]) -> dict:
    positions = {t: w for t, w in targets.items() if abs(w) > 1e-6}
    if not positions:
        res = {"decisions": [], "commentaire_global": "Stratégie 100 % cash : rien à examiner."}
    else:
        lines = [f"- {t} ({U.group_of(t)}) : {w:.1%} du capital" for t, w in sorted(positions.items(), key=lambda x: -x[1])]
        themes = ", ".join(f"{a['theme']} (z={a['z']})" for a in theme_alerts) or "aucun"
        prompt = (
            f"Date du signal : {signal_date}\n\nPOSITIONS CIBLES DE LA STRATÉGIE :\n" + "\n".join(lines) +
            f"\n\nACTUALITÉS (agent Actualités, 7 derniers jours) :\n{_news_digest(list(positions))}"
            f"\n\nCONTEXTE MACRO (agent Macro) :\n{_macro_digest()}\n\nTHÈMES EN ACCÉLÉRATION : {themes}"
            "\n\nDonne une décision pour CHAQUE position listée."
        )
        res = llm.call_json("comite", MODEL_COMMITTEE, SYSTEM, prompt, COMMITTEE_SCHEMA, effort="high",
                            max_tokens=32000, est_cost=0.8)
    rows = [{"date_signal": signal_date, "poids": targets.get(d["ticker"], 0.0), **d} for d in res["decisions"]]
    if rows:
        path = ai_dir() / "committee.csv"
        pd.DataFrame(rows).to_csv(path, mode="a", header=not path.exists(), index=False)
    (ai_dir() / f"committee_{signal_date}.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    return res
