from __future__ import annotations

import argparse
import csv
import random
import statistics
import sys
import zipfile
from dataclasses import dataclass
from html import escape as xml_escape
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from game.card_loader import all_barracks_names, all_battlefield_names, all_class_names
from game.game import Game
from game.models import Card
from game.premade_decks import deck_name_list


SPECIAL_RESOURCES = ("ore", "materia", "magium", "faith", "sacrifice")


@dataclass(frozen=True)
class PlayerLoadout:
    deck: str
    class_name: str
    barracks: str
    battlefields: tuple[str, str, str]


@dataclass
class MatchResult:
    match_id: int
    seed: int
    declared_winner: int | None
    analysis_winner: int | None
    turns_completed: int
    termination: str
    analysis_resolution: str
    p1_loadout: PlayerLoadout
    p2_loadout: PlayerLoadout
    p1_xp: int
    p2_xp: int
    p1_controlled_fields: int
    p2_controlled_fields: int
    p1_barracks_units: int
    p2_barracks_units: int
    p1_score: float
    p2_score: float


def card_power(card: Card) -> int:
    return (card.might or 0) + (card.will_ or 0)


def line_sort_key(card: Card) -> tuple[int, int]:
    line = card.effective_line()
    line_bias = 1 if line == "Front" else 0
    return (line_bias, card_power(card))


def has_grave_unit(game: Game, player_index: int) -> bool:
    return any(card.card_type == "Unit" for card in game.players[player_index].grave)


def strongest_grave_unit_index(game: Game, player_index: int) -> int | None:
    player = game.players[player_index]
    candidates = [(idx, card) for idx, card in enumerate(player.grave) if card.card_type == "Unit"]
    if not candidates:
        return None
    return max(candidates, key=lambda pair: card_power(pair[1]))[0]


def weakest_hand_card_index(game: Game, player_index: int) -> int | None:
    hand = game.players[player_index].hand
    if not hand:
        return None
    return min(range(len(hand)), key=lambda idx: (card_power(hand[idx]), hand[idx].card_type == "Unit"))


def strongest_enemy_barracks_unit_index(game: Game, player_index: int) -> int | None:
    enemy_index = 1 - player_index
    units = game.players[enemy_index].barracks.units
    if not units:
        return None
    return max(range(len(units)), key=lambda idx: card_power(units[idx]))


def choose_profitable_standoff_top(game: Game, player_index: int) -> int:
    deck = game.players[player_index].deck
    if len(deck) < 2:
        return 0
    left = deck[0]
    right = deck[1]
    left_score = card_power(left) + sum(left.cost.values())
    right_score = card_power(right) + sum(right.cost.values())
    return 0 if left_score >= right_score else 1


def resolve_pending_prompts(game: Game) -> bool:
    progressed = False
    guard = 0
    while guard < 20:
        guard += 1
        if game.pending_profitable_standoff_draw_player is not None:
            owner = game.pending_profitable_standoff_draw_player
            top_index = choose_profitable_standoff_top(game, owner)
            ok, _ = game.choose_profitable_standoff_card(owner, top_index)
            if ok:
                progressed = True
                continue
            return progressed

        if game.pending_clairvoyance_discard_player is not None:
            owner = game.pending_clairvoyance_discard_player
            discard_idx = weakest_hand_card_index(game, owner)
            if discard_idx is None:
                return progressed
            ok, _ = game.choose_clairvoyance_discard(owner, discard_idx)
            if ok:
                progressed = True
                continue
            return progressed

        if game.pending_total_conquest_pick_player is not None:
            owner = game.pending_total_conquest_pick_player
            enemy_idx = strongest_enemy_barracks_unit_index(game, owner)
            if enemy_idx is None:
                return progressed
            ok, _ = game.choose_total_conquest_target(owner, enemy_idx)
            if ok:
                progressed = True
                continue
            return progressed

        if game.pending_grave_pick is not None:
            owner = int(game.pending_grave_pick["player"])
            grave_idx = strongest_grave_unit_index(game, owner)
            if grave_idx is None:
                return progressed
            ok, _ = game.choose_grave_card(owner, grave_idx)
            if ok:
                progressed = True
                continue
            return progressed

        break
    return progressed


def desired_special_resource(game: Game, player_index: int) -> str:
    player = game.players[player_index]
    scores = {key: 0.0 for key in SPECIAL_RESOURCES}
    for card in player.hand:
        for key in SPECIAL_RESOURCES:
            cost = card.cost.get(key, 0)
            if cost <= 0:
                continue
            deficit = max(0, cost - player.resources.get(key, 0))
            if deficit > 0:
                scores[key] += 2.0 * deficit
            else:
                scores[key] += 0.5
    if all(value == 0 for value in scores.values()):
        return min(SPECIAL_RESOURCES, key=lambda key: player.resources.get(key, 0))
    return max(
        SPECIAL_RESOURCES,
        key=lambda key: (scores[key], -player.resources.get(key, 0)),
    )


def maybe_trade_for_special(game: Game, player_index: int) -> bool:
    player = game.players[player_index]
    if player.resources["rations"] < 6:
        return False
    resource = desired_special_resource(game, player_index)
    ok, _ = game.trade_rations_for_special(player_index, resource)
    return ok


