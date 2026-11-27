"""Chargement des réglages secrets depuis un fichier .env à la racine du dépôt.

Format du fichier (une variable par ligne) :
    TELEGRAM_TOKEN=123456789:ABC...
    CHAT_ID=123456789
Les lignes vides et celles qui commencent par # sont ignorées. Les variables déjà
définies dans Windows ne sont pas écrasées. Le fichier .env n'est jamais envoyé
sur GitHub (il est listé dans .gitignore).
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env(path: Path = ENV_FILE) -> list[str]:
    """Charge les variables du fichier .env ; renvoie les noms chargés."""
    if not path.exists():
        return []
    loaded = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded
