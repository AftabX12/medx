"""Load JSON schemas (cached) by name."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_SCHEMA_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict:
    path = _SCHEMA_DIR / f"{name}.schema.json"
    return json.loads(path.read_text())