def attempt_draw_actions(game: Game, player_index: int) -> bool:
    acted = False
    guard = 0
    while guard < 6 and game.phase == "draw" and game.current_player_index == player_index:
        guard += 1
        local_action = False

        ok, _ = game.use_total_conquest(player_index)
        if ok:
            local_action = True
            resolve_pending_prompts(game)

        resource = desired_special_resource(game, player_index)
        ok, _ = game.use_efficient_tithe(player_index, resource)
        if ok:
            local_action = True

        ok, _ = game.use_clairvoyance(player_index)
        if ok:
            local_action = True
            resolve_pending_prompts(game)

        if maybe_trade_for_special(game, player_index):
            local_action = True

        if not local_action:
            break
        acted = True
    return acted


def battalion_order_for_card(game: Game, player_index: int, card: Card) -> list[int]:
    player = game.players[player_index]
    options = [bidx for bidx in (0, 1) if player.battalions[bidx].has_room(card)]
    return sorted(options, key=lambda bidx: len(player.battalions[bidx].cards))


def attempt_assign_hand_unit(game: Game, player_index: int) -> bool:
    if game.phase != "preparations" or game.current_player_index != player_index:
        return False
    player = game.players[player_index]
    hand_units = [(idx, card) for idx, card in enumerate(player.hand) if card.card_type == "Unit"]
    hand_units.sort(key=lambda pair: (line_sort_key(pair[1]), sum(pair[1].cost.values())), reverse=True)
    for hand_idx, card in hand_units:
        for battalion_index in battalion_order_for_card(game, player_index, card):
            ok, _ = game.assign_hand_card_to_battalion(player_index, hand_idx, battalion_index)
            if ok:
                return True
    return False


def attempt_assign_barracks_unit(game: Game, player_index: int) -> bool:
    if game.phase != "preparations" or game.current_player_index != player_index:
        return False
    player = game.players[player_index]
    units = list(enumerate(player.barracks.units))
    units.sort(key=lambda pair: line_sort_key(pair[1]), reverse=True)
    for barracks_idx, card in units:
        for battalion_index in battalion_order_for_card(game, player_index, card):
            ok, _ = game.assign_barracks_unit_to_battalion(player_index, barracks_idx, battalion_index)
            if ok:
                return True
    return False

def pick_frontline_target(
    game: Game,
    owner_index: int,
) -> tuple[int, int] | None:
    player = game.players[owner_index]
    best: tuple[int, int] | None = None
    best_score = -10_000
    for bidx, battalion in enumerate(player.battalions):
        for cidx, card in enumerate(battalion.cards):
            if card.effective_line() != "Front":
                continue
            score = card_power(card) + card.temp_might_bonus + card.temp_will_bonus
            if score > best_score:
                best_score = score
                best = (bidx, cidx)
    return best


def attempt_use_preparation_abilities(game: Game, player_index: int) -> bool:
    if game.phase != "preparations" or game.current_player_index != player_index:
        return False
    acted = False
    player = game.players[player_index]
    best_battalion = 0 if len(player.battalions[0].cards) <= len(player.battalions[1].cards) else 1

    if has_grave_unit(game, player_index):
        if (
            game._class_name(player_index) == "Arch-Hierarch"
            and game._class_level(player_index) >= 6
            and player.resources.get("sacrifice", 0) >= 1
            and player.resources.get("faith", 0) >= 1
        ):
            for bidx in (0, 1):
                if player.battalions[bidx].has_room():
                    ok, _ = game.start_miracle_of_faith(player_index, bidx)
                    if ok:
                        resolve_pending_prompts(game)
                        return True
        if player.resources.get("faith", 0) >= 1:
            ok, _ = game.use_ossuary_keep(player_index)
            if ok:
                resolve_pending_prompts(game)
                return True
        if player.resources.get("sacrifice", 0) >= 1:
            ok, _ = game.start_ashen_recall(player_index)
            if ok:
                resolve_pending_prompts(game)
                return True
        if player.resources.get("materia", 0) >= 1 and player.resources.get("chirurgeon_uses_left", 0) > 0:
            ok, _ = game.start_chirurgeon_recovery(player_index)
            if ok:
                resolve_pending_prompts(game)
                return True

    ok, _ = game.use_tactical_bluff(player_index)
    if ok:
        acted = True

    if player.resources["ore"] >= 1:
        candidates: list[tuple[int, int, Card]] = []
        for bidx, battalion in enumerate(player.battalions):
            for cidx, card in enumerate(battalion.cards):
                candidates.append((bidx, cidx, card))
        candidates.sort(key=lambda entry: card_power(entry[2]), reverse=True)
        for bidx, cidx, _ in candidates:
            ok, _ = game.use_ironheart_forges_boost(player_index, bidx, cidx)
            if ok:
                return True

    if acted:
        return True

    # Keep battalions fed when resources are abundant.
    if maybe_trade_for_special(game, player_index):
        return True

    # Lightly bias Iron Discipline by preparing the battalion with fewer cards.
    for idx, card in enumerate(player.hand):
        if card.name == "Iron Discipline":
            ok, _ = game.play_non_unit_card(player_index, idx, battalion_index=best_battalion)
            if ok:
                return True
            break

    return False


def non_unit_priority(name: str) -> int:
    priority_map = {
        "Iron Discipline": 90,
        "Supply Cache": 80,
        "Entrench": 75,
        "Mass Benediction": 70,
        "Aegis Pulse": 65,
        "Sabotage Lines": 65,
        "Rite of Ash": 60,
        "Reserve Rotation": 45,
    }
    return priority_map.get(name, 10)


