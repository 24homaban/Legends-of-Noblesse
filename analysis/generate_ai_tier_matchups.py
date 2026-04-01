from __future__ import annotations

import argparse
import random
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import analysis.generate_balance_assignment as base
from game.game import Game
from game.models import Card


BAD = "bad"
MEDIOCRE = "mediocre"
GOOD = "good"

MATCHUPS: list[tuple[str, str]] = [
    (BAD, BAD),
    (BAD, MEDIOCRE),
    (BAD, GOOD),
    (MEDIOCRE, GOOD),
    (MEDIOCRE, MEDIOCRE),
    (GOOD, GOOD),
]


@dataclass
class TierMatchRecord:
    match_id: int
    matchup_label: str
    p1_ai: str
    p2_ai: str
    declared_winner: int | None
    termination: str
    turns_completed: int
    loadout_deck: str
    loadout_class: str
    loadout_barracks: str
    loadout_battlefields: str
    p1_score: float
    p2_score: float


def copy_loadout(loadout: base.PlayerLoadout) -> base.PlayerLoadout:
    return base.PlayerLoadout(
        deck=loadout.deck,
        class_name=loadout.class_name,
        barracks=loadout.barracks,
        battlefields=tuple(loadout.battlefields),
    )


def tier_for_player(p1_ai: str, p2_ai: str, player_index: int) -> str:
    return p1_ai if player_index == 0 else p2_ai


def undeployed_battalions(game: Game, player_index: int) -> list[int]:
    values: list[int] = []
    player = game.players[player_index]
    for bidx in (0, 1):
        if not player.battalions[bidx].cards:
            continue
        if game.siege_assignments[player_index][bidx] is not None:
            continue
        values.append(bidx)
    return values


def battalion_attack_strength(cards: list[Card]) -> int:
    total = 0
    for card in cards:
        total += (card.might or 0) + card.temp_might_bonus
    return total


def battalion_total_strength(cards: list[Card]) -> int:
    total = 0
    for card in cards:
        total += (card.might or 0) + (card.will_ or 0) + card.temp_might_bonus + card.temp_will_bonus
    return total


def choose_profitable_standoff(game: Game, player_index: int, tier: str, rng: random.Random) -> int:
    if tier == BAD:
        return rng.choice([0, 1])
    return base.choose_profitable_standoff_top(game, player_index)


def choose_clairvoyance_discard(game: Game, player_index: int, tier: str) -> int | None:
    hand = game.players[player_index].hand
    if not hand:
        return None
    if tier == BAD:
        return max(range(len(hand)), key=lambda idx: base.card_power(hand[idx]))
    return min(range(len(hand)), key=lambda idx: (base.card_power(hand[idx]), hand[idx].card_type == "Unit"))


def choose_grave_pick(game: Game, player_index: int, tier: str) -> int | None:
    grave = game.players[player_index].grave
    unit_indices = [idx for idx, card in enumerate(grave) if card.card_type == "Unit"]
    if not unit_indices:
        return None
    if tier == BAD:
        return min(unit_indices, key=lambda idx: base.card_power(grave[idx]))
    return max(unit_indices, key=lambda idx: base.card_power(grave[idx]))


def choose_total_conquest_target(game: Game, player_index: int, tier: str) -> int | None:
    enemy_index = 1 - player_index
    units = game.players[enemy_index].barracks.units
    if not units:
        return None
    if tier == BAD:
        return min(range(len(units)), key=lambda idx: base.card_power(units[idx]))
    return max(range(len(units)), key=lambda idx: base.card_power(units[idx]))


