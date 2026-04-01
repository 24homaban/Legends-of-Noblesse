from __future__ import annotations

from collections import Counter

from .card_loader import create_card
from .models import Card


PREMADE_DECKS: dict[str, dict[str, int]] = {
    "Inspiring Defenders": {
        "Zealous Standard-Bearer": 4,
        "Ironclad Phalanx": 4,
        "Hollowed Sentry": 4,
        "Conscripted Militia": 1,
        "Alchemical Chirurgeon": 4,
        "Camp Scout": 3,
        "Pikeline Recruit": 2,
        "Supply Runner": 2,
        "Shield Initiate": 2,
        "Iron Discipline": 2,
        "Supply Cache": 2,
    },
    "Arcane Manipulators": {
        "Spire Mind-Bender": 4,
        "Arcane Bombardier": 4,
        "Occultic Blood-Mage": 4,
        "Zealous Standard-Bearer": 1,
        "Forged Dreadnought": 4,
        "Conscripted Militia": 2,
        "Pikeline Recruit": 4,
        "Shield Initiate": 3,
        "Aegis Pulse": 2,
        "Reserve Rotation": 2,
    },
    "Relentless Assault": {
        "Volatile Slag-Brute": 4,
        "Ironclad Phalanx": 2,
        "Conscripted Militia": 1,
        "Forged Dreadnought": 4,
        "Arcane Bombardier": 4,
        "Zealous Standard-Bearer": 2,
        "Camp Scout": 3,
        "Pikeline Recruit": 1,
        "Supply Runner": 4,
        "Shield Initiate": 1,
        "Entrench": 2,
        "Sabotage Lines": 2,
    },
    "Sacrificial Cult": {
        "Occultic Blood-Mage": 4,
        "Zealous Standard-Bearer": 4,
        "Hollowed Sentry": 4,
        "Arcane Bombardier": 1,
        "Spire Mind-Bender": 4,
        "Conscripted Militia": 2,
        "Pikeline Recruit": 4,
        "Shield Initiate": 3,
        "Rite of Ash": 2,
        "Mass Benediction": 2,
    },
    "Siege Masters": {
        "Forged Dreadnought": 4,
        "Ironclad Phalanx": 2,
        "Volatile Slag-Brute": 4,
        "Alchemical Chirurgeon": 4,
        "Conscripted Militia": 2,
        "Arcane Bombardier": 2,
        "Camp Scout": 3,
        "Pikeline Recruit": 1,
        "Supply Runner": 4,
        "Supply Cache": 2,
        "Entrench": 2,
    },
}


def validate_deck_map(deck_map: dict[str, int]) -> tuple[bool, str]:
    total_cards = sum(deck_map.values())
    if total_cards != 30:
        return False, f"Deck must contain exactly 30 cards (found {total_cards})."
    too_many = [name for name, count in deck_map.items() if count > 4]
    if too_many:
        return False, f"Deck has cards above copy limit 4: {', '.join(sorted(too_many))}."
    return True, "ok"


def build_deck_from_map(deck_map: dict[str, int], owner_index: int) -> list[Card]:
    ok, msg = validate_deck_map(deck_map)
    if not ok:
        raise ValueError(msg)
    deck: list[Card] = []
    for name, count in deck_map.items():
        for _ in range(count):
            deck.append(create_card(name, owner_index=owner_index, revealed=False))
    return deck


def build_premade_deck(deck_name: str, owner_index: int) -> list[Card]:
    if deck_name not in PREMADE_DECKS:
        raise KeyError(f"Unknown deck name: {deck_name}")
    return build_deck_from_map(PREMADE_DECKS[deck_name], owner_index)


def deck_name_list() -> list[str]:
    return list(PREMADE_DECKS.keys())


def deck_to_name_counter(deck: list[Card]) -> Counter[str]:
    return Counter(card.name for card in deck)
