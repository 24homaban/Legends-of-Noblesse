from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(eq=False)
class Card:
    name: str
    card_type: str
    cost: dict[str, int] = field(default_factory=dict)
    might: int | None = None
    will_: int | None = None
    ability: str | None = None
    description: str | None = None
    line: str | None = None
    revealed: bool = False
    xp: str | None = None
    xp_description: str | None = None
    levels: list[dict[str, Any]] = field(default_factory=list)

    # Runtime mutable combat fields.
    temp_might_bonus: int = 0
    temp_will_bonus: int = 0
    temp_line_override: str | None = None
    shield_used_this_siege: bool = False
    from_barracks: bool = False
    hand_source: str | None = None
    paid_cost: dict[str, int] = field(default_factory=dict)

    owner_index: int | None = None

    def clone(self) -> "Card":
        return Card(
            name=self.name,
            card_type=self.card_type,
            cost=dict(self.cost),
            might=self.might,
            will_=self.will_,
            ability=self.ability,
            description=self.description,
            line=self.line,
            revealed=self.revealed,
            xp=self.xp,
            xp_description=self.xp_description,
            levels=[dict(level) for level in self.levels],
            temp_might_bonus=self.temp_might_bonus,
            temp_will_bonus=self.temp_will_bonus,
            temp_line_override=self.temp_line_override,
            shield_used_this_siege=self.shield_used_this_siege,
            from_barracks=self.from_barracks,
            hand_source=self.hand_source,
            paid_cost=dict(self.paid_cost),
            owner_index=self.owner_index,
        )

    def effective_line(self) -> str | None:
        return self.temp_line_override if self.temp_line_override else self.line

    def base_power_sum(self) -> int:
        return (self.might or 0) + (self.will_ or 0)

    def clear_temporary_state(self) -> None:
        self.temp_might_bonus = 0
        self.temp_will_bonus = 0
        self.temp_line_override = None
        self.paid_cost = {}


@dataclass
class Barracks:
    card: Card
    units: list[Card] = field(default_factory=list)


@dataclass
class Battalion:
    cards: list[Card] = field(default_factory=list)
    max_front_size: int = 3
    max_back_size: int = 3

    @staticmethod
    def _normalize_line(line: str | None) -> str | None:
        if line is None:
            return None
        normalized = line.strip().lower()
        if normalized == "front":
            return "front"
        if normalized == "back":
            return "back"
        return None

    @classmethod
    def _card_line(cls, card: Card) -> str | None:
        # Use a card's base line whenever possible so temporary siege swaps
        # do not affect battalion slot validation.
        return cls._normalize_line(card.line or card.effective_line())

    def _line_count(self, line: str, excluding: Card | None = None) -> int:
        normalized = self._normalize_line(line)
        if normalized is None:
            return 0
        return sum(
            1
            for existing in self.cards
            if existing is not excluding and self._card_line(existing) == normalized
        )

    def has_room(self, card: Card | None = None, excluding: Card | None = None) -> bool:
        front_count = self._line_count("front", excluding=excluding)
        back_count = self._line_count("back", excluding=excluding)
        if card is None:
            return front_count < self.max_front_size or back_count < self.max_back_size

        line = self._card_line(card)
        if line == "front":
            return front_count < self.max_front_size
        if line == "back":
            return back_count < self.max_back_size
        return False