def resolve_pending_prompts(game: Game, p1_ai: str, p2_ai: str, rng: random.Random) -> bool:
    progressed = False
    guard = 0
    while guard < 30:
        guard += 1
        if game.pending_profitable_standoff_draw_player is not None:
            owner = game.pending_profitable_standoff_draw_player
            tier = tier_for_player(p1_ai, p2_ai, owner)
            pick = choose_profitable_standoff(game, owner, tier, rng)
            ok, _ = game.choose_profitable_standoff_card(owner, pick)
            if ok:
                progressed = True
                continue
            return progressed

        if game.pending_clairvoyance_discard_player is not None:
            owner = game.pending_clairvoyance_discard_player
            tier = tier_for_player(p1_ai, p2_ai, owner)
            hand_idx = choose_clairvoyance_discard(game, owner, tier)
            if hand_idx is None:
                # Safety valve for impossible pending prompts (empty hand).
                game.pending_clairvoyance_discard_player = None
                progressed = True
                continue
            ok, _ = game.choose_clairvoyance_discard(owner, hand_idx)
            if ok:
                progressed = True
                continue
            return progressed

        if game.pending_total_conquest_pick_player is not None:
            owner = game.pending_total_conquest_pick_player
            tier = tier_for_player(p1_ai, p2_ai, owner)
            target = choose_total_conquest_target(game, owner, tier)
            if target is None:
                # Safety valve for impossible pending prompts (no enemy barracks unit).
                game.pending_total_conquest_pick_player = None
                progressed = True
                continue
            ok, _ = game.choose_total_conquest_target(owner, target)
            if ok:
                progressed = True
                continue
            return progressed

        if game.pending_grave_pick is not None:
            owner = int(game.pending_grave_pick["player"])
            tier = tier_for_player(p1_ai, p2_ai, owner)
            pick = choose_grave_pick(game, owner, tier)
            if pick is None:
                # Safety valve for impossible pending prompts (no Unit in grave).
                game.pending_grave_pick = None
                progressed = True
                continue
            ok, _ = game.choose_grave_card(owner, pick)
            if ok:
                progressed = True
                continue
            return progressed

        break
    return progressed

def attempt_play_random_non_unit(game: Game, player_index: int, rng: random.Random) -> bool:
    player = game.players[player_index]
    enemy_index = 1 - player_index
    enemy = game.players[enemy_index]

    hand_indices = [idx for idx, card in enumerate(player.hand) if card.card_type != "Unit"]
    rng.shuffle(hand_indices)
    for hand_idx in hand_indices:
        if hand_idx >= len(player.hand):
            continue
        card = player.hand[hand_idx]
        name = card.name
        attempts: list[dict[str, Any]] = []

        if name in ("Supply Cache", "Mass Benediction", "Rite of Ash"):
            attempts.append({})

        if name in ("Entrench", "Iron Discipline", "Reserve Rotation"):
            attempts.extend([{"battalion_index": 0}, {"battalion_index": 1}])

        if name == "Aegis Pulse":
            for bidx in (0, 1):
                battalion = player.battalions[bidx]
                for cidx, _ in enumerate(battalion.cards):
                    attempts.append(
                        {
                            "battalion_index": bidx,
                            "target_player_index": player_index,
                            "target_card_index": cidx,
                        }
                    )

        if name == "Sabotage Lines":
            for bidx in (0, 1):
                battalion = enemy.battalions[bidx]
                for cidx, unit in enumerate(battalion.cards):
                    if unit.effective_line() != "Front":
                        continue
                    attempts.append(
                        {
                            "battalion_index": bidx,
                            "target_player_index": enemy_index,
                            "target_card_index": cidx,
                        }
                    )

        if not attempts:
            attempts.append({})

        rng.shuffle(attempts)
        for params in attempts:
            ok, _ = game.play_non_unit_card(player_index, hand_idx, **params)
            if ok:
                return True
    return False


def attempt_bad_assign_hand_unit(game: Game, player_index: int, rng: random.Random) -> bool:
    player = game.players[player_index]
    candidates = [(idx, card) for idx, card in enumerate(player.hand) if card.card_type == "Unit"]
    if not candidates:
        return False
    candidates.sort(key=lambda pair: base.card_power(pair[1]))
    for idx, card in candidates:
        if rng.random() < 0.35:
            continue
        bchoices = [bidx for bidx in (0, 1) if player.battalions[bidx].has_room(card)]
        if not bchoices:
            continue
        battalion_index = rng.choice(bchoices)
        ok, _ = game.assign_hand_card_to_battalion(player_index, idx, battalion_index)
        if ok:
            return True
    return False