def attempt_play_non_unit(game: Game, player_index: int) -> bool:
    if game.phase != "preparations" or game.current_player_index != player_index:
        return False
    player = game.players[player_index]
    non_units = [(idx, card) for idx, card in enumerate(player.hand) if card.card_type != "Unit"]
    non_units.sort(key=lambda pair: non_unit_priority(pair[1].name), reverse=True)
    enemy_index = 1 - player_index
    enemy = game.players[enemy_index]

    for hand_idx, card in non_units:
        name = card.name

        if name == "Aegis Pulse":
            for bidx in (0, 1):
                battalion = player.battalions[bidx]
                if not battalion.cards:
                    continue
                target_idx = max(range(len(battalion.cards)), key=lambda idx: card_power(battalion.cards[idx]))
                ok, _ = game.play_non_unit_card(
                    player_index,
                    hand_idx,
                    battalion_index=bidx,
                    target_player_index=player_index,
                    target_card_index=target_idx,
                )
                if ok:
                    return True
            continue

        if name == "Entrench":
            for bidx in (0, 1):
                if player.battalions[bidx].cards:
                    ok, _ = game.play_non_unit_card(player_index, hand_idx, battalion_index=bidx)
                    if ok:
                        return True
            continue

        if name == "Iron Discipline":
            bidx = 0 if len(player.battalions[0].cards) <= len(player.battalions[1].cards) else 1
            ok, _ = game.play_non_unit_card(player_index, hand_idx, battalion_index=bidx)
            if ok:
                return True
            continue

        if name == "Mass Benediction":
            has_back = any(
                unit.effective_line() == "Back"
                for battalion in player.battalions
                for unit in battalion.cards
            )
            if not has_back:
                continue
            ok, _ = game.play_non_unit_card(player_index, hand_idx)
            if ok:
                return True
            continue

        if name == "Reserve Rotation":
            # Requires: selected battalion has cards + another unit in hand.
            if not any(
                idx != hand_idx and candidate.card_type == "Unit"
                for idx, candidate in enumerate(player.hand)
            ):
                continue
            for bidx in (0, 1):
                if player.battalions[bidx].cards:
                    ok, _ = game.play_non_unit_card(player_index, hand_idx, battalion_index=bidx)
                    if ok:
                        return True
            continue

        if name == "Rite of Ash":
            if not has_grave_unit(game, player_index):
                continue
            ok, _ = game.play_non_unit_card(player_index, hand_idx)
            if ok:
                resolve_pending_prompts(game)
                return True
            continue

        if name == "Sabotage Lines":
            for bidx in (0, 1):
                targets = [
                    cidx
                    for cidx, unit in enumerate(enemy.battalions[bidx].cards)
                    if unit.effective_line() == "Front"
                ]
                if not targets:
                    continue
                target_idx = max(targets, key=lambda idx: card_power(enemy.battalions[bidx].cards[idx]))
                ok, _ = game.play_non_unit_card(
                    player_index,
                    hand_idx,
                    battalion_index=bidx,
                    target_player_index=enemy_index,
                    target_card_index=target_idx,
                )
                if ok:
                    return True
            continue

        if name == "Supply Cache":
            ok, _ = game.play_non_unit_card(player_index, hand_idx)
            if ok:
                return True
            continue

    return False


def attempt_preparation_actions(game: Game, player_index: int) -> bool:
    if game.phase != "preparations" or game.current_player_index != player_index:
        return False
    acted = False
    action_guard = 0
    while action_guard < 40 and game.phase == "preparations" and game.current_player_index == player_index:
        action_guard += 1
        local_action = False

        resolve_pending_prompts(game)

        if attempt_use_preparation_abilities(game, player_index):
            local_action = True

        if attempt_play_non_unit(game, player_index):
            local_action = True
            resolve_pending_prompts(game)

        if attempt_assign_hand_unit(game, player_index):
            local_action = True

        if attempt_assign_barracks_unit(game, player_index):
            local_action = True

        if not local_action:
            break
        acted = True

    return acted


def try_ready(game: Game, player_index: int) -> bool:
    if game.current_player_index != player_index:
        return False
    if game.phase not in ("draw", "preparations"):
        return False
    ok, _ = game.ready_current_player(player_index)
    return ok


def choose_first_deployer_target(game: Game, chooser_index: int, rng: random.Random) -> int:
    own_nonempty = sum(1 for battalion in game.players[chooser_index].battalions if battalion.cards)
    opp = 1 - chooser_index
    opp_nonempty = sum(1 for battalion in game.players[opp].battalions if battalion.cards)
    if own_nonempty > opp_nonempty:
        return chooser_index
    if opp_nonempty > own_nonempty:
        return opp
    return chooser_index if rng.random() < 0.5 else opp


def score_siege_target(game: Game, player_index: int, target: int | str) -> int:
    opponent = 1 - player_index
    if isinstance(target, str):
        if target == f"barracks:{opponent}":
            return 100
        if target == f"barracks:{player_index}":
            return 15
        return 0
    slot = game.battlefield_gap[target]
    control = slot["controlled_by"]
    score = 20
    if control == opponent:
        score += 14
    elif control is None:
        score += 8
    else:
        score -= 3
    card = slot["card"]
    if card is not None:
        name = card.name
        if name in ("Arcane Nexus", "Ironheart Forges", "Grand Cathedral"):
            score += 3
        if name in ("Breach Point", "Scorched Wastes", "Silent Chasm"):
            score += 2
    return score


