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


def _read_text(path: Path) -> str:
    """Lit le fichier quel que soit l'encodage choisi par le Bloc-notes (UTF-8, UTF-16, ANSI)."""
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("export "):
            line = line[7:]
        if line.startswith("$env:"):
            line = line[5:]
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def load_env(path: Path = ENV_FILE) -> list[str]:
    """Charge les variables du fichier .env ; renvoie les noms chargés.

    Le fichier .env est PRIORITAIRE sur les variables Windows : c'est le réglage
    explicite du projet (une ancienne variable Windows ne doit pas le masquer).
    """
    if not path.exists():
        return []
    loaded = []
    for key, value in parse_env(_read_text(path)).items():
        if value:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def diagnose(path: Path = ENV_FILE) -> str:
    """Résumé lisible du fichier .env, sans jamais afficher les valeurs secrètes."""
    import re

    if not path.exists():
        return f"Fichier introuvable : {path}"
    values = parse_env(_read_text(path))
    lines = [f"Fichier : {path}", f"Variables reconnues : {', '.join(values) or 'AUCUNE'}"]
    for key in ("TELEGRAM_TOKEN", "CHAT_ID"):
        v = values.get(key)
        if v is None:
            lines.append(f"  {key} : absent du fichier")
            continue
        lines.append(f"  {key} : présent ({len(v)} caractères)")
        win = os.environ.get(key)
        if win and win != v:
            lines.append(f"  {key} : une AUTRE valeur existe dans Windows (le fichier .env est désormais prioritaire)")
        if any(ord(ch) > 127 or ch.isspace() for ch in v):
            lines.append(f"  {key} : contient un espace ou un caractère spécial invisible → à retaper")
    tok = values.get("TELEGRAM_TOKEN")
    if tok and not re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{30,}", tok):
        lines.append("  TELEGRAM_TOKEN : format inattendu (attendu : chiffres, deux-points, puis lettres/chiffres)")
    chat = values.get("CHAT_ID")
    if chat and not re.fullmatch(r"-?\d+", chat):
        lines.append("  CHAT_ID : format inattendu (attendu : uniquement des chiffres)")
    return "\n".join(lines)