def attempt_bad_assign_barracks(game: Game, player_index: int, rng: random.Random) -> bool:
    player = game.players[player_index]
    if not player.barracks.units or rng.random() < 0.6:
        return False
    indices = list(range(len(player.barracks.units)))
    rng.shuffle(indices)
    for barracks_idx in indices:
        if barracks_idx >= len(player.barracks.units):
            continue
        card = player.barracks.units[barracks_idx]
        bchoices = [bidx for bidx in (0, 1) if player.battalions[bidx].has_room(card)]
        if not bchoices:
            continue
        battalion_index = rng.choice(bchoices)
        ok, _ = game.assign_barracks_unit_to_battalion(player_index, barracks_idx, battalion_index)
        if ok:
            return True
    return False


def take_draw_turn(game: Game, player_index: int, tier: str, rng: random.Random) -> None:
    if tier == BAD:
        if rng.random() < 0.20:
            game.use_total_conquest(player_index)
        if rng.random() < 0.25:
            game.use_clairvoyance(player_index)
        if rng.random() < 0.25:
            special = rng.choice(base.SPECIAL_RESOURCES)
            game.use_efficient_tithe(player_index, special)
        if rng.random() < 0.40:
            special = rng.choice(base.SPECIAL_RESOURCES)
            game.trade_rations_for_special(player_index, special)
        return

    if tier == MEDIOCRE:
        base.attempt_draw_actions(game, player_index)
        return

    # GOOD
    base.attempt_draw_actions(game, player_index)
    player = game.players[player_index]
    if player.resources.get("rations", 0) >= 8 and len(player.hand) < 7:
        needed = base.desired_special_resource(game, player_index)
        game.trade_rations_for_special(player_index, needed)


def take_preparations_turn(game: Game, player_index: int, tier: str, rng: random.Random) -> None:
    if tier == BAD:
        if rng.random() < 0.40:
            return
        for _ in range(4):
            action = rng.choice(["play", "assign_hand", "assign_barracks", "trade", "remove"])
            if action == "play":
                attempt_play_random_non_unit(game, player_index, rng)
            elif action == "assign_hand":
                attempt_bad_assign_hand_unit(game, player_index, rng)
            elif action == "assign_barracks":
                attempt_bad_assign_barracks(game, player_index, rng)
            elif action == "trade":
                special = rng.choice(base.SPECIAL_RESOURCES)
                game.trade_rations_for_special(player_index, special)
            else:
                bidx = rng.choice([0, 1])
                game.remove_battalion_card_to_hand(player_index, bidx, 0)
        return

    if tier == MEDIOCRE:
        base.attempt_preparation_actions(game, player_index)
        return

    # GOOD
    base.attempt_preparation_actions(game, player_index)
    guard = 0
    while guard < 30 and game.phase == "preparations" and game.current_player_index == player_index:
        guard += 1
        acted = False
        if base.attempt_assign_hand_unit(game, player_index):
            acted = True
        elif base.attempt_assign_barracks_unit(game, player_index):
            acted = True
        elif base.attempt_play_non_unit(game, player_index):
            acted = True
        elif base.maybe_trade_for_special(game, player_index):
            acted = True
        if not acted:
            break

def choose_battalion_for_tier(game: Game, player_index: int, tier: str) -> int | None:
    choices = undeployed_battalions(game, player_index)
    if not choices:
        return None

    player = game.players[player_index]
    if tier == BAD:
        return min(choices, key=lambda bidx: battalion_total_strength(player.battalions[bidx].cards))

    return max(choices, key=lambda bidx: battalion_total_strength(player.battalions[bidx].cards))


def assigned_enemy_strength(game: Game, attacker_index: int, target: int | str) -> int:
    defender_index = 1 - attacker_index
    enemy_cards = game._cards_assigned_to_target(defender_index, target)
    return battalion_attack_strength(enemy_cards)