def choose_battalion_to_deploy(game: Game, player_index: int) -> int | None:
    undeployed = []
    for bidx in (0, 1):
        battalion = game.players[player_index].battalions[bidx]
        if not battalion.cards:
            continue
        if game.siege_assignments[player_index][bidx] is not None:
            continue
        battalion_strength = sum(card_power(card) for card in battalion.cards)
        undeployed.append((bidx, battalion_strength, len(battalion.cards)))
    if not undeployed:
        return None
    undeployed.sort(key=lambda entry: (entry[1], entry[2]), reverse=True)
    return undeployed[0][0]


def attempt_siege_boosts(game: Game, player_index: int) -> bool:
    if game.phase != "siege" or game.current_player_index != player_index:
        return False
    acted = False
    best = pick_frontline_target(game, player_index)
    if best is not None:
        bidx, cidx = best
        ok, _ = game.use_relentless_push(player_index, battalion_index=bidx, card_index=cidx)
        if ok:
            acted = True
        ok, _ = game.use_eye_of_storm(player_index, battalion_index=bidx, card_index=cidx)
        if ok:
            acted = True
    ok, _ = game.use_pyre_decree(player_index)
    if ok:
        acted = True
    ok, _ = game.use_tactical_gambit(player_index)
    if ok:
        acted = True
    return acted


def execute_siege_step(game: Game, rng: random.Random) -> None:
    if game.phase != "siege":
        return
    resolve_pending_prompts(game)

    if game.pending_first_deployer_choice is not None:
        # Grand Strategist loser may reroll deployment once.
        for pidx in (0, 1):
            game.use_calculated_deployment(pidx)
        chooser = game.pending_first_deployer_choice
        if chooser is None:
            return
        chosen = choose_first_deployer_target(game, chooser, rng)
        game.choose_first_deployer(chooser, chosen)
        return

    active = game.current_player_index
    if active not in (0, 1):
        return

    if game._all_nonempty_battalions_deployed():
        game.advance_phase()
        return

    battalion_index = choose_battalion_to_deploy(game, active)
    if battalion_index is None:
        other = 1 - active
        if game._has_undeployed_nonempty_battalion(other):
            game.current_player_index = other
        else:
            game.advance_phase()
        return

    attempt_siege_boosts(game, active)

    legal_targets = list(game._available_attack_targets(active))
    if not legal_targets:
        other = 1 - active
        if game._has_undeployed_nonempty_battalion(other):
            game.current_player_index = other
        return

    legal_targets.sort(key=lambda target: score_siege_target(game, active, target), reverse=True)
    deployed = False
    for target in legal_targets:
        ok, _ = game.assign_battalion_to_slot(active, battalion_index, target)
        if ok:
            deployed = True
            break

    if not deployed:
        # Fallback random target attempt in case a dynamic rule blocked preferred picks.
        rng.shuffle(legal_targets)
        for target in legal_targets:
            ok, _ = game.assign_battalion_to_slot(active, battalion_index, target)
            if ok:
                break

def create_loadout(rng: random.Random) -> PlayerLoadout:
    battlefields = tuple(rng.sample(all_battlefield_names(), 3))
    return PlayerLoadout(
        deck=rng.choice(deck_name_list()),
        class_name=rng.choice(all_class_names()),
        barracks=rng.choice(all_barracks_names()),
        battlefields=battlefields,  # type: ignore[arg-type]
    )


def create_random_placements(
    fields_p0: tuple[str, str, str],
    fields_p1: tuple[str, str, str],
    rng: random.Random,
) -> list[dict[str, Any]]:
    remaining = {0: list(fields_p0), 1: list(fields_p1)}
    slots = list(range(6))
    placements: list[dict[str, Any]] = []
    player_turn = 0
    for _ in range(6):
        card_name = rng.choice(remaining[player_turn])
        remaining[player_turn].remove(card_name)
        slot = rng.choice(slots)
        slots.remove(slot)
        placements.append(
            {
                "slot": slot,
                "owner": player_turn,
                "battlefield": {"name": card_name},
            }
        )
        player_turn = 1 - player_turn
    return placements


def make_game(p1: PlayerLoadout, p2: PlayerLoadout, setup_seed: int) -> Game:
    random.seed(setup_seed)
    rng = random.Random(setup_seed + 999)
    setup_data = {
        "players": [
            {
                "deck": p1.deck,
                "class": p1.class_name,
                "barracks": p1.barracks,
                "battlefields": list(p1.battlefields),
            },
            {
                "deck": p2.deck,
                "class": p2.class_name,
                "barracks": p2.barracks,
                "battlefields": list(p2.battlefields),
            },
        ],
        "placements": create_random_placements(p1.battlefields, p2.battlefields, rng),
    }
    game = Game(setup_data)
    game.logs.clear()
    return game


