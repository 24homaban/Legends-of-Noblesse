from __future__ import annotations

from .card_loader import (
    all_barracks_names,
    all_battlefield_names,
    all_class_names,
    all_tactic_names,
    all_unit_names,
)
from .premade_decks import deck_name_list

CUSTOM_DECK_NAME = "Custom Deck"


def setup_options() -> dict[str, list[str]]:
    deck_cards = sorted(all_unit_names() + all_tactic_names())
    deck_names = deck_name_list()
    if CUSTOM_DECK_NAME not in deck_names:
        deck_names.append(CUSTOM_DECK_NAME)
    return {
        "decks": deck_names,
        "deck_cards": deck_cards,
        "classes": all_class_names(),
        "barracks": all_barracks_names(),
        "battlefields": all_battlefield_names(),
    }
