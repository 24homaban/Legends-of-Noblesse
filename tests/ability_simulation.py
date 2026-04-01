from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from game.card_loader import all_battlefield_names, create_card
from game.game import Game


DATA_CARDS_DIR = PROJECT_ROOT / "data" / "Cards"


@dataclass
class Scenario:
    name: str
    run: Callable[[], None]
    labels: set[str]


def make_game(
    class_0: str = "Arch-Hierarch",
    class_1: str = "Ash Chancellor",
    barracks_0: str = "High Command Spire",
    barracks_1: str = "High Command Spire",
) -> Game:
    setup_data = {
        "players": [
            {
                "deck": "Inspiring Defenders",
                "class": class_0,
                "barracks": barracks_0,
                "battlefields": ["Arcane Nexus", "Hall of Mirrors", "Ironheart Forges"],
            },
            {
                "deck": "Inspiring Defenders",
                "class": class_1,
                "barracks": barracks_1,
                "battlefields": ["Grand Cathedral", "Breach Point", "Silent Chasm"],
            },
        ],
        "placements": [
            {"slot": 0, "battlefield": {"name": "Arcane Nexus"}},
            {"slot": 1, "battlefield": {"name": "Hall of Mirrors"}},
            {"slot": 2, "battlefield": {"name": "Ironheart Forges"}},
            {"slot": 3, "battlefield": {"name": "Grand Cathedral"}},
            {"slot": 4, "battlefield": {"name": "Breach Point"}},
            {"slot": 5, "battlefield": {"name": "Silent Chasm"}},
        ],
    }
    g = Game(setup_data)
    g.logs.clear()
    return g


def set_action(g: Game, phase: str, active: int = 0) -> None:
    g.phase = phase
    g.current_player_index = active
    g.pending_grave_pick = None
    g.pending_first_deployer_choice = None
    g.pending_clairvoyance_discard_player = None
    g.pending_profitable_standoff_draw_player = None


def set_control(g: Game, slot: int, owner: int | None, name: str) -> None:
    g.battlefield_gap[slot]["card"] = create_card(name, owner_index=None, revealed=True)
    g.battlefield_gap[slot]["controlled_by"] = owner


def max_resources(g: Game, pidx: int) -> None:
    p = g.players[pidx]
    for key, value in {
        "rations": 10,
        "ore": 5,
        "materia": 5,
        "magium": 5,
        "faith": 5,
        "sacrifice": 5,
    }.items():
        p.resources[key] = value


def martyr_square_name() -> str:
    return next(name for name in all_battlefield_names() if "Martyr" in name)


def _ok(result: tuple[bool, str]) -> None:
    ok, msg = result
    assert ok, msg


