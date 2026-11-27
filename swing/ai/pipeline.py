"""Enchaînement quotidien des agents IA, lancé après le paper trading (python -m swing live).

Activation : AI_ENABLED=1 et ANTHROPIC_API_KEY dans le fichier .env.
  - chaque soir : agent Actualités sur les positions, les cibles et les meilleurs candidats ;
  - chaque soir : détection des thèmes en accélération (sans IA) ;
  - le vendredi (ou s'il n'existe encore aucune analyse) : agent Macro ;
  - le soir du signal mensuel : Comité sur les positions cibles.
Toute erreur d'un agent est signalée dans le message mais ne bloque ni les autres, ni la stratégie.
"""

from __future__ import annotations

import os
from html import escape

import pandas as pd

from .. import universe as U
from ..portfolio import momentum_score
from .committee import run_committee
from .llm import LLM, AIError, BudgetExceeded, ai_dir, monthly_budget, spent_this_month
from .macro import run_macro
from .news import run_news
from .themes import current_alerts

STOCKS = [t for v in U.STOCKS.values() for t in v]


def e(text: str) -> str:
    """Échappe le texte des agents pour le format HTML de Telegram (sans toucher aux apostrophes)."""
    return escape(str(text), quote=False)


def explain_error(exc: Exception) -> str:
    """Traduit les erreurs de l'API Claude en explication simple."""
    name, msg = type(exc).__name__, str(exc)
    low = msg.lower()
    if name == "AuthenticationError" or "invalid x-api-key" in low:
        return "clé ANTHROPIC_API_KEY refusée (vérifiez la clé dans .env)"
    if "credit balance" in low:
        return "crédits API épuisés (console.anthropic.com → Billing)"
    if name == "RateLimitError":
        return "trop de requêtes, nouvel essai demain"
    if name in ("APIConnectionError", "ConnectError", "ConnectionError"):
        return "connexion à l'API impossible (réseau ?)"
    if name == "NotFoundError":
        return "modèle introuvable (nom de modèle à vérifier dans .env)"
    return f"{name} — {msg[:150]}"


def enabled() -> tuple[bool, str]:
    if os.environ.get("AI_ENABLED", "0") != "1":
        return False, "agents IA désactivés (AI_ENABLED=1 dans .env pour les activer)"
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False, "ANTHROPIC_API_KEY absente du fichier .env"
    return True, ""


def top_candidates(close: pd.DataFrame, n: int = 10) -> list[str]:
    """Les n actions les mieux classées par la rotation (en tendance), même non retenues."""
    score = momentum_score(close[[t for t in STOCKS if t in close]], (63, 126, 252)).iloc[-1]
    sma = close.rolling(200).mean().iloc[-1]
    ok = [t for t in score.dropna().index if score[t] > 0 and close[t].iloc[-1] > sma[t]]
    return sorted(ok, key=lambda t: -score[t])[:n]


def watchlist(close: pd.DataFrame, positions: dict, targets: dict | None) -> list[str]:
    seen: dict[str, None] = {}
    for t in list(positions) + list(targets or {}) + top_candidates(close) + ["SPY"]:
        if t in close.columns and not t.endswith("_INV"):
            seen.setdefault(t, None)
    return list(seen)


def _safe(label: str, fn, errors: list[str]):
    try:
        return fn()
    except BudgetExceeded as exc:
        errors.append(f"💰 {exc}")
    except AIError as exc:
        errors.append(f"⚠️ {label} : {exc}")
    except Exception as exc:  # erreur réseau, clé invalide, crédit épuisé…
        errors.append(f"⚠️ {label} : {explain_error(exc)}")
    return None


def run_ai(close: pd.DataFrame, day: pd.Timestamp, positions: dict, targets: dict | None,
           signal: bool, llm: LLM | None = None) -> str:
    ok, why = enabled()
    if not ok:
        return ""
    llm = llm or LLM()
    errors: list[str] = []
    lines = [f"<b>🤖 Agents IA</b> ({day.date()}) — mode observation, aucun effet sur les ordres"]

    tickers = watchlist(close, positions, targets)
    news = _safe("Actualités", lambda: run_news(llm, tickers), errors) or []
    failed = [r for r in news if "erreur" in r]
    news = [r for r in news if "erreur" not in r]
    flagged = [r for r in news if r.get("risque_majeur")]
    good = [r for r in news if r.get("sentiment") in ("positif", "tres_positif")]
    bad = [r for r in news if r.get("sentiment") in ("negatif", "tres_negatif")]
    if news:
        lines.append(f"\n<b>Actualités</b> : {len(news)} titres analysés — {len(good)} positifs, {len(bad)} négatifs")
    if failed:
        errors.append(f"⚠️ Actualités : presse inaccessible pour {len(failed)} titre(s) sur {len(failed) + len(news)}")
        held = set(positions) | set(targets or {})
        for r in flagged:
            tag = "📌 en portefeuille" if r["ticker"] in held else "candidat"
            lines.append(f"🚩 {r['ticker']} ({tag}) : {e(str(r.get('raison_risque') or r.get('resume')))}")

    alerts = current_alerts()
    if alerts:
        lines.append("\n<b>Signaux faibles</b> (thèmes en accélération)")
        lines += [f"📈 {a['theme']} : {a['mentions']} mentions (habituellement {a['moyenne']})" for a in alerts[:5]]

    macro_exists = (ai_dir() / "macro.csv").exists()
    if day.weekday() == 4 or not macro_exists:
        m = _safe("Macro", lambda: run_macro(llm, close, alerts), errors)
        if m:
            lines.append(f"\n<b>Macro</b> : régime « {m['regime']} » (confiance {m['confiance']})\n{e(m['resume'])}")
            if m["risques"]:
                lines.append("Risques : " + " ; ".join(e(x) for x in m["risques"]))

    if signal and targets is not None:
        c = _safe("Comité", lambda: run_committee(llm, day.date().isoformat(), targets, alerts), errors)
        if c:
            lines.append("\n<b>Comité (fin de mois)</b>")
            icon = {"confirmer": "✅", "alerte": "⚠️", "veto_suggere": "⛔"}
            lines += [f"{icon.get(d['decision'], '•')} {d['ticker']} : {e(d['justification'])}" for d in c["decisions"]]
            lines.append(e(c["commentaire_global"]))

    lines += [e(x) for x in errors]
    lines.append(f"\nCoût IA ce mois : {spent_this_month():.2f} $ / {monthly_budget():.0f} $")
    return "\n".join(lines)
