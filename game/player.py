from __future__ import annotations

from dataclasses import dataclass, field
import random

from .models import Barracks, Battalion, Card


RESOURCE_CAPS = {
    "rations": 10,
    "ore": 5,
    "materia": 5,
    "magium": 5,
    "faith": 5,
    "sacrifice": 5,
}


def _new_resource_state() -> dict[str, int]:
    return {
        "rations": 0,
        "ore": 0,
        "materia": 0,
        "magium": 0,
        "faith": 0,
        "sacrifice": 0,
        "tactical_gambit_used": 0,
        "miracle_of_faith_used": 0,
        "total_conquest_used": 0,
        "total_conquest_ready": 0,
        "clairvoyance_used": 0,
        "efficient_tithe_used": 0,
        "war_wrought_used": 0,
        "ironheart_used": 0,
        "tactical_bluff_used": 0,
        "hall_of_mirrors_used": 0,
        "martyrs_square_used": 0,
        "iron_discipline_used": 0,
        "iron_discipline_battalion": -1,
        "ossuary_keep_used": 0,
        "ashen_recall_used": 0,
        "chirurgeon_uses_left": 0,
        "relentless_push_used": 0,
        "calculated_deployment_used": 0,
        "static_surge_used": 0,
        "eye_of_storm_used": 0,
        "pyre_decree_used": 0,
        "cinder_tithe_used": 0,
        "pending_rations": 0,
    }


@dataclass
class Player:
    name: str
    hand: list[Card]
    deck: list[Card]
    grave: list[Card]
    player_class: Card
    barracks: Barracks
    battalions: list[Battalion]
    battlefields: list[Card]
    xp: int = 0
    resources: dict[str, int] = field(default_factory=_new_resource_state)

    @classmethod
    def create(
        cls,
        name: str,
        deck: list[Card],
        player_class: Card,
        barracks: Card,
        battlefields: list[Card],
        starting_rations: int,
    ) -> "Player":
        random.shuffle(deck)
        player = cls(
            name=name,
            hand=[],
            deck=deck,
            grave=[],
            player_class=player_class,
            barracks=Barracks(card=barracks, units=[]),
            battalions=[Battalion(), Battalion()],
            battlefields=battlefields,
            xp=0,
            resources=_new_resource_state(),
        )
        player.resources["rations"] = min(starting_rations, RESOURCE_CAPS["rations"])
        for _ in range(5):
            player.draw_card()
        return player

    def draw_card(self, count: int = 1) -> int:
        drawn = 0
        for _ in range(count):
            self._recycle_grave_into_deck_if_empty()
            if not self.deck:
                break
            card = self.deck.pop(0)
            card.revealed = False
            card.from_barracks = False
            card.hand_source = "deck"
            card.clear_temporary_state()
            self.hand.append(card)
            drawn += 1
        return drawn

    def _recycle_grave_into_deck_if_empty(self) -> bool:
        if self.deck or not self.grave:
            return False
        for card in self.grave:
            card.revealed = False
            card.from_barracks = False
            card.clear_temporary_state()
        random.shuffle(self.grave)
        self.deck.extend(self.grave)
        self.grave.clear()
        return True

    def class_level(self) -> int:
        level = 0
        if self.xp >= 1:
            level = 1
        if self.xp >= 3:
            level = 3
        if self.xp >= 6:
            level = 6
        return level

    def gain_resource(self, key: str, amount: int) -> int:
        if amount <= 0:
            return 0
        cap = RESOURCE_CAPS.get(key)
        if cap is None:
            self.resources[key] = self.resources.get(key, 0) + amount
            return amount
        before = self.resources.get(key, 0)
        after = min(cap, before + amount)
        self.resources[key] = after
        return after - before

    def has_resources(self, cost: dict[str, int]) -> bool:
        for key, value in cost.items():
            if self.resources.get(key, 0) < value:
                return False
        return True

    def spend_resources(self, cost: dict[str, int]) -> bool:
        if not self.has_resources(cost):
            return False
        for key, value in cost.items():
            self.resources[key] -= value
        return True

    def add_xp(self, amount: int = 1) -> None:
        if amount > 0:
            self.xp += amount