def scenario_tactics() -> None:
    # Aegis Pulse
    g = make_game()
    set_action(g, "preparations", 0)
    p0 = g.players[0]
    max_resources(g, 0)
    unit = create_card("Conscripted Militia", owner_index=0, revealed=True)
    p0.battalions[0].cards = [unit]
    p0.hand = [create_card("Aegis Pulse", owner_index=0, revealed=True)]
    _ok(g.play_non_unit_card(0, 0, battalion_index=0, target_player_index=0, target_card_index=0))
    assert unit.temp_will_bonus == 2

    # Entrench
    g = make_game()
    set_action(g, "preparations", 0)
    p0 = g.players[0]
    max_resources(g, 0)
    a = create_card("Conscripted Militia", owner_index=0, revealed=True)
    b = create_card("Shield Initiate", owner_index=0, revealed=True)
    c = create_card("Hollowed Sentry", owner_index=0, revealed=True)
    p0.battalions[0].cards = [a, b, c]
    p0.hand = [create_card("Entrench", owner_index=0, revealed=True)]
    _ok(g.play_non_unit_card(0, 0, battalion_index=0))
    assert (a.temp_will_bonus, b.temp_will_bonus, c.temp_will_bonus) == (1, 1, 0)

    # Iron Discipline + follow-up assignment discount
    g = make_game()
    set_action(g, "preparations", 0)
    p0 = g.players[0]
    max_resources(g, 0)
    p0.resources["rations"] = 5
    p0.hand = [
        create_card("Iron Discipline", owner_index=0, revealed=True),
        create_card("Conscripted Militia", owner_index=0, revealed=False),
    ]
    _ok(g.play_non_unit_card(0, 0, battalion_index=0))
    _ok(g.assign_hand_card_to_battalion(0, 0, 0))
    assert p0.resources["rations"] == 4

    # Mass Benediction
    g = make_game()
    set_action(g, "preparations", 0)
    p0 = g.players[0]
    max_resources(g, 0)
    back = create_card("Camp Scout", owner_index=0, revealed=True)
    front = create_card("Conscripted Militia", owner_index=0, revealed=True)
    p0.battalions[0].cards = [back, front]
    p0.hand = [create_card("Mass Benediction", owner_index=0, revealed=True)]
    _ok(g.play_non_unit_card(0, 0))
    assert (back.temp_will_bonus, front.temp_will_bonus) == (1, 0)

    # Reserve Rotation
    g = make_game()
    set_action(g, "preparations", 0)
    p0 = g.players[0]
    max_resources(g, 0)
    p0.battalions[0].cards = [create_card("Conscripted Militia", owner_index=0, revealed=False)]
    p0.hand = [
        create_card("Reserve Rotation", owner_index=0, revealed=True),
        create_card("Camp Scout", owner_index=0, revealed=False),
    ]
    _ok(g.play_non_unit_card(0, 0, battalion_index=0))
    assert p0.battalions[0].cards[0].name == "Camp Scout"
    assert any(card.name == "Conscripted Militia" for card in p0.hand)

    # Rite of Ash
    g = make_game()
    set_action(g, "preparations", 0)
    p0 = g.players[0]
    max_resources(g, 0)
    p0.hand = [create_card("Rite of Ash", owner_index=0, revealed=True)]
    p0.grave = [create_card("Conscripted Militia", owner_index=0, revealed=True)]
    _ok(g.play_non_unit_card(0, 0))
    _ok(g.choose_grave_card(0, 0))
    assert any(card.name == "Conscripted Militia" for card in p0.hand)

    # Sabotage Lines
    g = make_game()
    set_action(g, "preparations", 0)
    p0 = g.players[0]
    p1 = g.players[1]
    max_resources(g, 0)
    p0.hand = [create_card("Sabotage Lines", owner_index=0, revealed=True)]
    target = create_card("Conscripted Militia", owner_index=1, revealed=True)
    p1.battalions[0].cards = [target]
    _ok(g.play_non_unit_card(0, 0, battalion_index=0, target_player_index=1, target_card_index=0))
    assert target.temp_might_bonus == -1

    # Supply Cache
    g = make_game()
    set_action(g, "preparations", 0)
    p0 = g.players[0]
    max_resources(g, 0)
    p0.resources["rations"] = 1
    p0.hand = [create_card("Supply Cache", owner_index=0, revealed=True)]
    _ok(g.play_non_unit_card(0, 0))
    g._do_replenish_phase()
    g._do_replenish_phase()
    assert p0.resources["rations"] >= 8


