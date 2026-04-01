from __future__ import annotations

from collections import deque
import random
from typing import Any

from .card_loader import barracks_start_rations, create_card
from .models import Card
from .player import Player
from .premade_decks import build_deck_from_map, build_premade_deck


class Game:
    PHASES = ("replenish", "draw", "preparations", "siege", "field_cleanup")

    def __init__(self, setup_data: dict[str, Any]):
        self.turn = 1
        self.phase = "replenish"
        self.current_player_index = 0
        self.players: list[Player] = []
        self.winner: int | None = None

        self.ready_state = {0: False, 1: False}
        self.battlefield_gap: list[dict[str, Any]] = [
            {"slot": i, "owner": None, "card": None, "controlled_by": None} for i in range(6)
        ]
        self.siege_assignments: dict[int, list[int | str | None]] = {0: [None, None], 1: [None, None]}

        self.pending_grave_pick: dict[str, Any] | None = None
        self.pending_first_deployer_choice: int | None = None
        self.pending_clairvoyance_discard_player: int | None = None
        self.pending_profitable_standoff_draw_player: int | None = None
        self.pending_total_conquest_pick_player: int | None = None
        self.pending_profitable_standoff_draw_phase: list[bool] = [False, False]
        self.profitable_standoff_charges: list[int] = [0, 0]
        self.pending_siege_roll: dict[str, int] | None = None
        self.delayed_ration_payouts: list[list[int]] = [[], []]
        self.pending_siege_report: dict[str, Any] | None = None

        self.logs: deque[str] = deque(maxlen=14)
        self._setup_from_data(setup_data)
        self._log("Game initialized.")

    # --------------------------------------------------------------------- #
    # Setup / state helpers
    # --------------------------------------------------------------------- #
    def _setup_from_data(self, setup_data: dict[str, Any]) -> None:
        players_data = setup_data["players"]
        for idx, pdata in enumerate(players_data):
            deck_field = pdata["deck"]
            if isinstance(deck_field, str):
                deck = build_premade_deck(deck_field, owner_index=idx)
                deck_name = deck_field
            elif isinstance(deck_field, dict):
                deck = build_deck_from_map(deck_field, owner_index=idx)
                deck_name = "custom"
            else:
                raise ValueError("Unsupported deck type in setup data.")

            class_name = pdata["class"]
            barracks_name = pdata["barracks"]
            battlefield_names = pdata["battlefields"]
            player_class = create_card(class_name, owner_index=idx, revealed=True)
            barracks = create_card(barracks_name, owner_index=idx, revealed=True)
            battlefields = [create_card(name, owner_index=idx, revealed=True) for name in battlefield_names]

            player = Player.create(
                name=f"Player {idx + 1}",
                deck=deck,
                player_class=player_class,
                barracks=barracks,
                battlefields=battlefields,
                starting_rations=barracks_start_rations(barracks_name),
            )
            self.players.append(player)
            self._log(f"{player.name} loaded {deck_name} ({len(deck)} cards).")

        for placement in setup_data.get("placements", []):
            slot = int(placement["slot"])
            bfield_raw = placement["battlefield"]
            if isinstance(bfield_raw, dict):
                bfield_name = bfield_raw["name"]
            else:
                bfield_name = str(bfield_raw)
            card = create_card(bfield_name, owner_index=None, revealed=True)
            self.battlefield_gap[slot] = {
                "slot": slot,
                "owner": None,
                "card": card,
                "controlled_by": None,
            }

    def _log(self, message: str) -> None:
        self.logs.appendleft(message)

    def _opponent(self, player_index: int) -> int:
        return 1 - player_index

    def _player(self, player_index: int) -> Player:
        return self.players[player_index]

    def _refund_paid_cost(self, player: Player, card: Card) -> dict[str, int]:
        refunded: dict[str, int] = {}
        for key, value in card.paid_cost.items():
            if value <= 0:
                continue
            gained = player.gain_resource(key, value)
            if gained > 0:
                refunded[key] = gained
        card.paid_cost = {}
        return refunded

    def _all_cards(self, player: Player) -> list[Card]:
        cards: list[Card] = []
        cards.extend(player.hand)
        cards.extend(player.deck)
        cards.extend(player.grave)
        cards.extend(player.barracks.units)
        for battalion in player.battalions:
            cards.extend(battalion.cards)
        cards.append(player.player_class)
        cards.append(player.barracks.card)
        return cards

    def _class_name(self, player_index: int) -> str:
        return self.players[player_index].player_class.name

    def _class_level(self, player_index: int) -> int:
        return self.players[player_index].class_level()

    @staticmethod
    def _normalized_hand_source(card: Card) -> str:
        source = card.hand_source
        if source in ("deck", "grave", "barracks"):
            return source
        return "deck"

    def _hand_card_should_be_revealed_in_battalion(self, card: Card) -> bool:
        return self._normalized_hand_source(card) in ("grave", "barracks")

    def _interaction_blocked(self, player_index: int) -> str | None:
        if self.pending_profitable_standoff_draw_player is not None:
            owner = self.pending_profitable_standoff_draw_player
            if owner == player_index:
                return "Resolve Profitable Standoff top-card order first."
            return "Opponent must resolve Profitable Standoff top-card order first."
        if self.pending_total_conquest_pick_player is not None:
            owner = self.pending_total_conquest_pick_player
            if owner == player_index:
                return "Resolve Total Conquest target selection first."
            return "Opponent must resolve Total Conquest target selection first."
        if self.pending_grave_pick:
            owner = int(self.pending_grave_pick["player"])
            if owner == player_index:
                return "Resolve pending grave selection first."
            return "Opponent must resolve pending grave selection first."
        if self.pending_clairvoyance_discard_player is not None:
            owner = self.pending_clairvoyance_discard_player
            if owner == player_index:
                return "Choose a Clairvoyance discard first."
            return "Opponent must discard for Clairvoyance first."
        return None

    def _legal_active_action(self, player_index: int) -> tuple[bool, str]:
        if self.winner is not None:
            return False, "Game is already over."
        if player_index != self.current_player_index:
            return False, "It is not your action turn."
        blocked = self._interaction_blocked(player_index)
        if blocked:
            return False, blocked
        return True, "ok"

    def _clear_assignments(self) -> None:
        self.siege_assignments = {0: [None, None], 1: [None, None]}

    def _reset_draw_flags(self) -> None:
        for player in self.players:
            player.resources["clairvoyance_used"] = 0
            player.resources["efficient_tithe_used"] = 0

    def _reset_preparations_flags(self) -> None:
        for player in self.players:
            player.resources["war_wrought_used"] = 0
            player.resources["ironheart_used"] = 0
            player.resources["tactical_bluff_used"] = 0
            player.resources["hall_of_mirrors_used"] = 0
            player.resources["martyrs_square_used"] = 0
            player.resources["iron_discipline_used"] = 0
            player.resources["iron_discipline_battalion"] = -1
            player.resources["ossuary_keep_used"] = 0
            player.resources["ashen_recall_used"] = 0
            player.resources["chirurgeon_uses_left"] = sum(
                1 for unit in player.barracks.units if unit.name == "Alchemical Chirurgeon"
            )

    def _reset_siege_flags(self) -> None:
        for player in self.players:
            player.resources["relentless_push_used"] = 0
            player.resources["calculated_deployment_used"] = 0
            player.resources["static_surge_used"] = 0
            player.resources["eye_of_storm_used"] = 0
            player.resources["pyre_decree_used"] = 0
            player.resources["cinder_tithe_used"] = 0
            for card in self._all_cards(player):
                card.shield_used_this_siege = False
                card.temp_line_override = None

    # --------------------------------------------------------------------- #
    # Phase progression
    # --------------------------------------------------------------------- #
    def advance_phase(self) -> tuple[bool, str]:
        if self.winner is not None:
            return False, "Game is already over."

        if self.phase == "replenish":
            self._do_replenish_phase()
            self._start_draw_phase()
            return True, "Replenish complete. Draw phase started."

        if self.phase == "draw":
            return False, "Draw requires both players to Ready."

        if self.phase == "preparations":
            return False, "Preparations requires both players to Ready."

        if self.phase == "siege":
            if self._all_nonempty_battalions_deployed():
                return self._resolve_siege_and_cleanup()
            return False, "Siege deployment is still in progress."

        if self.phase == "field_cleanup":
            self._field_cleanup()
            self.turn += 1
            self.phase = "replenish"
            self.current_player_index = 0
            return True, "Field cleanup resolved. Next turn replenish."

        return False, "Unknown phase state."

    def _start_draw_phase(self) -> None:
        self.phase = "draw"
        self.current_player_index = 0
        self.ready_state = {0: False, 1: False}
        self.pending_clairvoyance_discard_player = None
        self.pending_profitable_standoff_draw_player = None
        self.pending_total_conquest_pick_player = None
        self.pending_profitable_standoff_draw_phase = [False, False]
        self._reset_draw_flags()
        for idx, player in enumerate(self.players):
            player._recycle_grave_into_deck_if_empty()
            if self.profitable_standoff_charges[idx] > 0:
                self.profitable_standoff_charges[idx] -= 1
                if len(player.deck) >= 2:
                    self.pending_profitable_standoff_draw_phase[idx] = True
                    self._log(
                        f"{player.name} triggered Profitable Standoff and must order the top 2 cards before drawing."
                    )
                else:
                    drawn = player.draw_card(1)
                    self._log(f"{player.name} draws {drawn} card(s).")
                    if drawn == 0:
                        self._log(f"{player.name} has no cards left to draw.")
                    self._log(
                        f"{player.name} had fewer than 2 cards for Profitable Standoff and drew normally."
                    )
            else:
                drawn = player.draw_card(1)
                self._log(f"{player.name} draws {drawn} card(s).")
                if drawn == 0:
                    self._log(f"{player.name} has no cards left to draw.")
            player_index = idx + 1
            self._log(f"Draw step reset flags for P{player_index}.")
        self._activate_pending_profitable_standoff_for_active_player()

    def _start_preparations_phase(self) -> None:
        self.phase = "preparations"
        self.current_player_index = 0
        self.ready_state = {0: False, 1: False}
        self.pending_profitable_standoff_draw_player = None
        self.pending_total_conquest_pick_player = None
        self.pending_profitable_standoff_draw_phase = [False, False]
        self._reset_preparations_flags()
        for pidx, player in enumerate(self.players):
            if not self._player_controls_battlefield(pidx, "Hall of Mirrors"):
                continue
            drawn = player.draw_card(1)
            gained = player.gain_resource("magium", 1)
            player.resources["hall_of_mirrors_used"] = 1
            self._log(
                f"{player.name} auto-resolved Hall of Mirrors (draw {drawn}, gain +{gained} magium)."
            )
        self._log("Preparations phase started.")

    def _start_siege_phase(self) -> None:
        self.phase = "siege"
        self._clear_assignments()
        self.pending_grave_pick = None
        self.pending_clairvoyance_discard_player = None
        self.pending_total_conquest_pick_player = None
        self.pending_siege_report = None
        self._reset_siege_flags()
        p1_roll, p2_roll, winner = self._roll_deployment_winner()
        loser = self._opponent(winner)
        self.pending_first_deployer_choice = winner
        self.pending_siege_roll = {"p1": p1_roll, "p2": p2_roll, "winner": winner, "loser": loser}
        self.current_player_index = winner
        self._log(
            f"Siege start roll: P1={p1_roll}, P2={p2_roll}. "
            f"P{winner + 1} chooses first deployer."
        )

    def _do_replenish_phase(self) -> None:
        for pidx, player in enumerate(self.players):
            # 1) Delayed supply cache payouts.
            next_markers: list[int] = []
            for turns_left in self.delayed_ration_payouts[pidx]:
                if turns_left <= 1:
                    gained = player.gain_resource("rations", 2)
                    self._log(f"{player.name} Supply Cache pays out +{gained} rations.")
                else:
                    next_markers.append(turns_left - 1)
            self.delayed_ration_payouts[pidx] = next_markers

            # 2) Base +3 rations.
            gained = player.gain_resource("rations", 3)
            self._log(f"{player.name} gains +{gained} rations in replenish.")

            # 3) Pending rations.
            pending = player.resources.get("pending_rations", 0)
            if pending > 0:
                gained = player.gain_resource("rations", pending)
                self._log(f"{player.name} receives +{gained} pending ration(s).")
                player.resources["pending_rations"] = 0

            # 4) Barracks bonuses.
            if player.barracks.card.name == "High Command Spire":
                gained = player.gain_resource("rations", 1)
                self._log(f"{player.name} High Command Spire grants +{gained} ration.")
            if player.barracks.card.name == "Quartermaster's Bastion" and player.resources["rations"] <= 2:
                gained = player.gain_resource("rations", 1)
                self._log(f"{player.name} Quartermaster's Bastion grants +{gained} ration.")

            # 5) Battlefield controlled bonuses.
            for slot in self.battlefield_gap:
                if slot["controlled_by"] != pidx or slot["card"] is None:
                    continue
                bname = slot["card"].name
                if bname == "Ironheart Forges":
                    player.gain_resource("ore", 1)
                elif bname == "Arcane Nexus":
                    player.gain_resource("magium", 1)
                elif bname == "Grand Cathedral":
                    player.gain_resource("faith", 1)

            self._log(
                f"{player.name} resources: r={player.resources['rations']} "
                f"o={player.resources['ore']} m={player.resources['materia']} "
                f"mg={player.resources['magium']} f={player.resources['faith']} "
                f"s={player.resources['sacrifice']}."
            )

        self.current_player_index = 0
        self.ready_state = {0: False, 1: False}

    def ready_current_player(self, player_index: int) -> tuple[bool, str]:
        if self.phase not in ("draw", "preparations"):
            return False, "Ready is only valid in draw or preparations."
        if player_index != self.current_player_index:
            return False, "It is not this player's ready turn."
        blocked = self._interaction_blocked(player_index)
        if blocked:
            return False, blocked

        self.ready_state[player_index] = True
        other = self._opponent(player_index)
        if not self.ready_state[other]:
            self.current_player_index = other
            self._activate_pending_profitable_standoff_for_active_player()
            return True, f"{self.players[player_index].name} is ready. Waiting for opponent."

        if self.phase == "draw":
            self._start_preparations_phase()
            return True, "Both players ready. Preparations phase started."

        self._start_siege_phase()
        return True, "Both players ready. Siege phase started."

    def ready_draw(self, player_index: int) -> tuple[bool, str]:
        return self.ready_current_player(player_index)

    def ready_preparations(self, player_index: int) -> tuple[bool, str]:
        return self.ready_current_player(player_index)

    def _activate_pending_profitable_standoff_for_active_player(self) -> None:
        if self.phase != "draw":
            self.pending_profitable_standoff_draw_player = None
            return
        owner = self.current_player_index
        if not self.pending_profitable_standoff_draw_phase[owner]:
            self.pending_profitable_standoff_draw_player = None
            return
        player = self.players[owner]
        player._recycle_grave_into_deck_if_empty()
        if len(player.deck) >= 2:
            self.pending_profitable_standoff_draw_player = owner
            return
        # Fallback safety in case deck changed before the choice resolved.
        self.pending_profitable_standoff_draw_phase[owner] = False
        self.pending_profitable_standoff_draw_player = None
        drawn = player.draw_card(1)
        self._log(
            f"{player.name} no longer has 2 cards for Profitable Standoff and draws {drawn} card(s) normally."
        )

    def choose_profitable_standoff_card(self, player_index: int, top_index: int) -> tuple[bool, str]:
        if self.phase != "draw":
            return False, "Profitable Standoff choice is only valid in draw."
        if self.pending_profitable_standoff_draw_player is None:
            return False, "No pending Profitable Standoff choice."
        if player_index != self.pending_profitable_standoff_draw_player:
            return False, "This player cannot resolve Profitable Standoff choice."
        if player_index != self.current_player_index:
            return False, "It is not this player's action turn."
        if top_index not in (0, 1):
            return False, "Choice must be top card 0 or 1."

        player = self.players[player_index]
        player._recycle_grave_into_deck_if_empty()
        if len(player.deck) < 2:
            return False, "Need at least 2 cards in deck for Profitable Standoff."

        if top_index == 1:
            player.deck[0], player.deck[1] = player.deck[1], player.deck[0]

        drawn = player.deck.pop(0)
        drawn.revealed = False
        drawn.from_barracks = False
        drawn.hand_source = "deck"
        drawn.clear_temporary_state()
        player.hand.append(drawn)
        self.pending_profitable_standoff_draw_phase[player_index] = False
        self.pending_profitable_standoff_draw_player = None
        self._log(
            f"{player.name} ordered the top 2 cards via Profitable Standoff and drew {drawn.name}."
        )
        return True, "Profitable Standoff choice resolved."

    # --------------------------------------------------------------------- #
    # Core setup checks and lookups
    # --------------------------------------------------------------------- #
    def _player_controls_battlefield(self, player_index: int, battlefield_name: str) -> bool:
        for slot in self.battlefield_gap:
            if slot["controlled_by"] == player_index and slot["card"] and slot["card"].name == battlefield_name:
                return True
        return False

    def _player_controls_any_battlefield_substring(self, player_index: int, token: str) -> bool:
        for slot in self.battlefield_gap:
            if slot["controlled_by"] == player_index and slot["card"] and token in slot["card"].name:
                return True
        return False

    def _player_controls_column(self, player_index: int, col: int) -> bool:
        for slot in self.battlefield_gap:
            if slot["slot"] % 3 == col and slot["controlled_by"] == player_index:
                return True
        return False

    def _player_controls_all_battlefields(self, player_index: int) -> bool:
        occupied = [slot for slot in self.battlefield_gap if slot["card"] is not None]
        if not occupied:
            return False
        return all(slot["controlled_by"] == player_index for slot in occupied)

    def _battlefield_name_at(self, slot_index: int) -> str | None:
        slot = self.battlefield_gap[slot_index]
        return slot["card"].name if slot["card"] else None

    # --------------------------------------------------------------------- #
    # Preparations actions
    # --------------------------------------------------------------------- #
    def assign_hand_card_to_battalion(
        self, player_index: int, hand_index: int, battalion_index: int
    ) -> tuple[bool, str]:
        if self.phase != "preparations":
            return False, "Hand assignment is only valid in preparations."
        ok, msg = self._legal_active_action(player_index)
        if not ok:
            return False, msg
        player = self.players[player_index]
        if battalion_index not in (0, 1):
            return False, "Battalion index must be 0 or 1."
        if hand_index < 0 or hand_index >= len(player.hand):
            return False, "Invalid hand index."
        battalion = player.battalions[battalion_index]
        card = player.hand[hand_index]
        if card.card_type != "Unit":
            return False, "Only Unit cards can be assigned to battalions."
        if not battalion.has_room(card):
            return False, "No room in this battalion for that unit's line."

        cost = dict(card.cost)
        ration_discount = 0

        if player.barracks.card.name == "War-Wrought Citadel" and player.resources["war_wrought_used"] == 0:
            ration_discount += 1
            player.resources["war_wrought_used"] = 1

        if (
            self._player_controls_any_battlefield_substring(player_index, "Martyr")
            and player.resources["martyrs_square_used"] == 0
        ):
            ration_discount += 1
            player.resources["martyrs_square_used"] = 1

        if (
            player.resources["iron_discipline_used"] == 1
            and player.resources["iron_discipline_battalion"] == battalion_index
        ):
            ration_discount += 1

        if ration_discount > 0 and "rations" in cost:
            cost["rations"] = max(0, cost["rations"] - ration_discount)

        if not player.has_resources(cost):
            return False, "Not enough resources to assign this card."
        player.spend_resources(cost)
        card.paid_cost = cost

        moved = player.hand.pop(hand_index)
        moved.revealed = self._hand_card_should_be_revealed_in_battalion(moved)
        moved.from_barracks = False
        battalion.cards.append(moved)

        if moved.name == "Supply Runner":
            player.resources["pending_rations"] += 1
            self._log(f"{player.name} Supply Runner queued +1 ration.")

        if moved.name == "Forged Dreadnought" and player.resources.get("ore", 0) >= 1:
            player.resources["ore"] -= 1
            moved.temp_might_bonus += 2
            moved.temp_will_bonus -= 2
            self._log(f"{player.name} Forged Dreadnought triggers Reckless Swing.")

        self._log(
            f"{player.name} assigned {moved.name} to Battalion {battalion_index + 1} "
            f"(cost paid: {cost})."
        )
        return True, "Card assigned to battalion."

    def remove_battalion_card_to_hand(
        self, player_index: int, battalion_index: int, card_index: int = 0
    ) -> tuple[bool, str]:
        if self.phase != "preparations":
            return False, "This action is only valid in preparations."
        ok, msg = self._legal_active_action(player_index)
        if not ok:
            return False, msg
        player = self.players[player_index]
        if battalion_index not in (0, 1):
            return False, "Battalion index must be 0 or 1."
        battalion = player.battalions[battalion_index]
        if card_index < 0 or card_index >= len(battalion.cards):
            return False, "Invalid battalion card index."
        card = battalion.cards.pop(card_index)
        if card.from_barracks:
            card.revealed = True
            card.paid_cost = {}
            player.barracks.units.append(card)
            self._log(f"{player.name} returned {card.name} from Battalion {battalion_index + 1} to barracks.")
            return True, "Card returned to barracks."
        refunded = self._refund_paid_cost(player, card)
        card.revealed = False
        if card.hand_source not in ("deck", "grave", "barracks"):
            card.hand_source = "deck"
        player.hand.append(card)
        refund_suffix = f" (refund: {refunded})" if refunded else ""
        self._log(
            f"{player.name} returned {card.name} from Battalion {battalion_index + 1} to hand{refund_suffix}."
        )
        if refunded:
            return True, f"Card returned to hand. Refunded {refunded}."
        return True, "Card returned to hand."

    def assign_barracks_unit_to_battalion(
        self, player_index: int, barracks_unit_index: int, battalion_index: int
    ) -> tuple[bool, str]:
        if self.phase != "preparations":
            return False, "This action is only valid in preparations."
        ok, msg = self._legal_active_action(player_index)
        if not ok:
            return False, msg
        player = self.players[player_index]
        if battalion_index not in (0, 1):
            return False, "Battalion index must be 0 or 1."
        if barracks_unit_index < 0 or barracks_unit_index >= len(player.barracks.units):
            return False, "Invalid barracks unit index."
        battalion = player.battalions[battalion_index]
        card = player.barracks.units[barracks_unit_index]
        if not battalion.has_room(card):
            return False, "No room in this battalion for that unit's line."
        card = player.barracks.units.pop(barracks_unit_index)
        card.from_barracks = True
        card.revealed = True
        battalion.cards.append(card)

        if card.name == "Supply Runner":
            player.resources["pending_rations"] += 1
            self._log(f"{player.name} Supply Runner queued +1 ration.")

        self._log(f"{player.name} moved barracks unit {card.name} to Battalion {battalion_index + 1}.")
        return True, "Barracks unit assigned to battalion."

    # --------------------------------------------------------------------- #
    # Draw / preparations abilities
    # --------------------------------------------------------------------- #
    def trade_rations_for_special(self, player_index: int, special_resource: str) -> tuple[bool, str]:
        if self.phase not in ("draw", "preparations", "siege"):
            return False, "Trading resources is not valid in this phase."
        ok, msg = self._legal_active_action(player_index)
        if not ok:
            return False, msg
        if special_resource not in ("ore", "materia", "magium", "faith", "sacrifice"):
            return False, "Special resource must be ore/materia/magium/faith/sacrifice."
        player = self.players[player_index]
        trade_cost = 3
        if player.resources["rations"] < trade_cost:
            return False, f"Not enough rations (need {trade_cost})."
        if player.resources[special_resource] >= 5:
            return False, f"{special_resource} is already at cap."
        player.resources["rations"] -= trade_cost
        gained = player.gain_resource(special_resource, 1)
        self._log(f"{player.name} traded {trade_cost} rations for +{gained} {special_resource}.")
        return True, "Trade successful."

    def use_efficient_tithe(self, player_index: int, special_resource: str) -> tuple[bool, str]:
        if self.phase != "draw":
            return False, "Efficient Tithe can only be used during draw."
        ok, msg = self._legal_active_action(player_index)
        if not ok:
            return False, msg
        player = self.players[player_index]
        if self._class_name(player_index) != "Arch-Hierarch" or self._class_level(player_index) < 1:
            return False, "Arch-Hierarch level 1 is required."
        if player.resources["efficient_tithe_used"] == 1:
            return False, "Efficient Tithe already used this draw."
        if special_resource not in ("ore", "materia", "magium", "faith", "sacrifice"):
            return False, "Choose a valid special resource."
        if player.resources["rations"] < 2:
            return False, "Not enough rations."
        if player.resources[special_resource] >= 5:
            return False, f"{special_resource} is already at cap."
        player.resources["rations"] -= 2
        player.gain_resource(special_resource, 1)
        player.resources["efficient_tithe_used"] = 1
        self._log(f"{player.name} used Efficient Tithe (+1 {special_resource}).")
        return True, "Efficient Tithe resolved."

    def use_clairvoyance(self, player_index: int) -> tuple[bool, str]:
        if self.phase != "draw":
            return False, "Clairvoyance can only be used during draw."
        ok, msg = self._legal_active_action(player_index)
        if not ok:
            return False, msg
        player = self.players[player_index]
        if player.resources["clairvoyance_used"] == 1:
            return False, "Arcane Nexus ability already used this draw."
        if not self._player_controls_battlefield(player_index, "Arcane Nexus"):
            return False, "You do not control Arcane Nexus."
        if player.resources["magium"] < 1:
            return False, "Not enough magium."
        player.resources["magium"] -= 1
        drawn = player.draw_card(1)
        if drawn == 0:
            return False, "No cards to draw for Clairvoyance."
        player.resources["clairvoyance_used"] = 1
        self.pending_clairvoyance_discard_player = player_index
        self._log(f"{player.name} used Arcane Nexus Clairvoyance and must discard one card.")
        return True, "Draw 1 completed. Choose one hand card to discard."

    def choose_clairvoyance_discard(self, player_index: int, hand_index: int) -> tuple[bool, str]:
        if self.pending_clairvoyance_discard_player is None:
            return False, "No pending Clairvoyance discard."
        if player_index != self.pending_clairvoyance_discard_player:
            return False, "This player cannot resolve Clairvoyance discard."
        player = self.players[player_index]
        if hand_index < 0 or hand_index >= len(player.hand):
            return False, "Invalid hand index."
        card = player.hand.pop(hand_index)
        player.grave.append(card)
        self.pending_clairvoyance_discard_player = None
        self._log(f"{player.name} discarded {card.name} for Clairvoyance.")
        return True, "Clairvoyance discard resolved."

    def use_hall_of_mirrors(self, player_index: int) -> tuple[bool, str]:
        if self.phase != "preparations":
            return False, "Hall of Mirrors can only be used in preparations."
        ok, msg = self._legal_active_action(player_index)
        if not ok:
            return False, msg
        player = self.players[player_index]
        if player.resources["hall_of_mirrors_used"] == 1:
            return False, "Hall of Mirrors already used this preparations."
        if not self._player_controls_battlefield(player_index, "Hall of Mirrors"):
            return False, "You do not control Hall of Mirrors."
        player.draw_card(1)
        player.gain_resource("magium", 1)
        player.resources["hall_of_mirrors_used"] = 1
        self._log(f"{player.name} used Hall of Mirrors (draw 1, gain 1 magium).")
        return True, "Hall of Mirrors resolved."

    def use_ossuary_keep(self, player_index: int) -> tuple[bool, str]:
        if self.phase != "preparations":
            return False, "Ossuary Keep can only be used in preparations."
        ok, msg = self._legal_active_action(player_index)
        if not ok:
            return False, msg
        player = self.players[player_index]
        if player.barracks.card.name != "Ossuary Keep":
            return False, "Your barracks is not Ossuary Keep."
        if player.resources["ossuary_keep_used"] == 1:
            return False, "Ossuary Keep already used this preparations."
        if not player.grave:
            return False, "Your grave is empty."
        return self._start_grave_pick(
            player_index,
            source="Ossuary Keep",
            destination="hand",
            reveal=True,
            required_cost={"faith": 1},
            flag_key="ossuary_keep_used",
        )

    def start_ashen_recall(self, player_index: int) -> tuple[bool, str]:
        if self.phase != "preparations":
            return False, "Ashen Recall can only be used in preparations."
        ok, msg = self._legal_active_action(player_index)
        if not ok:
            return False, msg
        if self._class_name(player_index) != "Ash Chancellor" or self._class_level(player_index) < 3:
            return False, "Ash Chancellor level 3 is required."
        player = self.players[player_index]
        if player.resources["ashen_recall_used"] == 1:
            return False, "Ashen Recall already used this preparations."
        if not player.grave:
            return False, "Your grave is empty."
        return self._start_grave_pick(
            player_index,
            source="Ashen Recall",
            destination="hand",
            reveal=True,
            required_cost={"sacrifice": 1},
            flag_key="ashen_recall_used",
        )

    def start_chirurgeon_recovery(self, player_index: int) -> tuple[bool, str]:
        if self.phase != "preparations":
            return False, "Chirurgeon recovery is only valid in preparations."
        ok, msg = self._legal_active_action(player_index)
        if not ok:
            return False, msg
        player = self.players[player_index]
        if player.resources["chirurgeon_uses_left"] <= 0:
            return False, "No Chirurgeon recovery uses left."
        if not player.grave:
            return False, "Your grave is empty."
        return self._start_grave_pick(
            player_index,
            source="Alchemical Chirurgeon",
            destination="hand",
            reveal=True,
            required_cost={"materia": 1},
            consume_counter="chirurgeon_uses_left",
        )

    def start_miracle_of_faith(self, player_index: int, battalion_index: int) -> tuple[bool, str]:
        if self.phase != "preparations":
            return False, "Miracle of Faith can only be used in preparations."
        ok, msg = self._legal_active_action(player_index)
        if not ok:
            return False, msg
        if self._class_name(player_index) != "Arch-Hierarch" or self._class_level(player_index) < 6:
            return False, "Arch-Hierarch level 6 is required."
        player = self.players[player_index]
        if player.resources["miracle_of_faith_used"] == 1:
            return False, "Miracle of Faith is once per game and already used."
        if battalion_index not in (0, 1):
            return False, "Battalion index must be 0 or 1."
        if not player.battalions[battalion_index].has_room():
            return False, "Selected battalion is full."
        if not player.grave:
            return False, "Your grave is empty."
        return self._start_grave_pick(
            player_index,
            source="Miracle of Faith",
            destination="battalion",
            battalion_index=battalion_index,
            reveal=True,
            required_cost={"sacrifice": 1, "faith": 1},
            flag_key="miracle_of_faith_used",
        )

    def use_tactical_bluff(self, player_index: int) -> tuple[bool, str]:
        if self.phase != "preparations":
            return False, "Tactical Bluff can only be used in preparations."
        ok, msg = self._legal_active_action(player_index)
        if not ok:
            return False, msg
        if self._class_name(player_index) != "Grand Strategist" or self._class_level(player_index) < 1:
            return False, "Grand Strategist level 1 is required."
        player = self.players[player_index]
        if player.resources["tactical_bluff_used"] == 1:
            return False, "Tactical Bluff already used this preparations."
        if not player.hand:
            return False, "Hand is empty."
        first_hand = player.hand[0]
        hidden_target: tuple[int, int, Card] | None = None
        for bidx, battalion in enumerate(player.battalions):
            for cidx, card in enumerate(battalion.cards):
                if not card.revealed:
                    hidden_target = (bidx, cidx, card)
                    break
            if hidden_target is not None:
                break
        if hidden_target is None:
            return False, "No eligible hidden battalion card for Tactical Bluff."

        bidx, cidx, hidden_card = hidden_target
        refunded = self._refund_paid_cost(player, hidden_card)
        player.hand[0] = hidden_card
        hidden_card.revealed = False
        if hidden_card.from_barracks:
            hidden_card.hand_source = "barracks"
        elif hidden_card.hand_source not in ("deck", "grave", "barracks"):
            hidden_card.hand_source = "deck"
        player.battalions[bidx].cards[cidx] = first_hand
        first_hand.revealed = self._hand_card_should_be_revealed_in_battalion(first_hand)
        first_hand.from_barracks = False
        first_hand.paid_cost = {}
        player.resources["tactical_bluff_used"] = 1
        self._log(
            f"{player.name} used Tactical Bluff (first hand card swapped with first hidden battalion card)."
        )
        if refunded:
            self._log(f"{player.name} was refunded {refunded} for returning {hidden_card.name} to hand.")
        return True, "Tactical Bluff resolved."

    def use_ironheart_forges_boost(
        self, player_index: int, battalion_index: int, card_index: int = 0
    ) -> tuple[bool, str]:
        if self.phase != "preparations":
            return False, "Ironheart boost can only be used in preparations."
        ok, msg = self._legal_active_action(player_index)
        if not ok:
            return False, msg
        player = self.players[player_index]
        if player.resources["ironheart_used"] == 1:
            return False, "Ironheart Forges boost already used this preparations."
        if not self._player_controls_battlefield(player_index, "Ironheart Forges"):
            return False, "You do not control Ironheart Forges."
        if player.resources["ore"] < 1:
            return False, "Not enough ore."
        if battalion_index not in (0, 1):
            return False, "Battalion index must be 0 or 1."
        battalion = player.battalions[battalion_index]
        if card_index < 0 or card_index >= len(battalion.cards):
            return False, "Invalid battalion card index."
        card = battalion.cards[card_index]
        player.resources["ore"] -= 1
        card.temp_might_bonus += 1
        player.resources["ironheart_used"] = 1
        self._log(f"{player.name} used Ironheart Forges boost on {card.name}.")
        return True, "Ironheart boost resolved."

    # --------------------------------------------------------------------- #
    # Grave selection pipeline
    # --------------------------------------------------------------------- #
    def _start_grave_pick(
        self,
        player_index: int,
        source: str,
        destination: str,
        reveal: bool,
        required_cost: dict[str, int] | None = None,
        consume_counter: str | None = None,
        flag_key: str | None = None,
        battalion_index: int | None = None,
    ) -> tuple[bool, str]:
        if self.pending_grave_pick is not None:
            return False, "A grave selection is already pending."
        self.pending_grave_pick = {
            "player": player_index,
            "source": source,
            "destination": destination,
            "reveal": reveal,
            "required_cost": dict(required_cost or {}),
            "consume_counter": consume_counter,
            "flag_key": flag_key,
            "battalion_index": battalion_index,
        }
        self._log(f"{self.players[player_index].name} started grave selection ({source}).")
        return True, "Choose a grave card."

    def choose_grave_card(self, player_index: int, grave_index: int) -> tuple[bool, str]:
        if self.pending_grave_pick is None:
            return False, "No pending grave selection."
        pending = self.pending_grave_pick
        owner = int(pending["player"])
        if player_index != owner:
            return False, "This player cannot resolve the pending grave selection."
        player = self.players[player_index]
        if grave_index < 0 or grave_index >= len(player.grave):
            return False, "Invalid grave index."
        card = player.grave[grave_index]
        if card.card_type != "Unit":
            return False, "Only Unit cards can be retrieved."

        required_cost = dict(pending.get("required_cost", {}))
        if not player.has_resources(required_cost):
            return False, "Not enough resources for this grave action."
        consume_counter = pending.get("consume_counter")
        if consume_counter:
            if player.resources.get(consume_counter, 0) <= 0:
                return False, "No uses remaining for this action."

        destination = pending["destination"]
        battalion_index = pending.get("battalion_index")
        if destination == "battalion":
            if battalion_index not in (0, 1):
                return False, "Pending battalion destination is invalid."
            selected_card = player.grave[grave_index]
            if not player.battalions[battalion_index].has_room(selected_card):
                return False, "Destination battalion has no room for that unit's line."

        player.spend_resources(required_cost)
        if consume_counter:
            player.resources[consume_counter] -= 1

        moved = player.grave.pop(grave_index)
        moved.hand_source = "grave"
        moved.revealed = bool(pending.get("reveal", True))
        moved.from_barracks = False
        moved.clear_temporary_state()

        if destination == "hand":
            player.hand.append(moved)
        else:
            player.battalions[battalion_index].cards.append(moved)

        flag_key = pending.get("flag_key")
        if flag_key:
            player.resources[flag_key] = 1

        source = pending.get("source", "grave effect")
        self.pending_grave_pick = None
        self._log(f"{player.name} resolved grave pick via {source}: {moved.name}.")
        return True, "Grave selection resolved."

    # --------------------------------------------------------------------- #
    # Non-unit card play
    # --------------------------------------------------------------------- #
    def play_non_unit_card(
        self,
        player_index: int,
        hand_index: int,
        battalion_index: int | None = None,
        target_player_index: int | None = None,
        target_card_index: int | None = None,
    ) -> tuple[bool, str]:
        if self.phase != "preparations":
            return False, "Non-unit cards can only be played in preparations."
        ok, msg = self._legal_active_action(player_index)
        if not ok:
            return False, msg
        player = self.players[player_index]
        if hand_index < 0 or hand_index >= len(player.hand):
            return False, "Invalid hand index."

        card = player.hand[hand_index]
        if card.card_type == "Unit":
            return False, "Selected card is a unit, not a non-unit."

        full_cost = dict(card.cost)
        if not player.has_resources(full_cost):
            return False, "Not enough resources to play this card."

        # Validate + apply effect (without moving card yet).
        effect_ok, effect_msg = self._apply_non_unit_effect(
            player_index=player_index,
            card=card,
            battalion_index=battalion_index,
            target_player_index=target_player_index,
            target_card_index=target_card_index,
        )
        if not effect_ok:
            return False, effect_msg

        player.spend_resources(full_cost)
        if card not in player.hand:
            return False, "Selected non-unit is no longer in hand."
        played = player.hand.pop(player.hand.index(card))
        played.paid_cost = full_cost
        player.grave.append(played)

        # Arch-Hierarch Divine Insight now scores on successful non-unit
        # activations in preparations (and still supports siege if enabled later).
        self._on_non_unit_activated(player_index)
        self._log(f"{player.name} played {played.name}.")
        return True, "Non-unit card played."

    def _apply_non_unit_effect(
        self,
        player_index: int,
        card: Card,
        battalion_index: int | None = None,
        target_player_index: int | None = None,
        target_card_index: int | None = None,
    ) -> tuple[bool, str]:
        player = self.players[player_index]
        enemy = self.players[self._opponent(player_index)]

        if card.name == "Aegis Pulse":
            if self.phase != "preparations":
                return False, "Aegis Pulse is preparations only."
            target = None
            if target_player_index is not None and target_player_index != player_index:
                return False, "Aegis Pulse must target one of your units."
            if battalion_index in (0, 1):
                battalion = player.battalions[battalion_index]
                if target_card_index is not None:
                    if target_card_index < 0 or target_card_index >= len(battalion.cards):
                        return False, "Invalid Aegis Pulse target card index."
                    target = battalion.cards[target_card_index]
                elif battalion.cards:
                    target = battalion.cards[0]
            if target is None:
                for battalion in player.battalions:
                    if battalion.cards:
                        target = battalion.cards[0]
                        break
            if target is None:
                return False, "No valid battalion unit target."
            target.temp_will_bonus += 2
            return True, "Aegis Pulse applied."

        if card.name == "Entrench":
            if self.phase != "preparations":
                return False, "Entrench is preparations only."
            if battalion_index not in (0, 1):
                return False, "Entrench requires battalion 0 or 1."
            battalion = player.battalions[battalion_index]
            if not battalion.cards:
                return False, "Selected battalion is empty."
            for unit in battalion.cards[:2]:
                unit.temp_will_bonus += 1
            return True, "Entrench applied."

        if card.name == "Iron Discipline":
            if self.phase != "preparations":
                return False, "Iron Discipline is preparations only."
            if battalion_index not in (0, 1):
                return False, "Iron Discipline requires battalion 0 or 1."
            player.resources["iron_discipline_used"] = 1
            player.resources["iron_discipline_battalion"] = battalion_index
            return True, "Iron Discipline active."

        if card.name == "Mass Benediction":
            if self.phase != "preparations":
                return False, "Mass Benediction is preparations only."
            changed = 0
            for battalion in player.battalions:
                for unit in battalion.cards:
                    if unit.effective_line() == "Back":
                        unit.temp_will_bonus += 1
                        changed += 1
            if changed == 0:
                return False, "No back-line units to buff."
            return True, "Mass Benediction applied."

        if card.name == "Reserve Rotation":
            if self.phase != "preparations":
                return False, "Reserve Rotation is preparations only."
            if battalion_index not in (0, 1):
                return False, "Reserve Rotation requires battalion 0 or 1."
            battalion = player.battalions[battalion_index]
            if not battalion.cards:
                return False, "Selected battalion has no cards."
            replacement_idx = None
            for idx, hand_card in enumerate(player.hand):
                if hand_card is card:
                    continue
                if hand_card.card_type == "Unit":
                    replacement_idx = idx
                    break
            if replacement_idx is None:
                return False, "Need another unit in hand for Reserve Rotation."
            removed = battalion.cards[0]
            replacement_card = player.hand[replacement_idx]
            if not battalion.has_room(replacement_card, excluding=removed):
                return False, "No room in this battalion for that replacement unit's line."

            removed = battalion.cards.pop(0)
            removed.revealed = False
            refunded = self._refund_paid_cost(player, removed)
            if removed.from_barracks:
                removed.hand_source = "barracks"
            elif removed.hand_source not in ("deck", "grave", "barracks"):
                removed.hand_source = "deck"
            player.hand.append(removed)

            replacement_card = player.hand[replacement_idx]
            replacement_card.revealed = self._hand_card_should_be_revealed_in_battalion(replacement_card)
            replacement_card.from_barracks = False
            replacement_card.paid_cost = {}
            battalion.cards.append(replacement_card)
            player.hand.pop(replacement_idx)
            if refunded:
                self._log(f"{player.name} was refunded {refunded} for returning {removed.name} to hand.")
            return True, "Reserve Rotation resolved."

        if card.name == "Rite of Ash":
            if self.phase != "preparations":
                return False, "Rite of Ash is preparations only."
            if not player.grave:
                return False, "Your grave is empty."
            return self._start_grave_pick(
                player_index=player_index,
                source="Rite of Ash",
                destination="hand",
                reveal=True,
            )

        if card.name == "Sabotage Lines":
            if self.phase != "preparations":
                return False, "Sabotage Lines is preparations only."
            defender_index = self._opponent(player_index)
            if target_player_index is not None and target_player_index != defender_index:
                return False, "Sabotage Lines must target an enemy unit."
            if battalion_index in (0, 1):
                battalion = enemy.battalions[battalion_index]
                if target_card_index is not None:
                    if target_card_index < 0 or target_card_index >= len(battalion.cards):
                        return False, "Invalid Sabotage Lines target card index."
                    target = battalion.cards[target_card_index]
                    if target.effective_line() != "Front":
                        return False, "Sabotage Lines requires an enemy front-line unit."
                    target.temp_might_bonus -= 1
                    return True, "Sabotage Lines applied."
                for unit in battalion.cards:
                    if unit.effective_line() == "Front":
                        unit.temp_might_bonus -= 1
                        return True, "Sabotage Lines applied."
            for battalion in enemy.battalions:
                for unit in battalion.cards:
                    if unit.effective_line() == "Front":
                        unit.temp_might_bonus -= 1
                        return True, "Sabotage Lines applied."
            return False, "No enemy front-line unit found."

        if card.name == "Supply Cache":
            if self.phase != "preparations":
                return False, "Supply Cache is preparations only."
            self.delayed_ration_payouts[player_index].append(2)
            return True, "Supply Cache delayed payout added."

        return False, "Unknown non-unit card effect."

    # --------------------------------------------------------------------- #
    # Siege deployment and class siege abilities
    # --------------------------------------------------------------------- #
    def _roll_deployment_winner(self) -> tuple[int, int, int]:
        while True:
            p1_roll = random.randint(1, 6)
            p2_roll = random.randint(1, 6)
            if p1_roll != p2_roll:
                return p1_roll, p2_roll, 0 if p1_roll > p2_roll else 1

    def choose_first_deployer(self, chooser_index: int, chosen_player_index: int) -> tuple[bool, str]:
        if self.phase != "siege":
            return False, "First deployer is only chosen in siege."
        if self.pending_first_deployer_choice is None:
            return False, "No first deployer choice is pending."
        if chooser_index != self.pending_first_deployer_choice:
            return False, "Only the roll winner may choose first deployer."
        if chosen_player_index not in (0, 1):
            return False, "Chosen player must be 0 or 1."
        self.current_player_index = chosen_player_index
        self.pending_first_deployer_choice = None
        self._log(f"{self.players[chooser_index].name} chose P{chosen_player_index + 1} as first deployer.")
        return True, "First deployer chosen."

    def use_calculated_deployment(self, player_index: int) -> tuple[bool, str]:
        if self.phase != "siege":
            return False, "Calculated Deployment can only be used in siege."
        if self.pending_siege_roll is None or self.pending_first_deployer_choice is None:
            return False, "No unresolved deployment roll."
        if self._class_name(player_index) != "Grand Strategist" or self._class_level(player_index) < 3:
            return False, "Grand Strategist level 3 is required."
        player = self.players[player_index]
        if player.resources["calculated_deployment_used"] == 1:
            return False, "Calculated Deployment already used this siege."
        if player_index != self.pending_siege_roll["loser"]:
            return False, "Only the roll loser may use Calculated Deployment."

        p1_roll, p2_roll, winner = self._roll_deployment_winner()
        loser = self._opponent(winner)
        self.pending_siege_roll = {"p1": p1_roll, "p2": p2_roll, "winner": winner, "loser": loser}
        self.pending_first_deployer_choice = winner
        self.current_player_index = winner
        player.resources["calculated_deployment_used"] = 1
        self._log(
            f"{player.name} used Calculated Deployment reroll: P1={p1_roll}, P2={p2_roll}, "
            f"P{winner + 1} now chooses first deployer."
        )
        return True, "Deployment roll rerolled."

    def _available_attack_targets(self, player_index: int) -> list[int | str]:
        occupied_slots = [slot for slot in self.battlefield_gap if slot["card"] is not None]
        if not occupied_slots:
            return []

        legal_columns: list[int] = []
        if player_index == 0:
            legal_columns.append(0)
            if self._player_controls_column(0, 0):
                legal_columns.append(1)
            if self._player_controls_column(0, 1):
                legal_columns.append(2)
        else:
            legal_columns.append(2)
            if self._player_controls_column(1, 2):
                legal_columns.append(1)
            if self._player_controls_column(1, 1):
                legal_columns.append(0)

        targets: list[int | str] = []
        for slot in occupied_slots:
            if slot["slot"] % 3 in legal_columns:
                targets.append(slot["slot"])

        # You may always assign a battalion to your own barracks to defend it.
        targets.append(f"barracks:{player_index}")
        # Enemy barracks remains a push objective unlocked by full battlefield control.
        if self._player_controls_all_battlefields(player_index):
            targets.append(f"barracks:{self._opponent(player_index)}")

        deduped: list[int | str] = []
        for target in targets:
            if target not in deduped:
                deduped.append(target)
        return deduped

    def _has_undeployed_nonempty_battalion(self, player_index: int) -> bool:
        for bidx, battalion in enumerate(self.players[player_index].battalions):
            if battalion.cards and self.siege_assignments[player_index][bidx] is None:
                return True
        return False

    def _all_nonempty_battalions_deployed(self) -> bool:
        for pidx in (0, 1):
            for bidx, battalion in enumerate(self.players[pidx].battalions):
                if battalion.cards and self.siege_assignments[pidx][bidx] is None:
                    return False
        return True

    def assign_battalion_to_slot(
        self, player_index: int, battalion_index: int, target: int | str
    ) -> tuple[bool, str]:
        if self.phase != "siege":
            return False, "Battalion deployment is only valid in siege."
        if self.pending_first_deployer_choice is not None:
            return False, "First deployer choice is pending."
        ok, msg = self._legal_active_action(player_index)
        if not ok:
            return False, msg
        player = self.players[player_index]
        if battalion_index not in (0, 1):
            return False, "Battalion index must be 0 or 1."
        battalion = player.battalions[battalion_index]
        if not battalion.cards:
            return False, "Cannot deploy an empty battalion."
        if self.siege_assignments[player_index][battalion_index] is not None:
            return False, "This battalion has already been deployed."
        other_bidx = 1 - battalion_index
        if self.siege_assignments[player_index][other_bidx] == target:
            return False, "Both battalions cannot target the same location."

        legal_targets = self._available_attack_targets(player_index)
        if target not in legal_targets:
            return False, "Invalid target for this player."

        self.siege_assignments[player_index][battalion_index] = target
        self._log(
            f"{player.name} deployed Battalion {battalion_index + 1} to target {target}."
        )

        if self._all_nonempty_battalions_deployed():
            return self._resolve_siege_and_cleanup()

        other = self._opponent(player_index)
        if self._has_undeployed_nonempty_battalion(player_index):
            # First deployer keeps placing until all of their non-empty battalions are assigned.
            self.current_player_index = player_index
        elif self._has_undeployed_nonempty_battalion(other):
            self.current_player_index = other
        return True, "Battalion deployed."

    def use_tactical_gambit(self, player_index: int) -> tuple[bool, str]:
        if self.phase != "siege":
            return False, "Tactical Gambit can only be used in siege."
        ok, msg = self._legal_active_action(player_index)
        if not ok:
            return False, msg
        if self._class_name(player_index) != "Grand Strategist" or self._class_level(player_index) < 6:
            return False, "Grand Strategist level 6 is required."
        player = self.players[player_index]
        if player.resources["tactical_gambit_used"] == 1:
            return False, "Tactical Gambit already used this game."
        if self.siege_assignments[player_index][0] is None or self.siege_assignments[player_index][1] is None:
            return False, "Both battalions must be deployed first."
        self.siege_assignments[player_index][0], self.siege_assignments[player_index][1] = (
            self.siege_assignments[player_index][1],
            self.siege_assignments[player_index][0],
        )
        player.resources["tactical_gambit_used"] = 1
        self._log(f"{player.name} used Tactical Gambit (swapped battalion targets).")
        return True, "Tactical Gambit resolved."

    def use_total_conquest(self, player_index: int) -> tuple[bool, str]:
        if self.phase != "draw":
            return False, "Total Conquest can only be used in draw."
        ok, msg = self._legal_active_action(player_index)
        if not ok:
            return False, msg
        if self._class_name(player_index) != "Vanguard" or self._class_level(player_index) < 6:
            return False, "Vanguard level 6 is required."
        player = self.players[player_index]
        if player.resources["total_conquest_used"] == 1:
            return False, "Total Conquest already used this game."
        if player.resources.get("total_conquest_ready", 0) != 1:
            return False, "Total Conquest is not primed yet."
        enemy = self.players[self._opponent(player_index)]
        if not enemy.barracks.units:
            return False, "Enemy barracks has no units to target."
        if self.pending_total_conquest_pick_player is not None:
            return False, "A Total Conquest target selection is already pending."
        self.pending_total_conquest_pick_player = player_index
        self._log(f"{player.name} activated Total Conquest and must choose an enemy barracks unit.")
        return True, "Choose an enemy barracks unit to fell."

    def choose_total_conquest_target(
        self, player_index: int, enemy_barracks_index: int
    ) -> tuple[bool, str]:
        if self.pending_total_conquest_pick_player is None:
            return False, "No pending Total Conquest selection."
        if player_index != self.pending_total_conquest_pick_player:
            return False, "This player cannot resolve Total Conquest."
        if player_index != self.current_player_index:
            return False, "It is not this player's action turn."

        conqueror = self.players[player_index]
        enemy_index = self._opponent(player_index)
        enemy = self.players[enemy_index]
        if enemy_barracks_index < 0 or enemy_barracks_index >= len(enemy.barracks.units):
            return False, "Invalid enemy barracks unit index."

        felled = enemy.barracks.units.pop(enemy_barracks_index)
        self._handle_felled_cards(enemy_index, [felled], slot_index=None)
        conqueror.resources["total_conquest_used"] = 1
        conqueror.resources["total_conquest_ready"] = 0
        self.pending_total_conquest_pick_player = None
        self._log(
            f"{conqueror.name} resolved Total Conquest and felled {enemy.name}'s {felled.name} from barracks."
        )
        return True, "Total Conquest resolved."

    def use_relentless_push(
        self,
        player_index: int,
        battalion_index: int | None = None,
        card_index: int | None = None,
        pay_resource: str | None = None,
    ) -> tuple[bool, str]:
        if self.phase != "siege":
            return False, "Relentless Push can only be used in siege."
        ok, msg = self._legal_active_action(player_index)
        if not ok:
            return False, msg
        if self._class_name(player_index) != "Vanguard" or self._class_level(player_index) < 3:
            return False, "Vanguard level 3 is required."
        player = self.players[player_index]
        if player.resources["relentless_push_used"] == 1:
            return False, "Relentless Push already used this siege."

        target = self._find_frontline_target(player_index, battalion_index, card_index)
        if target is None:
            return False, "No valid front-line target."
        card = target

        if pay_resource is None:
            pay_resource = "ore" if player.resources["ore"] >= 1 else "materia"
        if pay_resource not in ("ore", "materia"):
            return False, "Relentless Push must pay ore or materia."
        if player.resources[pay_resource] < 1:
            return False, f"Not enough {pay_resource}."

        player.resources[pay_resource] -= 1
        card.temp_might_bonus += 2
        player.resources["relentless_push_used"] = 1
        self._log(f"{player.name} used Relentless Push on {card.name}.")
        return True, "Relentless Push resolved."

    def use_eye_of_storm(
        self, player_index: int, battalion_index: int | None = None, card_index: int | None = None
    ) -> tuple[bool, str]:
        if self.phase != "siege":
            return False, "Eye of the Storm can only be used in siege."
        ok, msg = self._legal_active_action(player_index)
        if not ok:
            return False, msg
        if self._class_name(player_index) != "Storm Warden" or self._class_level(player_index) < 6:
            return False, "Storm Warden level 6 is required."
        player = self.players[player_index]
        if player.resources["eye_of_storm_used"] == 1:
            return False, "Eye of the Storm already used this siege."
        if player.resources["magium"] < 1:
            return False, "Not enough magium."

        target = self._find_frontline_target(player_index, battalion_index, card_index)
        if target is None:
            return False, "No valid front-line target."
        player.resources["magium"] -= 1
        target.temp_might_bonus += 2
        player.resources["eye_of_storm_used"] = 1
        self._log(f"{player.name} used Eye of the Storm on {target.name}.")
        return True, "Eye of the Storm resolved."

    def use_pyre_decree(self, player_index: int) -> tuple[bool, str]:
        if self.phase != "siege":
            return False, "Pyre Decree can only be used in siege."
        ok, msg = self._legal_active_action(player_index)
        if not ok:
            return False, msg
        if self._class_name(player_index) != "Ash Chancellor" or self._class_level(player_index) < 6:
            return False, "Ash Chancellor level 6 is required."
        player = self.players[player_index]
        if player.resources["pyre_decree_used"] == 1:
            return False, "Pyre Decree already used this siege."
        if player.resources["sacrifice"] < 2:
            return False, "Not enough sacrifice."
        boosted = 0
        for battalion in player.battalions:
            for unit in battalion.cards:
                if unit.effective_line() == "Front":
                    unit.temp_might_bonus += 2
                    boosted += 1
        if boosted == 0:
            return False, "No front-line units to buff."
        player.resources["sacrifice"] -= 2
        player.resources["pyre_decree_used"] = 1
        self._log(f"{player.name} used Pyre Decree (+2 might to all front-line units).")
        return True, "Pyre Decree resolved."

    def _find_frontline_target(
        self, player_index: int, battalion_index: int | None, card_index: int | None
    ) -> Card | None:
        player = self.players[player_index]
        if battalion_index in (0, 1):
            battalion = player.battalions[battalion_index]
            if card_index is not None and 0 <= card_index < len(battalion.cards):
                card = battalion.cards[card_index]
                if card.effective_line() == "Front":
                    return card
            for card in battalion.cards:
                if card.effective_line() == "Front":
                    return card
        for battalion in player.battalions:
            for card in battalion.cards:
                if card.effective_line() == "Front":
                    return card
        return None

    # --------------------------------------------------------------------- #
    # Siege resolution
    # --------------------------------------------------------------------- #
    def _resolve_siege_and_cleanup(self) -> tuple[bool, str]:
        if self.phase != "siege":
            return False, "Not currently in siege."
        self._log("Resolving siege...")
        had_contested_slot_battle = False
        siege_report: dict[str, Any] = {
            "turn": self.turn,
            "slot_battles": [],
            "barracks_battles": [],
            "winner": None,
        }
        for slot in range(6):
            if self.winner is not None:
                break
            slot_report = self._resolve_slot_battle(slot)
            if bool(slot_report.get("contested", False)):
                had_contested_slot_battle = True
                siege_report["slot_battles"].append(slot_report)
        if self.winner is None:
            p1_barracks_report = self._resolve_barracks_attack(defender_index=0)
            if p1_barracks_report is not None:
                siege_report["barracks_battles"].append(p1_barracks_report)
        if self.winner is None:
            p2_barracks_report = self._resolve_barracks_attack(defender_index=1)
            if p2_barracks_report is not None:
                siege_report["barracks_battles"].append(p2_barracks_report)
        siege_report["winner"] = self.winner
        self.pending_siege_report = siege_report if had_contested_slot_battle else None
        self.phase = "field_cleanup"
        self._field_cleanup()
        if self.winner is None:
            self.turn += 1
            self.phase = "replenish"
            self.current_player_index = 0
            self.pending_first_deployer_choice = None
            self.pending_siege_roll = None
            self._log("Siege complete. Next phase is replenish.")
            return True, "Siege resolved. Turn advanced to replenish."
        return True, f"Siege resolved. {self.players[self.winner].name} wins."

    def _cards_assigned_to_target(self, player_index: int, target: int | str) -> list[Card]:
        cards: list[Card] = []
        player = self.players[player_index]
        for bidx, assignment in enumerate(self.siege_assignments[player_index]):
            if assignment == target:
                cards.extend(player.battalions[bidx].cards)
        return cards

    def _clear_cards_assigned_to_target(self, player_index: int, target: int | str) -> None:
        player = self.players[player_index]
        for bidx, assignment in enumerate(self.siege_assignments[player_index]):
            if assignment == target:
                player.battalions[bidx].cards.clear()

    def _combat_card_attack(self, card: Card, mods: dict[Card, dict[str, int]]) -> int:
        return (card.might or 0) + mods.get(card, {}).get("might", 0)

    def _summarize_battle_side(
        self,
        cards: list[Card],
        mods: dict[Card, dict[str, int]],
        *,
        final_might: int,
        line_mix_penalty: int,
    ) -> dict[str, Any]:
        front_cards: list[dict[str, Any]] = []
        back_cards: list[dict[str, Any]] = []
        other_cards: list[dict[str, Any]] = []

        for card in cards:
            line = card.effective_line()
            attack = self._combat_card_attack(card, mods)
            card_summary = {
                "name": card.name,
                "line": line,
                "attack": attack,
                "base_might": card.might or 0,
                "base_will": card.will_ or 0,
                "might_mod": mods.get(card, {}).get("might", 0),
                "will_mod": mods.get(card, {}).get("will", 0),
            }
            if line == "Front":
                front_cards.append(card_summary)
            elif line == "Back":
                back_cards.append(card_summary)
            else:
                other_cards.append(card_summary)

        return {
            "total_might": final_might,
            "attack_might": max(0, final_might),
            "line_mix_penalty": line_mix_penalty,
            "front_might": sum(card["attack"] for card in front_cards),
            "back_might": sum(card["attack"] for card in back_cards),
            "other_might": sum(card["attack"] for card in other_cards),
            "front_cards": front_cards,
            "back_cards": back_cards,
            "other_cards": other_cards,
        }

    def _resolve_slot_battle(self, slot_index: int) -> dict[str, Any]:
        p1_cards = list(self._cards_assigned_to_target(0, slot_index))
        p2_cards = list(self._cards_assigned_to_target(1, slot_index))
        battlefield_name = self._battlefield_name_at(slot_index)
        if not p1_cards and not p2_cards:
            return {
                "slot": slot_index,
                "battlefield_name": battlefield_name,
                "skipped": True,
                "contested": False,
                "p1": None,
                "p2": None,
                "deaths": {"p1": [], "p2": []},
                "prior_controller": self.battlefield_gap[slot_index]["controlled_by"],
                "new_controller": self.battlefield_gap[slot_index]["controlled_by"],
            }

        prior_controller = self.battlefield_gap[slot_index]["controlled_by"]
        for card in p1_cards + p2_cards:
            card.temp_line_override = None

        self._apply_spire_swaps(p1_cards, p2_cards)
        self._apply_spire_swaps(p2_cards, p1_cards)

        p1_mods = self._compute_modifiers_for_battalion(0, p1_cards, slot_index)
        p2_mods = self._compute_modifiers_for_battalion(1, p2_cards, slot_index)

        p1_might = self._compute_total_might(p1_cards, p1_mods)
        p2_might = self._compute_total_might(p2_cards, p2_mods)
        p1_line_mix_penalty = 0
        p2_line_mix_penalty = 0
        if self._contains_name(p1_cards, "Spire Mind-Bender") and self._has_front_and_back(p2_cards):
            p2_line_mix_penalty -= 1
            p2_might -= 1
        if self._contains_name(p2_cards, "Spire Mind-Bender") and self._has_front_and_back(p1_cards):
            p1_line_mix_penalty -= 1
            p1_might -= 1

        p1_summary = self._summarize_battle_side(
            p1_cards,
            p1_mods,
            final_might=p1_might,
            line_mix_penalty=p1_line_mix_penalty,
        )
        p2_summary = self._summarize_battle_side(
            p2_cards,
            p2_mods,
            final_might=p2_might,
            line_mix_penalty=p2_line_mix_penalty,
        )

        p1_dead, p1_survivors, p2_overflow = self._apply_damage_pipeline(
            incoming_might=max(0, p2_might),
            defenders=p1_cards,
            defender_mods=p1_mods,
        )
        p2_dead, p2_survivors, p1_overflow = self._apply_damage_pipeline(
            incoming_might=max(0, p1_might),
            defenders=p2_cards,
            defender_mods=p2_mods,
        )

        self._mark_pikeline_survivors(p1_survivors)
        self._mark_pikeline_survivors(p2_survivors)

        self._resolve_bloodmage_pulses(
            attacker_index=0,
            own_survivors=p1_survivors,
            own_dead=p1_dead,
            enemy_survivors=p2_survivors,
            enemy_dead=p2_dead,
            enemy_mods=p2_mods,
        )
        self._resolve_bloodmage_pulses(
            attacker_index=1,
            own_survivors=p2_survivors,
            own_dead=p2_dead,
            enemy_survivors=p1_survivors,
            enemy_dead=p1_dead,
            enemy_mods=p1_mods,
        )

        self._resolve_slag_brute_debuffs(dead_cards=p1_dead, enemy_survivors=p2_survivors)
        self._resolve_slag_brute_debuffs(dead_cards=p2_dead, enemy_survivors=p1_survivors)

        self._apply_overflow_rewards(0, p1_cards, p1_overflow, slot_index)
        self._apply_overflow_rewards(1, p2_cards, p2_overflow, slot_index)

        self._handle_felled_cards(0, p1_dead, slot_index)
        self._handle_felled_cards(1, p2_dead, slot_index)

        self._clear_cards_assigned_to_target(0, slot_index)
        self._clear_cards_assigned_to_target(1, slot_index)
        for card in p1_survivors:
            self._return_card_to_assigned_battalion(0, card)
        for card in p2_survivors:
            self._return_card_to_assigned_battalion(1, card)

        new_controller = self._determine_control(slot_index, p1_survivors, p2_survivors)
        # Ties hold prior control; only previously neutral battlefields stay neutral.
        if new_controller is None and prior_controller is not None:
            new_controller = prior_controller
        self.battlefield_gap[slot_index]["controlled_by"] = new_controller
        self._log(
            f"Slot {slot_index} resolved: "
            f"P1 survivors={len(p1_survivors)} P2 survivors={len(p2_survivors)} "
            f"control={new_controller}."
        )

        self._grant_grand_strategist_xp(0, bool(p1_cards), new_controller)
        self._grant_grand_strategist_xp(1, bool(p2_cards), new_controller)

        if (
            self._battlefield_name_at(slot_index) == "Silent Chasm"
            and prior_controller is not None
            and new_controller == prior_controller
            and bool(p1_cards)
            and bool(p2_cards)
        ):
            self._handle_silent_chasm_profitable_standoff(prior_controller)

        if new_controller is not None and new_controller != prior_controller:
            self._handle_total_conquest(new_controller)

        return {
            "slot": slot_index,
            "battlefield_name": battlefield_name,
            "skipped": False,
            "contested": bool(p1_cards and p2_cards),
            "p1": p1_summary,
            "p2": p2_summary,
            "deaths": {
                "p1": [card.name for card in p1_dead],
                "p2": [card.name for card in p2_dead],
            },
            "prior_controller": prior_controller,
            "new_controller": new_controller,
            "p1_overflow": p1_overflow,
            "p2_overflow": p2_overflow,
        }

    def _resolve_barracks_attack(self, defender_index: int) -> dict[str, Any] | None:
        target = f"barracks:{defender_index}"
        attacker_index = self._opponent(defender_index)
        attackers = list(self._cards_assigned_to_target(attacker_index, target))
        defending_battalion_cards = list(self._cards_assigned_to_target(defender_index, target))
        if not attackers:
            return None

        defender = self.players[defender_index]
        defenders = defending_battalion_cards + list(defender.barracks.units)

        for card in attackers + defenders:
            card.temp_line_override = None
        self._apply_spire_swaps(attackers, defenders)
        self._apply_spire_swaps(defenders, attackers)

        atk_mods = self._compute_modifiers_for_battalion(attacker_index, attackers, slot_index=None)
        def_mods = self._compute_modifiers_for_battalion(defender_index, defenders, slot_index=None)

        atk_might = self._compute_total_might(attackers, atk_mods)
        def_might = self._compute_total_might(defenders, def_mods)
        attacker_line_mix_penalty = 0
        defender_line_mix_penalty = 0
        if self._contains_name(attackers, "Spire Mind-Bender") and self._has_front_and_back(defenders):
            defender_line_mix_penalty -= 1
            def_might -= 1
        if self._contains_name(defenders, "Spire Mind-Bender") and self._has_front_and_back(attackers):
            attacker_line_mix_penalty -= 1
            atk_might -= 1

        attacker_summary = self._summarize_battle_side(
            attackers,
            atk_mods,
            final_might=atk_might,
            line_mix_penalty=attacker_line_mix_penalty,
        )
        defender_summary = self._summarize_battle_side(
            defenders,
            def_mods,
            final_might=def_might,
            line_mix_penalty=defender_line_mix_penalty,
        )

        atk_dead, atk_survivors, _ = self._apply_damage_pipeline(
            incoming_might=max(0, def_might),
            defenders=attackers,
            defender_mods=atk_mods,
        )
        def_dead, def_survivors, atk_overflow = self._apply_damage_pipeline(
            incoming_might=max(0, atk_might),
            defenders=defenders,
            defender_mods=def_mods,
        )

        self._mark_pikeline_survivors(atk_survivors)
        self._mark_pikeline_survivors(def_survivors)
        self._resolve_bloodmage_pulses(
            attacker_index=attacker_index,
            own_survivors=atk_survivors,
            own_dead=atk_dead,
            enemy_survivors=def_survivors,
            enemy_dead=def_dead,
            enemy_mods=def_mods,
        )
        self._resolve_bloodmage_pulses(
            attacker_index=defender_index,
            own_survivors=def_survivors,
            own_dead=def_dead,
            enemy_survivors=atk_survivors,
            enemy_dead=atk_dead,
            enemy_mods=atk_mods,
        )
        self._resolve_slag_brute_debuffs(dead_cards=atk_dead, enemy_survivors=def_survivors)
        self._resolve_slag_brute_debuffs(dead_cards=def_dead, enemy_survivors=atk_survivors)

        self._apply_overflow_rewards(attacker_index, attackers, atk_overflow, slot_index=None)
        self._handle_felled_cards(attacker_index, atk_dead, slot_index=None)
        self._handle_felled_cards(defender_index, def_dead, slot_index=None)

        self._clear_cards_assigned_to_target(attacker_index, target)
        self._clear_cards_assigned_to_target(defender_index, target)
        for card in atk_survivors:
            self._return_card_to_assigned_battalion(attacker_index, card)
        for card in def_survivors:
            if card in defending_battalion_cards:
                self._return_card_to_assigned_battalion(defender_index, card)
        defender.barracks.units = [card for card in def_survivors if card not in defending_battalion_cards]

        if atk_survivors:
            self.winner = attacker_index
            self._log(
                f"{self.players[attacker_index].name} breached enemy barracks and wins immediately."
            )

        return {
            "target": target,
            "attacker_index": attacker_index,
            "defender_index": defender_index,
            "attacker": attacker_summary,
            "defender": defender_summary,
            "deaths": {
                f"p{attacker_index + 1}": [card.name for card in atk_dead],
                f"p{defender_index + 1}": [card.name for card in def_dead],
            },
            "attacker_overflow": atk_overflow,
        }

    # --------------------------------------------------------------------- #
    # Combat helpers
    # --------------------------------------------------------------------- #
    def _contains_name(self, cards: list[Card], name: str) -> bool:
        return any(card.name == name for card in cards)

    def _has_front_and_back(self, cards: list[Card]) -> bool:
        has_front = any(card.effective_line() == "Front" for card in cards)
        has_back = any(card.effective_line() == "Back" for card in cards)
        return has_front and has_back

    def _apply_spire_swaps(self, source_cards: list[Card], enemy_cards: list[Card]) -> None:
        if not self._contains_name(source_cards, "Spire Mind-Bender"):
            return
        enemy_front = None
        enemy_back = None
        for card in enemy_cards:
            if enemy_front is None and card.effective_line() == "Front":
                enemy_front = card
            elif enemy_back is None and card.effective_line() == "Back":
                enemy_back = card
        if enemy_front and enemy_back:
            enemy_front.temp_line_override = "Back"
            enemy_back.temp_line_override = "Front"

    def _compute_modifiers_for_battalion(
        self,
        player_index: int,
        cards: list[Card],
        slot_index: int | None,
    ) -> dict[Card, dict[str, int]]:
        mods: dict[Card, dict[str, int]] = {}
        if not cards:
            return mods

        has_backline = any(card.effective_line() == "Back" for card in cards)
        has_standard_bearer = self._contains_name(cards, "Zealous Standard-Bearer")
        controls_grand_cathedral = self._player_controls_battlefield(player_index, "Grand Cathedral")
        breach_slots = [
            slot["slot"]
            for slot in self.battlefield_gap
            if slot["controlled_by"] == player_index and slot["card"] and slot["card"].name == "Breach Point"
        ]
        storm_warden_frontline_buff = (
            self._class_name(player_index) == "Storm Warden" and self._class_level(player_index) >= 1
        )
        vanguard_crush_momentum = (
            self._class_name(player_index) == "Vanguard"
            and self._class_level(player_index) >= 1
            and slot_index is not None
            and self.battlefield_gap[slot_index]["controlled_by"] != player_index
        )

        for card in cards:
            might_mod = card.temp_might_bonus
            will_mod = card.temp_will_bonus
            line = card.effective_line()

            if has_standard_bearer and line == "Front":
                might_mod += 1
                will_mod += 1

            if card.name == "Ironclad Phalanx" and has_backline:
                will_mod += 2

            if (
                card.name == "Hollowed Sentry"
                and slot_index is not None
                and self.battlefield_gap[slot_index]["controlled_by"] == player_index
            ):
                will_mod += 2

            if controls_grand_cathedral and line == "Back":
                will_mod += 1

            if (
                slot_index is not None
                and breach_slots
                and line == "Front"
                and any(slot_index != breach_slot for breach_slot in breach_slots)
            ):
                might_mod += 1

            if storm_warden_frontline_buff and line == "Front":
                might_mod += 1

            if vanguard_crush_momentum and line == "Front":
                might_mod += 1

            mods[card] = {"might": might_mod, "will": will_mod}
        return mods

    def _compute_total_might(self, cards: list[Card], mods: dict[Card, dict[str, int]]) -> int:
        total = 0
        for card in cards:
            card_might = (card.might or 0) + mods.get(card, {}).get("might", 0)
            total += card_might
        return total

    def _apply_damage_pipeline(
        self,
        incoming_might: int,
        defenders: list[Card],
        defender_mods: dict[Card, dict[str, int]],
    ) -> tuple[list[Card], list[Card], bool]:
        survivors = list(defenders)
        dead: list[Card] = []

        fronts = [card for card in defenders if card.effective_line() == "Front"]
        backs = [card for card in defenders if card.effective_line() == "Back"]
        others = [card for card in defenders if card.effective_line() not in ("Front", "Back")]
        ordered = fronts + backs + others

        front_total_will = 0
        for card in fronts:
            will_mod = defender_mods.get(card, {}).get("will", 0)
            front_total_will += max(1, (card.will_ or 0) + will_mod)
        overflowed = bool(backs) and incoming_might > front_total_will

        remaining = incoming_might
        for card in ordered:
            if remaining <= 0:
                break
            will_mod = defender_mods.get(card, {}).get("will", 0)
            effective_will = max(1, (card.will_ or 0) + will_mod)
            to_apply = remaining

            if card.name == "Shield Initiate" and not card.shield_used_this_siege and to_apply > 0:
                to_apply = max(0, to_apply - 1)
                card.shield_used_this_siege = True

            if to_apply >= effective_will:
                dead.append(card)
                if card in survivors:
                    survivors.remove(card)
                remaining = to_apply - effective_will
            else:
                remaining = 0
        return dead, survivors, overflowed

    def _mark_pikeline_survivors(self, survivors: list[Card]) -> None:
        for card in survivors:
            if card.name == "Pikeline Recruit":
                card.temp_will_bonus += 1

    def _resolve_bloodmage_pulses(
        self,
        attacker_index: int,
        own_survivors: list[Card],
        own_dead: list[Card],
        enemy_survivors: list[Card],
        enemy_dead: list[Card],
        enemy_mods: dict[Card, dict[str, int]],
    ) -> None:
        if not self._contains_name(own_survivors, "Occultic Blood-Mage"):
            return
        front_deaths = sum(1 for card in own_dead if card.effective_line() == "Front")
        if front_deaths <= 0:
            return
        for _ in range(front_deaths):
            target = next((card for card in enemy_survivors if card.effective_line() == "Back"), None)
            if target is None:
                return
            effective_will = max(1, (target.will_ or 0) + enemy_mods.get(target, {}).get("will", 0))
            if effective_will <= 2:
                enemy_survivors.remove(target)
                enemy_dead.append(target)
                self._log(
                    f"{self.players[attacker_index].name} Blood-Mage pulse fells {target.name} (will <= 2)."
                )
            else:
                self._log(
                    f"{self.players[attacker_index].name} Blood-Mage pulse hits {target.name} (no persistent damage)."
                )

    def _resolve_slag_brute_debuffs(self, dead_cards: list[Card], enemy_survivors: list[Card]) -> None:
        for dead in dead_cards:
            if dead.name != "Volatile Slag-Brute":
                continue
            target = next((card for card in enemy_survivors if card.effective_line() == "Front"), None)
            if target and target.might is not None:
                target.might -= 1
                self._log(f"{target.name} loses 1 permanent might from Volatile Slag-Brute.")

    def _apply_overflow_rewards(
        self, player_index: int, cards: list[Card], overflowed: bool, slot_index: int | None
    ) -> None:
        if not overflowed:
            return
        player = self.players[player_index]
        self._log(f"{player.name} triggers overflow.")
        if slot_index is not None and self._player_controls_battlefield(player_index, "Scorched Wastes"):
            player.gain_resource("rations", 1)
            self._log(f"{player.name} gains +1 ration from Scorched Wastes.")
        if self._contains_name(cards, "Arcane Bombardier"):
            player.draw_card(1)
            self._log(f"{player.name} draws 1 from Arcane Bombardier overflow.")
        if self._class_name(player_index) == "Vanguard":
            player.add_xp(1)
        if self._class_name(player_index) == "Storm Warden":
            player.add_xp(1)
            if self._class_level(player_index) >= 3 and player.resources["static_surge_used"] == 0:
                player.gain_resource("magium", 1)
                player.resources["static_surge_used"] = 1
                self._log(f"{player.name} gains +1 magium from Static Surge.")

    def _handle_felled_cards(self, player_index: int, dead_cards: list[Card], slot_index: int | None) -> None:
        if not dead_cards:
            return
        player = self.players[player_index]
        if self._class_name(player_index) == "Ash Chancellor":
            player.add_xp(1)
            if self._class_level(player_index) >= 1 and player.resources["cinder_tithe_used"] == 0:
                player.gain_resource("sacrifice", 1)
                player.resources["cinder_tithe_used"] = 1
                self._log(f"{player.name} gains +1 sacrifice from Cinder Tithe.")

        for card in dead_cards:
            if card.name == "Conscripted Militia":
                player.resources["pending_rations"] += 1
                self._log(f"{player.name} queued +1 ration from Conscripted Militia.")
            if self._player_controls_battlefield(player_index, "Bloodletting Altar"):
                player.gain_resource("sacrifice", 1)
            if (
                slot_index is not None
                and player.barracks.card.name == "Sanctum of the Fallen"
                and self._is_back_row_slot(player_index, slot_index)
            ):
                player.draw_card(1)
            self._send_to_grave(player_index, card)

    def _send_to_grave(self, player_index: int, card: Card) -> None:
        card.revealed = True
        card.from_barracks = False
        card.clear_temporary_state()
        self.players[player_index].grave.append(card)

    def _is_back_row_slot(self, player_index: int, slot_index: int) -> bool:
        if player_index == 0:
            return slot_index in (3, 4, 5)
        return slot_index in (0, 1, 2)

    def _return_card_to_assigned_battalion(self, player_index: int, card: Card) -> None:
        player = self.players[player_index]
        assigned_indices = [idx for idx, target in enumerate(self.siege_assignments[player_index]) if target is not None]
        for bidx in assigned_indices:
            battalion = player.battalions[bidx]
            if battalion.has_room(card):
                battalion.cards.append(card)
                return
        if player.battalions[0].has_room(card):
            player.battalions[0].cards.append(card)

    def _determine_control(self, slot_index: int, p1_survivors: list[Card], p2_survivors: list[Card]) -> int | None:
        _ = slot_index
        if p1_survivors and not p2_survivors:
            return 0
        if p2_survivors and not p1_survivors:
            return 1
        if not p1_survivors and not p2_survivors:
            return None
        p1_base_might = sum(card.might or 0 for card in p1_survivors)
        p2_base_might = sum(card.might or 0 for card in p2_survivors)
        if p1_base_might > p2_base_might:
            return 0
        if p2_base_might > p1_base_might:
            return 1
        return None

    def _grant_grand_strategist_xp(
        self, player_index: int, had_units_in_fight: bool, result_controller: int | None
    ) -> None:
        if not had_units_in_fight:
            return
        if self._class_name(player_index) != "Grand Strategist":
            return
        if result_controller is None or result_controller == player_index:
            self.players[player_index].add_xp(1)

    def _handle_silent_chasm_profitable_standoff(self, owner_index: int) -> None:
        player = self.players[owner_index]
        self.profitable_standoff_charges[owner_index] += 1
        self._log(
            f"{player.name} held Silent Chasm in a contested battle and gained a Profitable Standoff for next draw."
        )

    def _handle_total_conquest(self, conqueror_index: int) -> None:
        if self._class_name(conqueror_index) != "Vanguard" or self._class_level(conqueror_index) < 6:
            return
        player = self.players[conqueror_index]
        if player.resources["total_conquest_used"] == 1:
            return
        if player.resources.get("total_conquest_ready", 0) == 0:
            player.resources["total_conquest_ready"] = 1
            self._log(f"{player.name} primed Total Conquest for a future draw phase.")

    # --------------------------------------------------------------------- #
    # Cleanup and shared class hooks
    # --------------------------------------------------------------------- #
    def _field_cleanup(self) -> None:
        for player in self.players:
            survivors: list[Card] = []
            for battalion in player.battalions:
                survivors.extend(battalion.cards)
                battalion.cards.clear()
            for card in survivors:
                card.revealed = True
                card.from_barracks = False
                card.clear_temporary_state()
                if card.name == "Camp Scout":
                    player.gain_resource("rations", 1)
                if card not in player.barracks.units:
                    player.barracks.units.append(card)
        self._log("Field cleanup complete.")

    def _on_non_unit_activated(self, player_index: int) -> None:
        if self.phase not in ("preparations", "siege"):
            return
        if self._class_name(player_index) != "Arch-Hierarch":
            return
        player = self.players[player_index]
        player.add_xp(1)
        if self.phase == "siege" and self._class_level(player_index) >= 3:
            target = self._first_unit_in_battalions(player_index)
            if target is not None:
                target.temp_will_bonus += 1
                self._log(f"{player.name} Holy Aegis grants +1 will to {target.name}.")

    def _first_unit_in_battalions(self, player_index: int) -> Card | None:
        for battalion in self.players[player_index].battalions:
            for card in battalion.cards:
                if card.card_type == "Unit":
                    return card
        return None
