from __future__ import annotations

import json
from pathlib import Path


class MacroStore:
    def __init__(self, path: Path = Path("macros.json")) -> None:
        self._path = path

    def _load(self) -> dict:
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text(encoding="utf-8"))

    def _save(self, macros: dict) -> None:
        self._path.write_text(json.dumps(macros, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_macro(self, name: str, steps: list[dict]) -> None:
        macros = self._load()
        macros[name] = {"steps": steps}
        self._save(macros)

    def delete_macro(self, name: str) -> bool:
        macros = self._load()
        if name not in macros:
            return False
        del macros[name]
        self._save(macros)
        return True

    def get_macro(self, name: str) -> list[dict] | None:
        return self._load().get(name, {}).get("steps")

    def list_macros(self) -> list[str]:
        return list(self._load().keys())