def score_target_good(game: Game, player_index: int, battalion_index: int, target: int | str) -> float:
    opponent = 1 - player_index
    player = game.players[player_index]
    battalion_cards = player.battalions[battalion_index].cards
    our_strength = battalion_attack_strength(battalion_cards)
    enemy_strength = assigned_enemy_strength(game, player_index, target)

    if target == f"barracks:{opponent}":
        return 500.0 + our_strength * 2.0

    if target == f"barracks:{player_index}":
        # Avoid defensive stall unless it blocks a known incoming attack.
        base_score = -80.0
        incoming = assigned_enemy_strength(game, opponent, f"barracks:{player_index}")
        return base_score + incoming * 0.8

    if not isinstance(target, int):
        return -100.0

    slot = game.battlefield_gap[target]
    control = slot["controlled_by"]

    score = 0.0
    if control == opponent:
        score += 40.0
    elif control is None:
        score += 25.0
    else:
        score -= 12.0

    score += (our_strength - enemy_strength) * 1.2

    bfield = slot.get("card")
    if bfield is not None:
        name = bfield.name
        if name in ("Breach Point", "Scorched Wastes", "Silent Chasm"):
            score += 6.0
        if name in ("Arcane Nexus", "Ironheart Forges", "Grand Cathedral"):
            score += 4.0

    return score


def choose_target_for_tier(
    game: Game,
    player_index: int,
    battalion_index: int,
    tier: str,
    rng: random.Random,
) -> int | str | None:
    legal_targets = list(game._available_attack_targets(player_index))
    if not legal_targets:
        return None

    if tier == BAD:
        own_barracks = f"barracks:{player_index}"
        if own_barracks in legal_targets and rng.random() < 0.45:
            return own_barracks
        return rng.choice(legal_targets)

    if tier == MEDIOCRE:
        return max(legal_targets, key=lambda target: base.score_siege_target(game, player_index, target))

    # GOOD
    return max(legal_targets, key=lambda target: score_target_good(game, player_index, battalion_index, target))


def choose_first_deployer_for_tier(game: Game, chooser_index: int, tier: str, rng: random.Random) -> int:
    if tier == BAD:
        return rng.choice([0, 1])

    if tier == MEDIOCRE:
        return base.choose_first_deployer_target(game, chooser_index, rng)

    own_strength = sum(
        battalion_total_strength(b.cards)
        for b in game.players[chooser_index].battalions
        if b.cards
    )
    opp_index = 1 - chooser_index
    opp_strength = sum(
        battalion_total_strength(b.cards)
        for b in game.players[opp_index].battalions
        if b.cards
    )
    return chooser_index if own_strength >= opp_strength else opp_index


def run_siege_step(game: Game, p1_ai: str, p2_ai: str, rng: random.Random) -> None:
    if game.phase != "siege":
        return

    if game.pending_first_deployer_choice is not None:
        if game.pending_siege_roll is not None:
            loser = int(game.pending_siege_roll["loser"])
            loser_tier = tier_for_player(p1_ai, p2_ai, loser)
            if loser_tier == GOOD:
                game.use_calculated_deployment(loser)
            elif loser_tier == MEDIOCRE and rng.random() < 0.5:
                game.use_calculated_deployment(loser)

        chooser = game.pending_first_deployer_choice
        if chooser is None:
            return
        chooser_tier = tier_for_player(p1_ai, p2_ai, chooser)
        choice = choose_first_deployer_for_tier(game, chooser, chooser_tier, rng)
        game.choose_first_deployer(chooser, choice)
        return

    active = game.current_player_index
    if active not in (0, 1):
        return

    if game._all_nonempty_battalions_deployed():
        game.advance_phase()
        return

    tier = tier_for_player(p1_ai, p2_ai, active)

    battalion_index = choose_battalion_for_tier(game, active, tier)
    if battalion_index is None:
        other = 1 - active
        if game._has_undeployed_nonempty_battalion(other):
            game.current_player_index = other
        else:
            game.advance_phase()
        return

    if tier in (MEDIOCRE, GOOD):
        base.attempt_siege_boosts(game, active)

    target = choose_target_for_tier(game, active, battalion_index, tier, rng)
    if target is None:
        other = 1 - active
        if game._has_undeployed_nonempty_battalion(other):
            other_targets = list(game._available_attack_targets(other))
            if other_targets:
                game.current_player_index = other
                return
        game.advance_phase()
        return

    ok, _ = game.assign_battalion_to_slot(active, battalion_index, target)
    if ok:
        return

    # Fallback random if primary target became invalid.
    legal_targets = list(game._available_attack_targets(active))
    rng.shuffle(legal_targets)
    for fallback_target in legal_targets:
        ok, _ = game.assign_battalion_to_slot(active, battalion_index, fallback_target)
        if ok:
            return

    other = 1 - active
    if game._has_undeployed_nonempty_battalion(other):
        other_targets = list(game._available_attack_targets(other))
        if other_targets:
            game.current_player_index = other
            return
    game.advance_phase()


