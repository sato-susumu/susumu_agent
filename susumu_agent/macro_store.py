from __future__ import annotations

import json
from pathlib import Path

MACRO_FILE = Path("macros.json")


def load_macros() -> dict:
    if not MACRO_FILE.exists():
        return {}
    return json.loads(MACRO_FILE.read_text(encoding="utf-8"))


def save_macro(name: str, steps: list[dict]) -> None:
    macros = load_macros()
    macros[name] = {"steps": steps}
    MACRO_FILE.write_text(json.dumps(macros, ensure_ascii=False, indent=2), encoding="utf-8")


def delete_macro(name: str) -> bool:
    macros = load_macros()
    if name not in macros:
        return False
    del macros[name]
    MACRO_FILE.write_text(json.dumps(macros, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def get_macro(name: str) -> list[dict] | None:
    return load_macros().get(name, {}).get("steps")


def list_macros() -> list[str]:
    return list(load_macros().keys())
