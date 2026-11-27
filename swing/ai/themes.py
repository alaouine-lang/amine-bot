"""Détecteur de signaux faibles (sans IA) : un thème « accélère » quand on en parle
nettement plus que d'habitude.

Méthode : nombre de mentions de chaque thème par jour (issu de l'agent Actualités),
comparé à la moyenne et à l'écart-type des 20 jours précédents (score z ≥ 2, et au moins
le double de la moyenne). Il faut
au moins 10 jours d'historique avant de signaler quoi que ce soit.
"""

from __future__ import annotations

import json

import pandas as pd

from .llm import ai_dir

MIN_HISTORY_DAYS = 10
WINDOW = 20
Z_ALERT = 2.0
MIN_MENTIONS = 3


def daily_counts(news: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in news.iterrows():
        try:
            themes = json.loads(r["themes"]) if isinstance(r["themes"], str) else []
        except json.JSONDecodeError:
            themes = []
        for th in themes:
            rows.append({"date": str(r["date"]), "theme": th})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return df.groupby(["date", "theme"]).size().unstack(fill_value=0).sort_index()


def accelerating(counts: pd.DataFrame) -> list[dict]:
    """Thèmes du dernier jour dont le score z dépasse le seuil."""
    if counts.empty or len(counts) < MIN_HISTORY_DAYS + 1:
        return []
    last = counts.iloc[-1]
    hist = counts.iloc[-(WINDOW + 1):-1]
    mean, std = hist.mean(), hist.std(ddof=0).clip(lower=1.0)  # variabilité minimale d'une mention
    out = []
    for th, n in last.items():
        if th == "autre" or n < MIN_MENTIONS:
            continue
        z = (n - mean[th]) / std[th]
        if z >= Z_ALERT and n >= 2 * mean[th]:  # au moins le double de l'habitude
            out.append({"theme": th, "mentions": int(n), "moyenne": round(float(mean[th]), 1), "z": round(float(z), 1)})
    return sorted(out, key=lambda x: -x["z"])


def load_news() -> pd.DataFrame:
    path = ai_dir() / "news.csv"
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def current_alerts() -> list[dict]:
    news = load_news()
    return accelerating(daily_counts(news)) if not news.empty else []