def scenario_units() -> None:
    g = make_game()
    p0 = g.players[0]
    # Supply Runner
    set_action(g, "preparations", 0)
    max_resources(g, 0)
    p0.hand = [create_card("Supply Runner", owner_index=0, revealed=False)]
    before_pending = p0.resources["pending_rations"]
    _ok(g.assign_hand_card_to_battalion(0, 0, 0))
    assert p0.resources["pending_rations"] == before_pending + 1
    # Forged Dreadnought
    g = make_game()
    set_action(g, "preparations", 0)
    p0 = g.players[0]
    max_resources(g, 0)
    p0.resources["ore"] = 2
    p0.hand = [create_card("Forged Dreadnought", owner_index=0, revealed=False)]
    _ok(g.assign_hand_card_to_battalion(0, 0, 0))
    d = p0.battalions[0].cards[0]
    assert p0.resources["ore"] == 0 and d.temp_might_bonus == 2 and d.temp_will_bonus == -2
    # Shield Initiate
    shield = create_card("Shield Initiate", owner_index=0, revealed=True)
    dead, survivors, _ = g._apply_damage_pipeline(4, [shield], {shield: {"might": 0, "will": 0}})
    assert not dead and survivors == [shield] and shield.shield_used_this_siege
    # Pikeline Recruit
    pike = create_card("Pikeline Recruit", owner_index=0, revealed=True)
    g._mark_pikeline_survivors([pike])
    assert pike.temp_will_bonus == 1
    # Occultic Blood-Mage
    blood_mage = create_card("Occultic Blood-Mage", owner_index=0, revealed=True)
    enemy_survivors = [create_card("Camp Scout", owner_index=1, revealed=True)]
    enemy_dead: list = []
    g._resolve_bloodmage_pulses(0, [blood_mage], [create_card("Conscripted Militia", owner_index=0, revealed=True)], enemy_survivors, enemy_dead, {})
    assert len(enemy_dead) == 1
    # Slag-Brute + Standard-Bearer + Phalanx + Sentry + Mind-Bender + Bombardier + Camp Scout + Militia
    front = create_card("Conscripted Militia", owner_index=1, revealed=True)
    might_before = front.might
    g._resolve_slag_brute_debuffs([create_card("Volatile Slag-Brute", owner_index=0, revealed=True)], [front])
    assert front.might == might_before - 1
    own_front = create_card("Conscripted Militia", owner_index=0, revealed=True)
    standard = create_card("Zealous Standard-Bearer", owner_index=0, revealed=True)
    mods = g._compute_modifiers_for_battalion(0, [own_front, standard], slot_index=None)
    assert mods[own_front]["might"] >= 1 and mods[own_front]["will"] >= 1
    phalanx = create_card("Ironclad Phalanx", owner_index=0, revealed=True)
    mods = g._compute_modifiers_for_battalion(0, [phalanx, create_card("Camp Scout", owner_index=0, revealed=True)], slot_index=None)
    assert mods[phalanx]["will"] >= 2
    set_control(g, 0, 0, "Arcane Nexus")
    sentry = create_card("Hollowed Sentry", owner_index=0, revealed=True)
    mods = g._compute_modifiers_for_battalion(0, [sentry], slot_index=0)
    assert mods[sentry]["will"] >= 2
    enemy_front = create_card("Conscripted Militia", owner_index=1, revealed=True)
    enemy_back = create_card("Camp Scout", owner_index=1, revealed=True)
    g._apply_spire_swaps([create_card("Spire Mind-Bender", owner_index=0, revealed=True)], [enemy_front, enemy_back])
    assert enemy_front.temp_line_override == "Back" and enemy_back.temp_line_override == "Front"
    hand_before = len(g.players[0].hand)
    g._apply_overflow_rewards(0, [create_card("Arcane Bombardier", owner_index=0, revealed=True)], True, slot_index=0)
    assert len(g.players[0].hand) == hand_before + 1
    g.players[0].resources["rations"] = 0
    g.players[0].battalions[0].cards = [create_card("Camp Scout", owner_index=0, revealed=True)]
    g._field_cleanup()
    assert g.players[0].resources["rations"] == 1
    before_pending = g.players[0].resources["pending_rations"]
    g._handle_felled_cards(0, [create_card("Conscripted Militia", owner_index=0, revealed=True)], slot_index=None)
    assert g.players[0].resources["pending_rations"] == before_pending + 1