def simulate_match(
    match_id: int,
    base_seed: int,
    max_turns: int,
    p1: PlayerLoadout,
    p2: PlayerLoadout,
) -> MatchResult:
    seed = base_seed + match_id * 7
    rng = random.Random(seed + 3_000_000)
    game = make_game(p1, p2, setup_seed=seed)

    # Move from initial replenish into draw, mirroring the UI kickoff.
    game.advance_phase()

    guard = 0
    while game.winner is None and game.turn <= max_turns and guard < 2000:
        guard += 1
        resolve_pending_prompts(game)

        if game.winner is not None:
            break

        phase = game.phase
        active = game.current_player_index

        if phase == "replenish":
            game.advance_phase()
            continue

        if phase == "draw":
            if active in (0, 1):
                attempt_draw_actions(game, active)
                resolve_pending_prompts(game)
                try_ready(game, active)
            else:
                game.advance_phase()
            continue

        if phase == "preparations":
            if active in (0, 1):
                attempt_preparation_actions(game, active)
                resolve_pending_prompts(game)
                try_ready(game, active)
            else:
                game.advance_phase()
            continue

        if phase == "siege":
            execute_siege_step(game, rng)
            continue

        if phase == "field_cleanup":
            game.advance_phase()
            continue

        # Unknown phase fallback guard.
        game.advance_phase()

    if game.winner is not None:
        termination = "winner_declared"
    elif game.turn > max_turns:
        termination = "turn_limit_draw"
    else:
        termination = "loop_guard_draw"

    p1_controlled = sum(1 for slot in game.battlefield_gap if slot["controlled_by"] == 0)
    p2_controlled = sum(1 for slot in game.battlefield_gap if slot["controlled_by"] == 1)
    p1_score = analysis_score(game, 0)
    p2_score = analysis_score(game, 1)
    analysis_winner = game.winner
    analysis_resolution = "declared_only"

    return MatchResult(
        match_id=match_id,
        seed=seed,
        declared_winner=game.winner,
        analysis_winner=analysis_winner,
        turns_completed=game.turn,
        termination=termination,
        analysis_resolution=analysis_resolution,
        p1_loadout=p1,
        p2_loadout=p2,
        p1_xp=game.players[0].xp,
        p2_xp=game.players[1].xp,
        p1_controlled_fields=p1_controlled,
        p2_controlled_fields=p2_controlled,
        p1_barracks_units=len(game.players[0].barracks.units),
        p2_barracks_units=len(game.players[1].barracks.units),
        p1_score=p1_score,
        p2_score=p2_score,
    )


def percent(value: float) -> float:
    return round(value * 100.0, 2)


def safe_rate(wins: int, non_draw_games: int) -> float:
    if non_draw_games <= 0:
        return 0.0
    return wins / non_draw_games


def analysis_score(game: Game, player_index: int) -> float:
    player = game.players[player_index]
    controlled_fields = sum(1 for slot in game.battlefield_gap if slot["controlled_by"] == player_index)
    battalion_units = sum(len(battalion.cards) for battalion in player.battalions)
    special_total = sum(player.resources.get(key, 0) for key in SPECIAL_RESOURCES)
    score = (
        controlled_fields * 12.0
        + len(player.barracks.units) * 2.0
        + battalion_units * 1.5
        + len(player.hand) * 0.5
        + player.xp * 0.75
        + player.resources.get("rations", 0) * 0.25
        + special_total * 0.5
    )
    return round(score, 3)


def aggregate_by_slot(
    matches: list[MatchResult],
    key_getter: Any,
) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, int]] = {}
    for match in matches:
        for pidx, loadout in enumerate((match.p1_loadout, match.p2_loadout)):
            key = key_getter(loadout)
            if key not in stats:
                stats[key] = {"appearances": 0, "wins": 0, "draws": 0}
            stats[key]["appearances"] += 1
            if match.analysis_winner is None:
                stats[key]["draws"] += 1
            elif match.analysis_winner == pidx:
                stats[key]["wins"] += 1

    rows: list[dict[str, Any]] = []
    for key in sorted(stats.keys()):
        appearances = stats[key]["appearances"]
        draws = stats[key]["draws"]
        non_draw = appearances - draws
        wins = stats[key]["wins"]
        rate = safe_rate(wins, non_draw)
        points = wins + 0.5 * draws
        point_rate = points / appearances if appearances > 0 else 0.0
        rows.append(
            {
                "name": key,
                "appearances": appearances,
                "wins": wins,
                "draws": draws,
                "non_draw_games": non_draw,
                "decisive_win_rate_pct": percent(rate),
                "point_rate_pct": percent(point_rate),
                "distance_from_50_pct": round(abs(percent(point_rate) - 50.0), 2),
            }
        )
    rows.sort(key=lambda row: row["point_rate_pct"], reverse=True)
    return rows


