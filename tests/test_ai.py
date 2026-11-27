"""Tests des agents IA avec un faux client Claude (aucun appel réseau, aucun coût)."""

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Nvidia beats estimates as AI demand surges</title><link>http://a</link>
<pubDate>{d}</pubDate><source url="x">Reuters</source></item>
<item><title>Old news</title><link>http://b</link><pubDate>Mon, 01 Jan 2018 10:00:00 GMT</pubDate><source url="y">X</source></item>
</channel></rss>"""


class FakeMessages:
    def __init__(self, answers, calls):
        self.answers, self.calls = answers, calls

    def create(self, **kw):
        self.calls.append(kw)
        agent_schema = kw["output_config"]["format"]["schema"].get("properties", {})
        if "decisions" in agent_schema:
            payload = self.answers["committee"]
        elif "regime" in agent_schema:
            payload = self.answers["macro"]
        else:
            payload = dict(self.answers["news"])
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(payload))],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=500, cache_read_input_tokens=0, cache_creation_input_tokens=0),
            stop_reason=self.answers.get("stop_reason", "end_turn"),
            model=kw["model"],
        )


class FakeClient:
    def __init__(self, answers):
        self.calls = []
        self.messages = FakeMessages(answers, self.calls)
        self.beta = SimpleNamespace(messages=FakeMessages(answers, self.calls))


ANSWERS = {
    "news": {"ticker": "X", "resume": "Résultats solides.", "sentiment": "positif", "catalyseur": "resultats",
             "risque_majeur": False, "raison_risque": "", "themes": ["ia", "resultats"], "titres_pertinents": 1},
    "macro": {"regime": "ralentissement", "confiance": "moyenne", "resume": "Marché sous pression <test>.",
              "risques": ["taux"], "secteurs_favorables": ["XLU"], "secteurs_defavorables": ["XLK"],
              "evenements_a_surveiller": ["Fed"]},
    "committee": {"decisions": [{"ticker": "AAPL", "decision": "confirmer", "niveau_risque": "faible",
                                 "justification": "Rien à signaler & tendance intacte."}],
                  "commentaire_global": "RAS."},
}


@pytest.fixture
def ai_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SWING_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AI_ENABLED", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("AI_MONTHLY_BUDGET", "150")
    return tmp_path


def fake_fetch(query, days=3, limit=10, session=None):
    from swing.ai.news import parse_rss
    from email.utils import format_datetime
    from datetime import datetime, timezone
    items = parse_rss(RSS.format(d=format_datetime(datetime.now(timezone.utc))))
    return items[:1]


def test_parse_rss_reads_title_source_date():
    from swing.ai.news import parse_rss
    items = parse_rss(RSS.format(d="Fri, 27 Nov 2026 10:00:00 GMT"))
    assert items[0].title.startswith("Nvidia")
    assert items[0].source == "Reuters"
    assert items[0].published.year == 2026


def test_news_agent_logs_results_and_cost(ai_env):
    from swing.ai.llm import LLM, spent_this_month
    from swing.ai.news import run_news
    client = FakeClient(ANSWERS)
    res = run_news(LLM(client), ["NVDA", "T"], fetch=fake_fetch)
    assert [r["ticker"] for r in res] == ["NVDA", "T"]
    assert (ai_env / "ai" / "news.csv").exists()
    # Haiku : pas de repli serveur, endpoint standard, sortie JSON imposée
    assert all(c["model"] == "claude-haiku-5-5" and "fallbacks" not in c for c in client.calls)
    assert client.calls[0]["output_config"]["format"]["type"] == "json_schema"
    expected = 2 * (1000 * 0.10 + 500 * 0.50) / 1e6
    assert spent_this_month() == pytest.approx(expected, rel=1e-3)


def test_opus_and_sonnet_use_server_fallback(ai_env):
    from swing.ai.committee import run_committee
    from swing.ai.llm import LLM
    client = FakeClient(ANSWERS)
    run_committee(LLM(client), "2026-11-30", {"AAPL": 0.1, "SPY": 0.5}, [])
    call = client.calls[-1]
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert (ai_env / "ai" / "committee.csv").exists()


def test_budget_blocks_calls(ai_env, monkeypatch):
    from swing.ai.llm import LLM, BudgetExceeded
    monkeypatch.setenv("AI_MONTHLY_BUDGET", "0")
    with pytest.raises(BudgetExceeded):
        LLM(FakeClient(ANSWERS)).call_json("x", "claude-haiku-5-5", "s", "p", {"type": "object", "required": []})


def test_refusal_and_truncation_raise(ai_env):
    from swing.ai.llm import LLM, AIError
    for reason in ("refusal", "max_tokens"):
        answers = dict(ANSWERS, stop_reason=reason)
        with pytest.raises(AIError):
            LLM(FakeClient(answers)).call_json("x", "claude-haiku-5-5", "s", "p", {"type": "object", "required": []})


def test_theme_acceleration_detected():
    from swing.ai.themes import accelerating
    idx = [f"2026-11-{d:02d}" for d in range(1, 16)]
    counts = pd.DataFrame({"ia": [2] * 14 + [3], "nucleaire_uranium": [0, 1] * 7 + [6]}, index=idx)
    alerts = accelerating(counts)
    assert [a["theme"] for a in alerts] == ["nucleaire_uranium"]
    assert accelerating(counts.iloc[:5]) == []  # pas assez d'historique


def test_pipeline_end_to_end_escapes_html(ai_env):
    from swing.ai import pipeline
    from swing.ai.llm import LLM
    idx = pd.bdate_range("2025-01-01", periods=300)
    rng = np.random.default_rng(0)
    close = pd.DataFrame({t: 100 * np.exp(np.cumsum(rng.normal(0.001, 0.01, 300))) for t in ["SPY", "AAPL", "MSFT", "XLK", "XLU"]}, index=idx)
    import swing.ai.news as news_mod
    orig = news_mod.fetch_headlines
    news_mod.fetch_headlines = fake_fetch
    try:
        pipeline.run_news.__globals__["run_news"]  # import présent
        text = pipeline.run_ai(close, idx[-1], {"AAPL": 10}, {"AAPL": 0.2, "SPY": 0.5}, signal=True, llm=LLM(FakeClient(ANSWERS)))
    finally:
        news_mod.fetch_headlines = orig
    assert "Agents IA" in text and "Comité" in text and "Macro" in text
    assert "&lt;test&gt;" in text and "&amp;" in text  # texte des agents échappé pour Telegram
    assert "Coût IA ce mois" in text


def test_pipeline_disabled_without_flag(monkeypatch):
    from swing.ai.pipeline import enabled
    monkeypatch.delenv("AI_ENABLED", raising=False)
    assert enabled()[0] is False


def test_split_message_respects_limit():
    from swing.live import split_message
    text = "\n".join(["x" * 100] * 100)
    chunks = split_message(text, limit=1000)
    assert all(len(c) <= 1000 for c in chunks)
    assert "\n".join(chunks) == text