def scenario_barracks_battlefields() -> None:
    # Barracks
    g = make_game(barracks_0="High Command Spire")
    g.players[0].resources["rations"] = 0
    g._do_replenish_phase()
    assert g.players[0].resources["rations"] >= 4
    g = make_game(barracks_0="Quartermaster's Bastion")
    g.players[0].resources["rations"] = -1
    g._do_replenish_phase()
    assert g.players[0].resources["rations"] >= 3
    g = make_game(barracks_0="Ossuary Keep")
    set_action(g, "preparations", 0)
    max_resources(g, 0)
    g.players[0].hand = []
    g.players[0].grave = [create_card("Conscripted Militia", owner_index=0, revealed=True)]
    _ok(g.use_ossuary_keep(0))
    _ok(g.choose_grave_card(0, 0))
    _ok(g.assign_hand_card_to_battalion(0, 0, 0))
    assert g.players[0].battalions[0].cards[0].revealed
    g = make_game(barracks_0="Sanctum of the Fallen")
    g.players[0].deck = [create_card("Camp Scout", owner_index=0, revealed=False)]
    hand_before = len(g.players[0].hand)
    g._handle_felled_cards(0, [create_card("Conscripted Militia", owner_index=0, revealed=True)], slot_index=3)
    assert len(g.players[0].hand) == hand_before + 1
    g = make_game()
    p0 = g.players[0]
    p0.deck = []
    recycle_a = create_card("Conscripted Militia", owner_index=0, revealed=True)
    recycle_a.temp_might_bonus = 3
    recycle_a.from_barracks = True
    recycle_b = create_card("Camp Scout", owner_index=0, revealed=True)
    p0.grave = [recycle_a, recycle_b]
    hand_before = len(p0.hand)
    drawn = p0.draw_card(1)
    assert drawn == 1
    assert len(p0.hand) == hand_before + 1 and len(p0.deck) == 1 and len(p0.grave) == 0
    recycled = p0.hand[-1]
    assert not recycled.revealed and not recycled.from_barracks
    assert recycled.temp_might_bonus == 0 and recycled.temp_will_bonus == 0
    g = make_game()
    g.profitable_standoff_charges[0] = 1
    g.players[0].deck = []
    g.players[0].grave = [
        create_card("Conscripted Militia", owner_index=0, revealed=True),
        create_card("Camp Scout", owner_index=0, revealed=True),
    ]
    g._start_draw_phase()
    assert g.pending_profitable_standoff_draw_player == 0 and len(g.players[0].grave) == 0
    _ok(g.choose_profitable_standoff_card(0, 1))
    standoff_drawn = g.players[0].hand[-1]
    assert not standoff_drawn.revealed and not standoff_drawn.from_barracks
    g = make_game(barracks_0="War-Wrought Citadel")
    set_action(g, "preparations", 0)
    max_resources(g, 0)
    g.players[0].resources["rations"] = 1
    g.players[0].hand = [create_card("Conscripted Militia", owner_index=0, revealed=False)]
    _ok(g.assign_hand_card_to_battalion(0, 0, 0))
    placed = g.players[0].battalions[0].cards[0]
    assert (not placed.revealed) and g.players[0].resources["rations"] == 1
    # Battlefields
    g = make_game()
    set_control(g, 0, 0, "Arcane Nexus")
    g.players[0].resources["magium"] = 0
    g._do_replenish_phase()
    assert g.players[0].resources["magium"] >= 1
    set_action(g, "draw", 0)
    g.players[0].deck = [create_card("Camp Scout", owner_index=0, revealed=False)]
    g.players[0].resources["magium"] = 1
    _ok(g.use_clairvoyance(0))
    _ok(g.choose_clairvoyance_discard(0, 0))
    set_control(g, 0, 0, "Bloodletting Altar")
    g.players[0].resources["sacrifice"] = 0
    g._handle_felled_cards(0, [create_card("Conscripted Militia", owner_index=0, revealed=True)], slot_index=0)
    assert g.players[0].resources["sacrifice"] >= 1
    set_control(g, 0, 0, "Breach Point")
    front = create_card("Conscripted Militia", owner_index=0, revealed=True)
    assert g._compute_modifiers_for_battalion(0, [front], slot_index=1)[front]["might"] >= 1
    set_control(g, 0, 0, "Grand Cathedral")
    back = create_card("Camp Scout", owner_index=0, revealed=True)
    assert g._compute_modifiers_for_battalion(0, [back], slot_index=0)[back]["will"] >= 1
    set_control(g, 0, 0, "Hall of Mirrors")
    set_action(g, "draw", 0)
    g.players[0].deck = [create_card("Camp Scout", owner_index=0, revealed=False)]
    g.players[0].resources["magium"] = 0
    _ok(g.ready_current_player(0))
    _ok(g.ready_current_player(1))
    assert g.phase == "preparations" and g.players[0].resources["magium"] >= 1
    set_control(g, 0, 0, "Ironheart Forges")
    g.players[0].resources["ore"] = 0
    g._do_replenish_phase()
    assert g.players[0].resources["ore"] >= 1
    set_action(g, "preparations", 0)
    g.players[0].battalions[0].cards = [create_card("Conscripted Militia", owner_index=0, revealed=True)]
    _ok(g.use_ironheart_forges_boost(0, 0, 0))
    set_control(g, 0, 0, martyr_square_name())
    max_resources(g, 0)
    g.players[0].resources["rations"] = 1
    g.players[0].hand = [create_card("Conscripted Militia", owner_index=0, revealed=False)]
    _ok(g.assign_hand_card_to_battalion(0, 0, 0))
    assert not g.players[0].battalions[0].cards[-1].revealed
    set_control(g, 0, 0, "Scorched Wastes")
    g.players[0].resources["rations"] = 0
    g._apply_overflow_rewards(0, [create_card("Conscripted Militia", owner_index=0, revealed=True)], True, slot_index=0)
    assert g.players[0].resources["rations"] >= 1
    g._handle_silent_chasm_profitable_standoff(0)
    g.players[0].deck = [
        create_card("Conscripted Militia", owner_index=0, revealed=False),
        create_card("Camp Scout", owner_index=0, revealed=False),
    ]
    g._start_draw_phase()
    _ok(g.choose_profitable_standoff_card(0, 1))