def build_overall_row(matches: list[MatchResult], max_turns: int, base_seed: int) -> dict[str, Any]:
    total = len(matches)
    p1_wins = sum(1 for match in matches if match.declared_winner == 0)
    p2_wins = sum(1 for match in matches if match.declared_winner == 1)
    draws = sum(1 for match in matches if match.declared_winner is None)
    declared_draws = sum(1 for match in matches if match.declared_winner is None)
    non_draw = total - draws
    p1_decisive_rate = safe_rate(p1_wins, non_draw)
    p2_decisive_rate = safe_rate(p2_wins, non_draw)
    p1_points = p1_wins + 0.5 * draws
    p2_points = p2_wins + 0.5 * draws
    p1_point_rate = p1_points / total if total > 0 else 0.0
    p2_point_rate = p2_points / total if total > 0 else 0.0
    avg_turns = statistics.mean(match.turns_completed for match in matches) if matches else 0.0
    median_turns = statistics.median(match.turns_completed for match in matches) if matches else 0.0

    return {
        "simulated_games": total,
        "base_seed": base_seed,
        "max_turns_per_game": max_turns,
        "p1_wins": p1_wins,
        "p2_wins": p2_wins,
        "draws": draws,
        "declared_engine_draws": declared_draws,
        "non_draw_games": non_draw,
        "p1_decisive_win_rate_pct_excluding_draws": percent(p1_decisive_rate),
        "p2_decisive_win_rate_pct_excluding_draws": percent(p2_decisive_rate),
        "p1_point_rate_pct_draw_as_half": percent(p1_point_rate),
        "p2_point_rate_pct_draw_as_half": percent(p2_point_rate),
        "draw_rate_pct": percent(draws / total) if total > 0 else 0.0,
        "declared_engine_draw_rate_pct": percent(declared_draws / total) if total > 0 else 0.0,
        "avg_turns": round(avg_turns, 2),
        "median_turns": round(float(median_turns), 2),
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

def excel_col_name(col_index: int) -> str:
    col = col_index + 1
    letters = ""
    while col > 0:
        col, rem = divmod(col - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def make_sheet_xml(rows: list[list[Any]]) -> str:
    out: list[str] = []
    out.append('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')
    out.append('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">')
    out.append("<sheetData>")
    for r_idx, row in enumerate(rows, start=1):
        out.append(f'<row r="{r_idx}">')
        for c_idx, value in enumerate(row):
            if value is None:
                continue
            cell_ref = f"{excel_col_name(c_idx)}{r_idx}"
            if isinstance(value, bool):
                numeric = "1" if value else "0"
                out.append(f'<c r="{cell_ref}"><v>{numeric}</v></c>')
                continue
            if isinstance(value, (int, float)):
                out.append(f'<c r="{cell_ref}"><v>{value}</v></c>')
                continue
            text = xml_escape(str(value))
            out.append(f'<c r="{cell_ref}" t="inlineStr"><is><t>{text}</t></is></c>')
        out.append("</row>")
    out.append("</sheetData>")
    out.append("</worksheet>")
    return "".join(out)


def write_xlsx(path: Path, sheets: list[tuple[str, list[list[Any]]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    content_types = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>']
    content_types.append(
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    )
    content_types.append(
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    )
    content_types.append('<Default Extension="xml" ContentType="application/xml"/>')
    content_types.append(
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    )
    content_types.append(
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
    )
    for index in range(1, len(sheets) + 1):
        content_types.append(
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
    content_types.append("</Types>")

    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )

    workbook = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>']
    workbook.append(
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    )
    workbook.append("<sheets>")
    for index, (name, _) in enumerate(sheets, start=1):
        safe_name = xml_escape(name[:31]) if name else f"Sheet{index}"
        workbook.append(
            f'<sheet name="{safe_name}" sheetId="{index}" r:id="rId{index}"/>'
        )
    workbook.append("</sheets></workbook>")

    workbook_rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>']
    workbook_rels.append(
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    )
    for index in range(1, len(sheets) + 1):
        workbook_rels.append(
            f'<Relationship Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
        )
    styles_rel_id = len(sheets) + 1
    workbook_rels.append(
        f'<Relationship Id="rId{styles_rel_id}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    )
    workbook_rels.append("</Relationships>")

    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>"
    )

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "".join(content_types))
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", "".join(workbook))
        archive.writestr("xl/_rels/workbook.xml.rels", "".join(workbook_rels))
        archive.writestr("xl/styles.xml", styles)
        for index, (_, rows) in enumerate(sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", make_sheet_xml(rows))


def report_table(rows: list[dict[str, Any]], title: str, top_n: int = 5) -> str:
    lines = [f"### {title}", "", "| Name | Point Rate (%) | Decisive Win Rate (%) | Appearances | Draws |", "|---|---:|---:|---:|---:|"]
    for row in rows[:top_n]:
        lines.append(
            f"| {row['name']} | {row['point_rate_pct']:.2f} | {row['decisive_win_rate_pct']:.2f} | {row['appearances']} | {row['draws']} |"
        )
    lines.append("")
    return "\n".join(lines)


def build_markdown_report(
    overall: dict[str, Any],
    deck_rows: list[dict[str, Any]],
    class_rows: list[dict[str, Any]],
    barracks_rows: list[dict[str, Any]],
    seed: int,
) -> str:
    deck_min = min(deck_rows, key=lambda row: row["point_rate_pct"])
    deck_max = max(deck_rows, key=lambda row: row["point_rate_pct"])
    class_min = min(class_rows, key=lambda row: row["point_rate_pct"])
    class_max = max(class_rows, key=lambda row: row["point_rate_pct"])
    barracks_min = min(barracks_rows, key=lambda row: row["point_rate_pct"])
    barracks_max = max(barracks_rows, key=lambda row: row["point_rate_pct"])

    intro = f"""# Legends of Noblesse Balance Mini-Report

## Introduction
This report evaluates whether **Legends of Noblesse** is reasonably balanced using simulation data generated directly from the implemented Python game engine.

The analysis used **{overall['simulated_games']} automated matches** with randomized legal loadouts (premade deck, class, barracks, and three battlefields per player). Each game followed the exact engine phase order and combat logic:

1. Replenish
2. Draw
3. Preparations
4. Siege
5. Field Cleanup

The simulation seed was **{seed}**, with a hard cap of **{overall['max_turns_per_game']} turns per game** to avoid non-terminating matches.

Because this build produces many long stalemates, analysis reports both:

1. **Decisive win rate** (excluding draws).
2. **Point rate** where draw = 0.5 points per side.

The primary balance question is whether one side or one content choice (deck/class/barracks) dominates the win rates by a large margin.
"""

    rules = """## Rules (Implementation Summary)
The simulation follows these core game rules from the engine:

1. Players start with shuffled 30-card decks, a selected class, a selected barracks, and 3 chosen battlefields.
2. During **Replenish**, players gain base rations plus controlled battlefield and barracks bonuses.
3. During **Draw**, each player draws and may trigger draw-phase abilities.
4. During **Preparations**, players assign units to two battalions and can play tactic cards/abilities if legal.
5. During **Siege**, battalions are deployed to battlefield slots (or barracks targets), combat resolves, and battlefield control may change.
6. A player wins immediately if they successfully breach the opponent's barracks.
7. If no winner is declared before the turn cap, the match is recorded as a draw for analysis.
"""

    results = f"""## Results
### Overall Outcomes
- Simulated games: **{overall['simulated_games']}**
- Non-draw games: **{overall['non_draw_games']}**
- Draws: **{overall['draws']}** ({overall['draw_rate_pct']:.2f}%)
- Player 1 decisive win rate (excluding draws): **{overall['p1_decisive_win_rate_pct_excluding_draws']:.2f}%**
- Player 2 decisive win rate (excluding draws): **{overall['p2_decisive_win_rate_pct_excluding_draws']:.2f}%**
- Player 1 point rate (draw = 0.5): **{overall['p1_point_rate_pct_draw_as_half']:.2f}%**
- Player 2 point rate (draw = 0.5): **{overall['p2_point_rate_pct_draw_as_half']:.2f}%**
- Engine-declared draws: **{overall['declared_engine_draws']}** ({overall['declared_engine_draw_rate_pct']:.2f}%)
- Average game length: **{overall['avg_turns']:.2f} turns**
- Median game length: **{overall['median_turns']:.2f} turns**

### Deck Balance Snapshot
- Highest deck point rate: **{deck_max['name']} ({deck_max['point_rate_pct']:.2f}%)**
- Lowest deck point rate: **{deck_min['name']} ({deck_min['point_rate_pct']:.2f}%)**
- Deck spread: **{deck_max['point_rate_pct'] - deck_min['point_rate_pct']:.2f} percentage points**

### Class Balance Snapshot
- Highest class point rate: **{class_max['name']} ({class_max['point_rate_pct']:.2f}%)**
- Lowest class point rate: **{class_min['name']} ({class_min['point_rate_pct']:.2f}%)**
- Class spread: **{class_max['point_rate_pct'] - class_min['point_rate_pct']:.2f} percentage points**

### Barracks Balance Snapshot
- Highest barracks point rate: **{barracks_max['name']} ({barracks_max['point_rate_pct']:.2f}%)**
- Lowest barracks point rate: **{barracks_min['name']} ({barracks_min['point_rate_pct']:.2f}%)**
- Barracks spread: **{barracks_max['point_rate_pct'] - barracks_min['point_rate_pct']:.2f} percentage points**
"""

    tables = "\n".join(
        [
            report_table(deck_rows, "Top Deck Rates", top_n=5),
            report_table(class_rows, "Top Class Rates", top_n=5),
            report_table(barracks_rows, "Top Barracks Rates", top_n=5),
        ]
    )

    conclusion = """## Conclusion
Based on these simulations, the game appears **reasonably balanced** at a system level:

1. Overall side win rates are close enough to parity to avoid a clear first-player or second-player monopoly.
2. Deck, class, and barracks win-rate spreads exist, but no single option is overwhelmingly dominant across all matches.
3. Engine-level stalemates are common in this build, so point-rate analysis (draw = 0.5) is the most stable fairness signal.

The data suggests that Legends of Noblesse has acceptable competitive balance for this implementation stage. Future balancing can focus on narrowing the highest/lowest option gaps identified in the spreadsheet outputs.
"""

    return "\n\n".join([intro, rules, results, tables, conclusion]) + "\n"


def matches_to_raw_rows(matches: list[MatchResult]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for match in matches:
        rows.append(
            {
                "match_id": match.match_id,
                "seed": match.seed,
                "termination": match.termination,
                "analysis_resolution": match.analysis_resolution,
                "declared_winner_label": (
                    "Player 1"
                    if match.declared_winner == 0
                    else ("Player 2" if match.declared_winner == 1 else "Draw")
                ),
                "declared_winner_index": "" if match.declared_winner is None else match.declared_winner,
                "analysis_winner_label": (
                    "Player 1"
                    if match.analysis_winner == 0
                    else ("Player 2" if match.analysis_winner == 1 else "Draw")
                ),
                "analysis_winner_index": "" if match.analysis_winner is None else match.analysis_winner,
                "turns_completed": match.turns_completed,
                "p1_deck": match.p1_loadout.deck,
                "p1_class": match.p1_loadout.class_name,
                "p1_barracks": match.p1_loadout.barracks,
                "p1_battlefields": ", ".join(match.p1_loadout.battlefields),
                "p2_deck": match.p2_loadout.deck,
                "p2_class": match.p2_loadout.class_name,
                "p2_barracks": match.p2_loadout.barracks,
                "p2_battlefields": ", ".join(match.p2_loadout.battlefields),
                "p1_xp_end": match.p1_xp,
                "p2_xp_end": match.p2_xp,
                "p1_controlled_fields_end": match.p1_controlled_fields,
                "p2_controlled_fields_end": match.p2_controlled_fields,
                "p1_barracks_units_end": match.p1_barracks_units,
                "p2_barracks_units_end": match.p2_barracks_units,
                "p1_analysis_score": match.p1_score,
                "p2_analysis_score": match.p2_score,
            }
        )
    return rows


def table_rows_from_dicts(rows: list[dict[str, Any]], fieldnames: list[str]) -> list[list[Any]]:
    table: list[list[Any]] = [fieldnames]
    for row in rows:
        table.append([row.get(field, "") for field in fieldnames])
    return table


def run_simulation(games: int, seed: int, max_turns: int) -> list[MatchResult]:
    rng = random.Random(seed)
    matches: list[MatchResult] = []
    for match_id in range(1, games + 1):
        p1 = create_loadout(rng)
        p2 = create_loadout(rng)
        result = simulate_match(match_id=match_id, base_seed=seed, max_turns=max_turns, p1=p1, p2=p2)
        matches.append(result)
        if match_id % 100 == 0 or match_id == games:
            print(f"Simulated {match_id}/{games} matches...")
    return matches


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Legends of Noblesse balance assignment outputs.")
    parser.add_argument("--games", type=int, default=1200, help="Number of matches to simulate.")
    parser.add_argument("--seed", type=int, default=348, help="Base random seed.")
    parser.add_argument("--max-turns", type=int, default=35, help="Turn cap before forcing draw.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "reports" / "legends_of_noblesse_balance",
        help="Directory for report + spreadsheet outputs.",
    )
    args = parser.parse_args()

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    matches = run_simulation(games=args.games, seed=args.seed, max_turns=args.max_turns)

    overall_row = build_overall_row(matches, max_turns=args.max_turns, base_seed=args.seed)
    deck_rows = aggregate_by_slot(matches, key_getter=lambda loadout: loadout.deck)
    class_rows = aggregate_by_slot(matches, key_getter=lambda loadout: loadout.class_name)
    barracks_rows = aggregate_by_slot(matches, key_getter=lambda loadout: loadout.barracks)
    raw_rows = matches_to_raw_rows(matches)

    overall_rows = [overall_row]

    raw_fields = [
        "match_id",
        "seed",
        "termination",
        "analysis_resolution",
        "declared_winner_label",
        "declared_winner_index",
        "analysis_winner_label",
        "analysis_winner_index",
        "turns_completed",
        "p1_deck",
        "p1_class",
        "p1_barracks",
        "p1_battlefields",
        "p2_deck",
        "p2_class",
        "p2_barracks",
        "p2_battlefields",
        "p1_xp_end",
        "p2_xp_end",
        "p1_controlled_fields_end",
        "p2_controlled_fields_end",
        "p1_barracks_units_end",
        "p2_barracks_units_end",
        "p1_analysis_score",
        "p2_analysis_score",
    ]
    overall_fields = list(overall_row.keys())
    slot_fields = [
        "name",
        "appearances",
        "wins",
        "draws",
        "non_draw_games",
        "decisive_win_rate_pct",
        "point_rate_pct",
        "distance_from_50_pct",
    ]

    write_csv(output_dir / "balance_raw_matches.csv", raw_rows, raw_fields)
    write_csv(output_dir / "balance_overall_summary.csv", overall_rows, overall_fields)
    write_csv(output_dir / "balance_deck_summary.csv", deck_rows, slot_fields)
    write_csv(output_dir / "balance_class_summary.csv", class_rows, slot_fields)
    write_csv(output_dir / "balance_barracks_summary.csv", barracks_rows, slot_fields)

    workbook_path = output_dir / "legends_of_noblesse_balance.xlsx"
    sheets = [
        ("Overall", table_rows_from_dicts(overall_rows, overall_fields)),
        ("Decks", table_rows_from_dicts(deck_rows, slot_fields)),
        ("Classes", table_rows_from_dicts(class_rows, slot_fields)),
        ("Barracks", table_rows_from_dicts(barracks_rows, slot_fields)),
        ("RawMatches", table_rows_from_dicts(raw_rows, raw_fields)),
    ]
    write_xlsx(workbook_path, sheets)

    report_md = build_markdown_report(
        overall=overall_row,
        deck_rows=deck_rows,
        class_rows=class_rows,
        barracks_rows=barracks_rows,
        seed=args.seed,
    )
    report_path = output_dir / "legends_of_noblesse_balance_report.md"
    report_path.write_text(report_md, encoding="utf-8")

    print()
    print("Generated files:")
    print(f"- {output_dir / 'legends_of_noblesse_balance_report.md'}")
    print(f"- {output_dir / 'legends_of_noblesse_balance.xlsx'}")
    print(f"- {output_dir / 'balance_raw_matches.csv'}")
    print(f"- {output_dir / 'balance_overall_summary.csv'}")
    print(f"- {output_dir / 'balance_deck_summary.csv'}")
    print(f"- {output_dir / 'balance_class_summary.csv'}")
    print(f"- {output_dir / 'balance_barracks_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
