from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Card


_CARDS_ROOT = Path(__file__).resolve().parent.parent / "data" / "Cards"
_CARD_DIRS = (
    "Barracks",
    "Battlefields",
    "Classes",
    "Soldiers",
    "Tactics",
)


def _to_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _normalize_cost(raw_cost: Any) -> dict[str, int]:
    if not isinstance(raw_cost, dict):
        return {}
    normalized: dict[str, int] = {}
    for key, raw_value in raw_cost.items():
        if not isinstance(key, str):
            continue
        value = _to_int_or_none(raw_value)
        if value is None:
            continue
        normalized[key] = value
    return normalized


def _load_raw_card_data() -> list[dict[str, Any]]:
    if not _CARDS_ROOT.exists():
        raise FileNotFoundError(f"Cards data directory not found: {_CARDS_ROOT}")

    raw_cards: list[dict[str, Any]] = []
    for directory in _CARD_DIRS:
        dir_path = _CARDS_ROOT / directory
        if not dir_path.exists():
            continue
        for file_path in sorted(dir_path.glob("*.json")):
            payload = json.loads(file_path.read_text(encoding="utf-8-sig"))
            payload["__source_file__"] = str(file_path)
            raw_cards.append(payload)
    return raw_cards


def _normalize_card_payload(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("__source_file__", "<unknown>")

    name = payload.get("name")
    card_type = payload.get("type")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"Invalid card name in {source}")
    if not isinstance(card_type, str) or not card_type.strip():
        raise ValueError(f"Invalid card type in {source}")

    stats = payload.get("stats", {})
    if not isinstance(stats, dict):
        stats = {}
    might = _to_int_or_none(stats.get("might", payload.get("might")))
    will_ = _to_int_or_none(stats.get("will", payload.get("will_", payload.get("will"))))

    levels_raw = payload.get("levels", [])
    levels: list[dict[str, Any]] = []
    if isinstance(levels_raw, list):
        for level in levels_raw:
            if isinstance(level, dict):
                levels.append(dict(level))

    normalized = {
        "name": name.strip(),
        "card_type": card_type.strip(),
        "cost": _normalize_cost(payload.get("cost", {})),
        "might": might,
        "will_": will_,
        "ability": payload.get("ability"),
        "description": payload.get("description"),
        "line": payload.get("line"),
        "xp": payload.get("xp"),
        "xp_description": payload.get("xp_description"),
        "levels": levels,
    }

    if normalized["card_type"] == "Barracks":
        rations = _to_int_or_none(payload.get("rations"))
        if rations is None:
            raise ValueError(f"Barracks missing start rations in {source}")
        normalized["rations"] = rations

    return normalized


def _load_card_defs() -> list[dict[str, Any]]:
    return [_normalize_card_payload(payload) for payload in _load_raw_card_data()]


def _build_library(card_defs: list[dict[str, Any]]) -> dict[str, Card]:
    library: dict[str, Card] = {}
    for entry in card_defs:
        card = Card(
            name=entry["name"],
            card_type=entry["card_type"],
            cost=dict(entry.get("cost", {})),
            might=entry.get("might"),
            will_=entry.get("will_"),
            ability=entry.get("ability"),
            description=entry.get("description"),
            line=entry.get("line"),
            revealed=False,
            xp=entry.get("xp"),
            xp_description=entry.get("xp_description"),
            levels=[dict(level) for level in entry.get("levels", [])],
        )
        library[card.name] = card
    return library


_CARD_DEFS = _load_card_defs()
_CARD_LIBRARY = _build_library(_CARD_DEFS)
_BARRACKS_START_RATIONS = {
    entry["name"]: entry["rations"] for entry in _CARD_DEFS if entry["card_type"] == "Barracks"
}
_NAMES_BY_TYPE: dict[str, list[str]] = {}
for entry in _CARD_DEFS:
    _NAMES_BY_TYPE.setdefault(entry["card_type"], []).append(entry["name"])


def card_library() -> dict[str, Card]:
    return _CARD_LIBRARY


def create_card(name: str, owner_index: int | None = None, revealed: bool = False) -> Card:
    if name not in _CARD_LIBRARY:
        raise KeyError(f"Unknown card name: {name}")
    card = _CARD_LIBRARY[name].clone()
    card.owner_index = owner_index
    card.revealed = revealed
    return card


def barracks_start_rations(name: str) -> int:
    return _BARRACKS_START_RATIONS[name]


def names_for_type(card_type: str) -> list[str]:
    if card_type in _NAMES_BY_TYPE:
        return list(_NAMES_BY_TYPE[card_type])
    return sorted([name for name, card in _CARD_LIBRARY.items() if card.card_type == card_type])


def all_barracks_names() -> list[str]:
    return names_for_type("Barracks")


def all_battlefield_names() -> list[str]:
    return names_for_type("Battlefield")


def all_class_names() -> list[str]:
    return names_for_type("Class")


def all_unit_names() -> list[str]:
    return names_for_type("Unit")


def all_tactic_names() -> list[str]:
    return names_for_type("Tactic")