def scenario_classes() -> None:
    # Arch-Hierarch
    g = make_game(class_0="Arch-Hierarch")
    set_action(g, "draw", 0)
    g.players[0].xp = 1
    g.players[0].resources["rations"] = 2
    g.players[0].resources["ore"] = 0
    _ok(g.use_efficient_tithe(0, "ore"))
    # Divine Insight now triggers on successful non-unit activation in preparations.
    set_action(g, "preparations", 0)
    max_resources(g, 0)
    g.players[0].battalions[0].cards = [create_card("Conscripted Militia", owner_index=0, revealed=True)]
    g.players[0].hand = [create_card("Aegis Pulse", owner_index=0, revealed=True)]
    xp_before = g.players[0].xp
    _ok(g.play_non_unit_card(0, 0, battalion_index=0, target_player_index=0, target_card_index=0))
    assert g.players[0].xp == xp_before + 1
    g.players[0].xp = 3
    g.phase = "siege"
    unit = create_card("Conscripted Militia", owner_index=0, revealed=True)
    g.players[0].battalions[0].cards = [unit]
    xp_before = g.players[0].xp
    g._on_non_unit_activated(0)
    assert g.players[0].xp == xp_before + 1 and unit.temp_will_bonus == 1
    set_action(g, "preparations", 0)
    g.players[0].xp = 6
    max_resources(g, 0)
    g.players[0].grave = [create_card("Conscripted Militia", owner_index=0, revealed=True)]
    _ok(g.start_miracle_of_faith(0, 0))
    _ok(g.choose_grave_card(0, 0))
    # Siege non-unit integration guard (currently blocked)
    set_action(g, "siege", 0)
    g.players[0].hand = [create_card("Aegis Pulse", owner_index=0, revealed=True)]
    ok, _ = g.play_non_unit_card(0, 0, battalion_index=0)
    assert not ok
    # Ash Chancellor
    g = make_game(class_0="Ash Chancellor")
    g.players[0].xp = 3
    max_resources(g, 0)
    set_action(g, "preparations", 0)
    g.players[0].grave = [create_card("Conscripted Militia", owner_index=0, revealed=True)]
    _ok(g.start_ashen_recall(0))
    _ok(g.choose_grave_card(0, 0))
    set_action(g, "siege", 0)
    g.players[0].xp = 6
    g.players[0].resources["sacrifice"] = 2
    front = create_card("Conscripted Militia", owner_index=0, revealed=True)
    g.players[0].battalions[0].cards = [front]
    _ok(g.use_pyre_decree(0))
    assert front.temp_might_bonus >= 2
    xp_before = g.players[0].xp
    g._handle_felled_cards(0, [create_card("Conscripted Militia", owner_index=0, revealed=True)], slot_index=0)
    assert g.players[0].xp == xp_before + 1
    # Grand Strategist
    g = make_game(class_0="Grand Strategist")
    set_action(g, "preparations", 0)
    g.players[0].xp = 1
    g.players[0].battalions[0].cards = [create_card("Conscripted Militia", owner_index=0, revealed=False)]
    g.players[0].hand = [create_card("Camp Scout", owner_index=0, revealed=True)]
    _ok(g.use_tactical_bluff(0))
    set_action(g, "siege", 0)
    g.players[0].xp = 3
    g.pending_siege_roll = {"p1": 1, "p2": 6, "winner": 1, "loser": 0}
    g.pending_first_deployer_choice = 1
    _ok(g.use_calculated_deployment(0))
    set_action(g, "siege", 0)
    g.players[0].xp = 6
    g.siege_assignments[0] = [0, 1]
    _ok(g.use_tactical_gambit(0))
    hold_before = g.players[0].xp
    g._grant_grand_strategist_xp(0, had_units_in_fight=True, result_controller=0)
    assert g.players[0].xp == hold_before + 1
    # Storm Warden
    g = make_game(class_0="Storm Warden")
    g.players[0].xp = 6
    front = create_card("Conscripted Militia", owner_index=0, revealed=True)
    assert g._compute_modifiers_for_battalion(0, [front], slot_index=None)[front]["might"] >= 1
    static_before = g.players[0].xp
    g.players[0].resources["magium"] = 0
    g._apply_overflow_rewards(0, [front], True, slot_index=0)
    assert g.players[0].xp == static_before + 1 and g.players[0].resources["magium"] >= 1
    set_action(g, "siege", 0)
    g.players[0].resources["magium"] = 1
    g.players[0].battalions[0].cards = [front]
    _ok(g.use_eye_of_storm(0, battalion_index=0, card_index=0))
    # Vanguard
    g = make_game(class_0="Vanguard")
    g.players[0].xp = 6
    set_control(g, 0, 1, "Arcane Nexus")
    front = create_card("Conscripted Militia", owner_index=0, revealed=True)
    back = create_card("Camp Scout", owner_index=0, revealed=True)
    mods = g._compute_modifiers_for_battalion(0, [front, back], slot_index=0)
    assert mods[front]["might"] >= 1 and mods[back]["might"] == back.temp_might_bonus
    set_control(g, 0, 0, "Arcane Nexus")
    own_mods = g._compute_modifiers_for_battalion(0, [front], slot_index=0)
    assert own_mods[front]["might"] == front.temp_might_bonus
    rank_before = g.players[0].xp
    g._apply_overflow_rewards(0, [front], True, slot_index=0)
    assert g.players[0].xp == rank_before + 1
    set_action(g, "siege", 0)
    g.players[0].resources["ore"] = 1
    g.players[0].battalions[0].cards = [front]
    _ok(g.use_relentless_push(0, battalion_index=0, card_index=0, pay_resource="ore"))
    g.players[1].barracks.units = [create_card("Camp Scout", owner_index=1, revealed=True)]
    g._handle_total_conquest(0)
    assert g.players[0].resources["total_conquest_ready"] == 1
    set_action(g, "draw", 0)
    _ok(g.use_total_conquest(0))
    _ok(g.choose_total_conquest_target(0, 0))
    assert g.players[0].resources["total_conquest_used"] == 1