def simulate_tier_match(
    match_id: int,
    base_seed: int,
    max_turns: int,
    p1_ai: str,
    p2_ai: str,
    shared_loadout: base.PlayerLoadout,
) -> TierMatchRecord:
    seed = base_seed + match_id * 17
    rng = random.Random(seed + 900_000)

    p1_loadout = copy_loadout(shared_loadout)
    p2_loadout = copy_loadout(shared_loadout)
    game = base.make_game(p1_loadout, p2_loadout, setup_seed=seed)
    game.logs.clear()
    game.advance_phase()

    guard = 0
    guard_limit = max(200_000, max_turns * 300)
    while game.winner is None and game.turn <= max_turns and guard < guard_limit:
        guard += 1
        resolve_pending_prompts(game, p1_ai, p2_ai, rng)

        if game.winner is not None:
            break

        phase = game.phase
        active = game.current_player_index

        if phase == "replenish":
            game.advance_phase()
            continue

        if phase == "draw":
            if active in (0, 1):
                tier = tier_for_player(p1_ai, p2_ai, active)
                take_draw_turn(game, active, tier, rng)
                resolve_pending_prompts(game, p1_ai, p2_ai, rng)
                game.ready_current_player(active)
            else:
                game.advance_phase()
            continue

        if phase == "preparations":
            if active in (0, 1):
                tier = tier_for_player(p1_ai, p2_ai, active)
                take_preparations_turn(game, active, tier, rng)
                resolve_pending_prompts(game, p1_ai, p2_ai, rng)
                game.ready_current_player(active)
            else:
                game.advance_phase()
            continue

        if phase == "siege":
            run_siege_step(game, p1_ai, p2_ai, rng)
            continue

        if phase == "field_cleanup":
            game.advance_phase()
            continue

        game.advance_phase()

    if game.winner in (0, 1):
        termination = "winner_declared"
        declared_winner: int | None = game.winner
    elif game.turn > max_turns:
        termination = "turn_limit_draw"
        declared_winner = None
    else:
        termination = "loop_guard_draw"
        declared_winner = None

    return TierMatchRecord(
        match_id=match_id,
        matchup_label=f"{p1_ai}_vs_{p2_ai}",
        p1_ai=p1_ai,
        p2_ai=p2_ai,
        declared_winner=declared_winner,
        termination=termination,
        turns_completed=game.turn,
        loadout_deck=shared_loadout.deck,
        loadout_class=shared_loadout.class_name,
        loadout_barracks=shared_loadout.barracks,
        loadout_battlefields=", ".join(shared_loadout.battlefields),
        p1_score=base.analysis_score(game, 0),
        p2_score=base.analysis_score(game, 1),
    )


