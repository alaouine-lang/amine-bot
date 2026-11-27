"""Agent Actualités : récupère les titres de presse récents (Google News RSS) et les fait
classer par Claude Haiku (pertinence, sentiment, catalyseur, risque, thèmes).

Un appel par ticker, pour des réponses courtes et un coût très faible.
"""

from __future__ import annotations

import email.utils
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote_plus

import pandas as pd

from .llm import LLM, MODEL_NEWS, ai_dir, strict_object

# Vocabulaire fermé de thèmes : indispensable pour compter les thèmes d'un jour à l'autre
THEMES = [
    "ia", "semi_conducteurs", "cloud_logiciel", "taux_fed", "inflation", "emploi", "droits_douane",
    "chine", "geopolitique_guerre", "petrole_energie", "or_metaux", "defense", "nucleaire_uranium",
    "resultats", "previsions", "fusion_acquisition", "regulation", "antitrust", "proces",
    "medicament_fda", "consommation", "immobilier", "banques_credit", "crypto", "cybersecurite",
    "licenciements", "rachat_actions", "dividende", "direction", "autre",
]
CATALYSTS = ["resultats", "previsions", "produit", "contrat", "fusion_acquisition", "regulation",
             "proces", "direction", "macro", "analyste", "aucun"]

NEWS_SCHEMA = strict_object({
    "ticker": {"type": "string"},
    "resume": {"type": "string", "description": "2 phrases maximum, en français"},
    "sentiment": {"type": "string", "enum": ["tres_negatif", "negatif", "neutre", "positif", "tres_positif"]},
    "catalyseur": {"type": "string", "enum": CATALYSTS},
    "risque_majeur": {"type": "boolean", "description": "vrai si un titre signale un risque sérieux pour l'action"},
    "raison_risque": {"type": "string", "description": "vide si aucun risque majeur"},
    "themes": {"type": "array", "items": {"type": "string", "enum": THEMES}},
    "titres_pertinents": {"type": "integer", "description": "nombre de titres réellement liés à l'entreprise"},
})

SYSTEM = (
    "Tu es analyste actions. On te donne des titres de presse récents sur une entreprise ou un ETF coté aux États-Unis. "
    "Tu évalues uniquement ce que disent ces titres, sans inventer d'information ni utiliser tes connaissances pour "
    "compléter. Ignore les titres sans rapport avec l'entreprise, les publicités et les simples listes d'actions. "
    "Si les titres sont peu nombreux ou peu informatifs, dis-le dans le résumé et reste neutre. Réponds en français."
)


@dataclass
class Headline:
    title: str
    source: str
    published: datetime | None
    link: str


def google_news_url(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"


def parse_rss(xml_text: str) -> list[Headline]:
    root = ET.fromstring(xml_text)
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        src_el = item.find("source")
        source = (src_el.text or "").strip() if src_el is not None else ""
        pub = item.findtext("pubDate")
        try:
            published = email.utils.parsedate_to_datetime(pub) if pub else None
        except (TypeError, ValueError):
            published = None
        out.append(Headline(title, source, published, (item.findtext("link") or "").strip()))
    return out


def fetch_headlines(query: str, days: int = 3, limit: int = 10, session=None) -> list[Headline]:
    import requests

    get = (session or requests).get
    r = get(google_news_url(query), timeout=15, headers={"User-Agent": "Mozilla/5.0 (swing-research)"})
    r.raise_for_status()
    items = parse_rss(r.text)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = [h for h in items if h.published is None or h.published >= cutoff]
    recent.sort(key=lambda h: h.published or cutoff, reverse=True)
    return recent[:limit]


# Tickers trop courts ou ambigus pour une recherche de presse : on cherche le nom de l'entreprise
NAMES = {
    "T": "AT&T", "C": "Citigroup", "D": "Dominion Energy", "F": "Ford Motor", "O": "Realty Income",
    "V": "Visa", "MA": "Mastercard", "MS": "Morgan Stanley", "GS": "Goldman Sachs", "GM": "General Motors",
    "GE": "GE Aerospace", "SO": "Southern Company", "PM": "Philip Morris", "MO": "Altria", "CL": "Colgate-Palmolive",
    "DE": "Deere", "BA": "Boeing", "CAT": "Caterpillar", "WM": "Waste Management", "LOW": "Lowe's",
    "HD": "Home Depot", "KO": "Coca-Cola", "PG": "Procter & Gamble", "MU": "Micron Technology",
}


def query_for(ticker: str) -> str:
    if ticker in NAMES:
        return f'"{NAMES[ticker]}" stock'
    return f"{ticker} stock"


def analyze_ticker(llm: LLM, ticker: str, name_hint: str, headlines: list[Headline]) -> dict:
    lines = [
        f"- [{h.published.date() if h.published else '?'}] {h.title} ({h.source})" for h in headlines
    ] or ["(aucun titre récent)"]
    prompt = (
        f"Ticker : {ticker} ({name_hint})\nTitres des 3 derniers jours :\n" + "\n".join(lines) +
        "\n\nClasse ces informations selon le schéma demandé."
    )
    return llm.call_json("actualites", MODEL_NEWS, SYSTEM, prompt, NEWS_SCHEMA, effort="low", max_tokens=4000, est_cost=0.01)


def run_news(llm: LLM, tickers: list[str], names: dict[str, str] | None = None, fetch=fetch_headlines) -> list[dict]:
    """Analyse chaque ticker et ajoute les résultats au journal data/ai/news.csv."""
    names = names or {}
    results = []
    for t in tickers:
        try:
            heads = fetch(query_for(t))
        except Exception as e:  # une source de presse indisponible ne doit pas tout bloquer
            results.append({"ticker": t, "erreur": f"presse indisponible : {type(e).__name__}"})
            continue
        res = analyze_ticker(llm, t, names.get(t, NAMES.get(t, t)), heads)
        res["ticker"] = t
        res["nb_titres"] = len(heads)
        results.append(res)
    rows = [
        {"date": date.today().isoformat(), **{k: (json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v)
                                           for k, v in r.items()}}
        for r in results if "erreur" not in r
    ]
    if rows:
        path = ai_dir() / "news.csv"
        pd.DataFrame(rows).to_csv(path, mode="a", header=not path.exists(), index=False)
    return results