def declared_labels() -> set[str]:
    labels: set[str] = set()
    for path in DATA_CARDS_DIR.rglob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        ability = payload.get("ability")
        if isinstance(ability, str) and ability.strip():
            labels.add(ability.strip())
        xp = payload.get("xp")
        if isinstance(xp, str) and xp.strip():
            labels.add(xp.strip())
        for level in payload.get("levels", []):
            if isinstance(level, dict):
                lname = level.get("name")
                if isinstance(lname, str) and lname.strip():
                    labels.add(lname.strip())
    return labels


KNOWN_GAPS: set[str] = set()


def main() -> int:
    scenarios = [
        Scenario(
            "Tactics",
            scenario_tactics,
            {
                "Arcane Bulwark",
                "Fortification",
                "Coordinated Orders",
                "Sanctified Chorus",
                "Line Shift",
                "Funerary Recall",
                "Disruptive Strike",
                "Delayed Provisions",
            },
        ),
        Scenario(
            "Units",
            scenario_units,
            {
                "Field Provision",
                "Reckless Swing",
                "Brace",
                "Hold Rank",
                "Siphon Life",
                "Corrosive Splatter",
                "Rallying Cry",
                "Shield Wall",
                "Spectral Guard",
                "Confusion",
                "Devastating Payload",
                "Foraging Intel",
                "Expendable",
                "Strategic Role",
            },
        ),
        Scenario(
            "Barracks+Battlefields",
            scenario_barracks_battlefields,
            {
                "Supply Command",
                "Crypt Reserves",
                "Emergency Provisioning",
                "Desperate Defense",
                "Rapid Mobilization",
                "Clairvoyance",
                "Macabre Harvest",
                "Momentum",
                "Divine Bulwark",
                "Mirrored Supply",
                "Tempered Steel",
                "Zealous Decree",
                "Spoils of War",
                "Profitable Standoff",
            },
        ),
        Scenario(
            "Classes",
            scenario_classes,
            {
                "Divine Insight",
                "Efficient Tithe",
                "Holy Aegis",
                "Miracle of Faith",
                "Ledger of Cinders",
                "Cinder Tithe",
                "Ashen Recall",
                "Pyre Decree",
                "Hold The Line",
                "Tactical Bluff",
                "Calculated Deployment",
                "Tactical Gambit",
                "Tempest Pressure",
                "Stormline Drill",
                "Static Surge",
                "Eye of the Storm",
                "Shatter The Ranks",
                "Marching Orders",
                "Relentless Push",
                "Total Conquest",
            },
        ),
    ]

    covered: set[str] = set()
    failures: list[tuple[str, str]] = []
    for s in scenarios:
        try:
            s.run()
            covered.update(s.labels)
            print(f"[PASS] {s.name}")
        except AssertionError as exc:
            failures.append((s.name, str(exc)))
            print(f"[FAIL] {s.name}: {exc}")
        except Exception as exc:  # pragma: no cover
            failures.append((s.name, f"{type(exc).__name__}: {exc}"))
            print(f"[FAIL] {s.name}: {type(exc).__name__}: {exc}")

    declared = declared_labels()
    uncovered = sorted(declared - covered - KNOWN_GAPS)
    known = sorted(declared & KNOWN_GAPS)

    print()
    print(f"Scenario pass count: {len(scenarios) - len(failures)}/{len(scenarios)}")
    print(f"Declared ability labels: {len(declared)}")
    print(f"Covered labels: {len(covered)}")
    if failures:
        print("Scenario failures:")
        for name, reason in failures:
            print(f"- {name}: {reason}")
    if known:
        print("Known gaps:")
        for name in known:
            print(f"- {name}")
    if uncovered:
        print("Uncovered labels:")
        for name in uncovered:
            print(f"- {name}")

    if failures or uncovered:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