def summarize_matchup(records: list[TierMatchRecord], p1_ai: str, p2_ai: str) -> dict[str, Any]:
    games = len(records)
    p1_wins = sum(1 for record in records if record.declared_winner == 0)
    p2_wins = sum(1 for record in records if record.declared_winner == 1)
    draws = sum(1 for record in records if record.declared_winner is None)
    non_draw = games - draws

    p1_decisive = base.safe_rate(p1_wins, non_draw)
    p2_decisive = base.safe_rate(p2_wins, non_draw)

    p1_point_rate = (p1_wins + 0.5 * draws) / games if games > 0 else 0.0
    p2_point_rate = (p2_wins + 0.5 * draws) / games if games > 0 else 0.0

    avg_turns = statistics.mean(record.turns_completed for record in records) if records else 0.0

    return {
        "matchup": f"{p1_ai} vs {p2_ai}",
        "p1_ai": p1_ai,
        "p2_ai": p2_ai,
        "games": games,
        "p1_wins": p1_wins,
        "p2_wins": p2_wins,
        "draws": draws,
        "non_draw_games": non_draw,
        "p1_decisive_win_rate_pct": base.percent(p1_decisive),
        "p2_decisive_win_rate_pct": base.percent(p2_decisive),
        "p1_point_rate_pct": base.percent(p1_point_rate),
        "p2_point_rate_pct": base.percent(p2_point_rate),
        "draw_rate_pct": base.percent(draws / games) if games > 0 else 0.0,
        "avg_turns": round(avg_turns, 2),
    }


def summarize_by_ai(records: list[TierMatchRecord]) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, float]] = {
        BAD: {"appearances": 0, "wins": 0, "losses": 0, "draws": 0},
        MEDIOCRE: {"appearances": 0, "wins": 0, "losses": 0, "draws": 0},
        GOOD: {"appearances": 0, "wins": 0, "losses": 0, "draws": 0},
    }

    for record in records:
        # Player 1 entry.
        stats[record.p1_ai]["appearances"] += 1
        stats[record.p2_ai]["appearances"] += 1

        if record.declared_winner is None:
            stats[record.p1_ai]["draws"] += 1
            stats[record.p2_ai]["draws"] += 1
        elif record.declared_winner == 0:
            stats[record.p1_ai]["wins"] += 1
            stats[record.p2_ai]["losses"] += 1
        else:
            stats[record.p1_ai]["losses"] += 1
            stats[record.p2_ai]["wins"] += 1

    rows: list[dict[str, Any]] = []
    for ai_name in (BAD, MEDIOCRE, GOOD):
        entry = stats[ai_name]
        appearances = int(entry["appearances"])
        wins = int(entry["wins"])
        losses = int(entry["losses"])
        draws = int(entry["draws"])
        non_draw = wins + losses
        decisive = wins / non_draw if non_draw > 0 else 0.0
        point_rate = (wins + 0.5 * draws) / appearances if appearances > 0 else 0.0

        rows.append(
            {
                "ai": ai_name,
                "appearances": appearances,
                "wins": wins,
                "losses": losses,
                "draws": draws,
                "non_draw_games": non_draw,
                "decisive_win_rate_pct": base.percent(decisive),
                "point_rate_pct": base.percent(point_rate),
            }
        )

    rows.sort(key=lambda row: row["point_rate_pct"], reverse=True)
    return rows


