"""Load safe, data-only Hunter Duel mod packs."""

from __future__ import annotations

import json
from pathlib import Path

from game_core import TechniqueDraft


MOD_HELP = """HUNTER DUEL — FOLDER MODÓW
================================

Do tego folderu możesz wrzucać pliki z końcówką .huntermod.json.
Nie instalujesz ich — po prostu kopiujesz plik i ponownie uruchamiasz grę.

Przykład:
{
  "format": 1,
  "pack_name": "Moje techniki",
  "techniques": [
    {
      "name": "Burza Nen",
      "archetype": "projectile",
      "power": 7,
      "reach": 8,
      "speed": 5,
      "control": 4,
      "color_index": 0
    }
  ]
}

Archetype: impact, projectile, mobility albo counter.
Wartości power/reach/speed/control: od 1 do 10.
color_index: od 0 do 4.

Gra ignoruje wadliwe pliki zamiast się przez nie wyłączyć.
"""


def ensure_mod_folder(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    help_file = directory / "JAK_DODAWAC_MODY.txt"
    if not help_file.exists():
        help_file.write_text(MOD_HELP, encoding="utf-8")


def _integer(value, default, low=1, high=10):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def load_mod_drafts(directory: Path) -> tuple[list[TechniqueDraft], list[str]]:
    ensure_mod_folder(directory)
    drafts: list[TechniqueDraft] = []
    warnings: list[str] = []
    for path in sorted(directory.glob("*.huntermod.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("format") != 1 or not isinstance(payload.get("techniques"), list):
                raise ValueError("nieobsługiwany format")
            for entry in payload["techniques"][:50]:
                if not isinstance(entry, dict):
                    continue
                archetype = entry.get("archetype", "impact")
                if archetype not in ("impact", "projectile", "mobility", "counter"):
                    archetype = "impact"
                drafts.append(
                    TechniqueDraft(
                        name=str(entry.get("name", "Technika z modu"))[:22],
                        archetype=archetype,
                        power=_integer(entry.get("power"), 5),
                        reach=_integer(entry.get("reach"), 5),
                        speed=_integer(entry.get("speed"), 5),
                        control=_integer(entry.get("control"), 5),
                        color_index=_integer(entry.get("color_index"), 0, 0, 4),
                    )
                )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            warnings.append(f"{path.name}: {exc}")
    return drafts, warnings

