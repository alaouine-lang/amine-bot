"""Appels à l'API Claude avec réponse JSON imposée, suivi des coûts et plafond mensuel.

Clé API : variable ANTHROPIC_API_KEY (fichier .env). Plafond : AI_MONTHLY_BUDGET (défaut 150 $).
Les prix ci-dessous viennent de la documentation Anthropic de novembre 2026 ; ils
peuvent changer : vérifier la page officielle des tarifs. Le suivi des coûts est une
estimation (les tokens de réflexion sont inclus dans output_tokens).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from ..data import data_dir

MODEL_NEWS = os.environ.get("AI_MODEL_NEWS", "claude-haiku-5-5")
MODEL_MACRO = os.environ.get("AI_MODEL_MACRO", "claude-sonnet-5-5")
MODEL_COMMITTEE = os.environ.get("AI_MODEL_COMMITTEE", "claude-opus-5-5")

# $ par million de tokens (entrée, sortie)
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
}
UNKNOWN_PRICE = (10.00, 50.00)  # prudent si un modèle de repli inconnu a répondu

# Modèles pour lesquels on active le repli automatique côté serveur en cas de refus
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class BudgetExceeded(RuntimeError):
    pass


class AIError(RuntimeError):
    pass


def ai_dir() -> Path:
    p = data_dir() / "ai"
    p.mkdir(parents=True, exist_ok=True)
    return p


def monthly_budget() -> float:
    try:
        return float(os.environ.get("AI_MONTHLY_BUDGET", "150"))
    except ValueError:
        return 150.0


def spent_this_month(today: date | None = None) -> float:
    path = ai_dir() / "usage.csv"
    if not path.exists():
        return 0.0
    df = pd.read_csv(path)
    if df.empty:
        return 0.0
    month = (today or date.today()).strftime("%Y-%m")
    return float(df.loc[df["date"].astype(str).str.startswith(month), "cout_usd"].sum())


def cost_of(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = PRICES.get(model, UNKNOWN_PRICE)
    return input_tokens * pin / 1e6 + output_tokens * pout / 1e6


def _log_usage(agent: str, model: str, usage) -> float:
    inp = int(getattr(usage, "input_tokens", 0) or 0)
    inp += int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    inp += int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    out = int(getattr(usage, "output_tokens", 0) or 0)
    cost = cost_of(model, inp, out)
    row = pd.DataFrame([{
        "date": date.today().isoformat(), "heure": datetime.now().strftime("%H:%M:%S"),
        "agent": agent, "modele": model, "tokens_entree": inp, "tokens_sortie": out, "cout_usd": round(cost, 6),
    }])
    path = ai_dir() / "usage.csv"
    row.to_csv(path, mode="a", header=not path.exists(), index=False)
    return cost


@dataclass
class LLM:
    """Petit client : un appel = un JSON validé par le schéma fourni."""

    client: object | None = None

    def _client(self):
        if self.client is None:
            import anthropic

            self.client = anthropic.Anthropic()
        return self.client

    def call_json(
        self,
        agent: str,
        model: str,
        system: str,
        prompt: str,
        schema: dict,
        effort: str = "medium",
        max_tokens: int = 16000,
        est_cost: float = 0.05,
    ) -> dict:
        if spent_this_month() + est_cost > monthly_budget():
            raise BudgetExceeded(
                f"Plafond mensuel atteint ({spent_this_month():.2f} $ / {monthly_budget():.0f} $) : agent {agent} non lancé"
            )
        params = dict(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        )
        client = self._client()
        if model in FALLBACK_MODELS:
            resp = client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
        else:
            resp = client.messages.create(**params)
        served = getattr(resp, "model", model) or model
        _log_usage(agent, served, resp.usage)

        if resp.stop_reason == "refusal":
            raise AIError(f"L'agent {agent} a refusé de répondre ({getattr(resp, 'stop_details', None)})")
        if resp.stop_reason == "max_tokens":
            raise AIError(f"Réponse de l'agent {agent} tronquée (max_tokens atteint)")
        text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), None)
        if text is None:
            raise AIError(f"Réponse de l'agent {agent} sans texte")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise AIError(f"JSON invalide de l'agent {agent} : {e}") from e
        missing = [k for k in schema.get("required", []) if k not in data]
        if missing:
            raise AIError(f"Champs manquants dans la réponse de {agent} : {missing}")
        return data


def strict_object(properties: dict, required: list[str] | None = None) -> dict:
    """Schéma JSON d'objet strict (tous les champs requis, aucun champ en plus)."""
    return {
        "type": "object",
        "properties": properties,
        "required": required if required is not None else list(properties),
        "additionalProperties": False,
    }