def records_to_raw_rows(records: list[TierMatchRecord]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        rows.append(
            {
                "match_id": record.match_id,
                "matchup": record.matchup_label,
                "p1_ai": record.p1_ai,
                "p2_ai": record.p2_ai,
                "winner_label": (
                    "Player 1"
                    if record.declared_winner == 0
                    else ("Player 2" if record.declared_winner == 1 else "Draw")
                ),
                "winner_index": "" if record.declared_winner is None else record.declared_winner,
                "termination": record.termination,
                "turns_completed": record.turns_completed,
                "loadout_deck": record.loadout_deck,
                "loadout_class": record.loadout_class,
                "loadout_barracks": record.loadout_barracks,
                "loadout_battlefields": record.loadout_battlefields,
                "p1_final_score": record.p1_score,
                "p2_final_score": record.p2_score,
            }
        )
    return rows


def run_matchups(games_per_matchup: int, seed: int, max_turns: int) -> tuple[list[TierMatchRecord], list[dict[str, Any]]]:
    rng = random.Random(seed)
    all_records: list[TierMatchRecord] = []
    matchup_summaries: list[dict[str, Any]] = []

    for matchup_index, (p1_ai, p2_ai) in enumerate(MATCHUPS):
        matchup_records: list[TierMatchRecord] = []
        print(f"Running {p1_ai} vs {p2_ai}...")

        for local_id in range(1, games_per_matchup + 1):
            global_match_id = matchup_index * games_per_matchup + local_id
            shared_loadout = base.create_loadout(rng)
            record = simulate_tier_match(
                match_id=global_match_id,
                base_seed=seed,
                max_turns=max_turns,
                p1_ai=p1_ai,
                p2_ai=p2_ai,
                shared_loadout=shared_loadout,
            )
            matchup_records.append(record)
            all_records.append(record)

            if local_id % 50 == 0 or local_id == games_per_matchup:
                print(f"  {local_id}/{games_per_matchup}")

        matchup_summaries.append(summarize_matchup(matchup_records, p1_ai, p2_ai))

    return all_records, matchup_summaries


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bad/mediocre/good AI tier matchup simulations.")
    parser.add_argument("--games-per-matchup", type=int, default=250, help="Games to simulate for each listed matchup.")
    parser.add_argument("--seed", type=int, default=348, help="Base random seed.")
    parser.add_argument(
        "--max-turns",
        type=int,
        default=2000,
        help="Turn cap before recording a draw (no overtime force logic).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "reports" / "ai_tier_matchups",
        help="Output directory for workbook and CSV files.",
    )
    args = parser.parse_args()

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    records, matchup_summary = run_matchups(
        games_per_matchup=args.games_per_matchup,
        seed=args.seed,
        max_turns=args.max_turns,
    )

    ai_summary = summarize_by_ai(records)
    raw_rows = records_to_raw_rows(records)

    matchup_fields = [
        "matchup",
        "p1_ai",
        "p2_ai",
        "games",
        "p1_wins",
        "p2_wins",
        "draws",
        "non_draw_games",
        "p1_decisive_win_rate_pct",
        "p2_decisive_win_rate_pct",
        "p1_point_rate_pct",
        "p2_point_rate_pct",
        "draw_rate_pct",
        "avg_turns",
    ]
    ai_fields = [
        "ai",
        "appearances",
        "wins",
        "losses",
        "draws",
        "non_draw_games",
        "decisive_win_rate_pct",
        "point_rate_pct",
    ]
    raw_fields = [
        "match_id",
        "matchup",
        "p1_ai",
        "p2_ai",
        "winner_label",
        "winner_index",
        "termination",
        "turns_completed",
        "loadout_deck",
        "loadout_class",
        "loadout_barracks",
        "loadout_battlefields",
        "p1_final_score",
        "p2_final_score",
    ]

    base.write_csv(output_dir / "ai_tier_matchup_summary.csv", matchup_summary, matchup_fields)
    base.write_csv(output_dir / "ai_tier_overall_strength.csv", ai_summary, ai_fields)
    base.write_csv(output_dir / "ai_tier_raw_matches.csv", raw_rows, raw_fields)

    workbook_path = output_dir / "ai_tier_matchups.xlsx"
    sheets = [
        ("MatchupSummary", base.table_rows_from_dicts(matchup_summary, matchup_fields)),
        ("OverallStrength", base.table_rows_from_dicts(ai_summary, ai_fields)),
        ("RawMatches", base.table_rows_from_dicts(raw_rows, raw_fields)),
    ]
    base.write_xlsx(workbook_path, sheets)

    print()
    print("Generated files:")
    print(f"- {output_dir / 'ai_tier_matchups.xlsx'}")
    print(f"- {output_dir / 'ai_tier_matchup_summary.csv'}")
    print(f"- {output_dir / 'ai_tier_overall_strength.csv'}")
    print(f"- {output_dir / 'ai_tier_raw_matches.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
