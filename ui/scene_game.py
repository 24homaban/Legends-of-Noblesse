from __future__ import annotations

import math
from typing import Callable

import pygame

from adapters import GameAdapter
from game.game import Game
from .constants import (
    ACCENT,
    INFO,
    INVALID_TARGET,
    LEGAL_TARGET,
    MUTED,
    P1_COLOR,
    P2_COLOR,
    PANEL,
    PANEL_ALT,
    TEXT,
)
from .primitives import Button
from .renderers import (
    draw_board_background,
    draw_panel,
    draw_tcg_card,
    draw_text,
    fit_card_rect,
    truncate_text,
    wrap_text,
)
from .scene_base import SceneBase
from .tutorial import TutorialCard, draw_tutorial_popup


class GameScene(SceneBase):
    def __init__(self, app: "PygameApp", game: Game):
        super().__init__(app)
        self.game = game
        self.adapter = GameAdapter(game)

        self.font_small = pygame.font.SysFont("segoe ui", 14)
        self.font_body = pygame.font.SysFont("segoe ui", 16)
        self.font_title = pygame.font.SysFont("cambria", 23, bold=True)
        self.font_card_title = pygame.font.SysFont("cambria", 14, bold=True)
        self.font_card_body = pygame.font.SysFont("segoe ui", 12)
        self.font_card_tiny = pygame.font.SysFont("segoe ui", 11)

        self.time = 0.0
        self.selected_hand_index: int | None = None
        self.selected_barracks_index: int | None = None
        self.selected_unit_card: tuple[int, int, int] | None = None
        self.selected_battalion = 0
        self.selected_target: int | str | None = None
        self.log_scroll = 0
        self.action_scroll = 0
        self.stack_popup: dict[str, object] | None = None
        self.stack_popup_scroll = 0
        self.stack_popup_list_rect = pygame.Rect(0, 0, 0, 0)
        self.siege_report_popup: dict[str, object] | None = None
        self.siege_report_scroll = 0
        self.siege_report_list_rect = pygame.Rect(0, 0, 0, 0)
        self.pending_non_unit_target: dict[str, object] | None = None
        self.hand_scroll = {0: 0, 1: 0}
        self.hand_visible_cards = 1
        self.hand_card_gap = 8
        self.hand_card_width = 48
        self.hand_card_height = 68
        self.hovered_card = None
        self.hovered_card_hidden_preview = False
        self.tutorial_title_font = pygame.font.SysFont("cambria", 30, bold=True)
        self.tutorial_popup: TutorialCard | None = None
        self.tutorial_next_rect = pygame.Rect(0, 0, 0, 0)
        self.tutorial_skip_rect = pygame.Rect(0, 0, 0, 0)

        self.buttons: list[Button] = []
        self.click_map: list[tuple[pygame.Rect, Callable[[], None]]] = []
        self.action_panel_rect = pygame.Rect(926, 84, 338, 252)
        self.log_panel_rect = pygame.Rect(926, 616, 338, 64)
        self.hand_panel_rect = pygame.Rect(20, 616, 880, 84)
        self._recompute_hand_layout()
        ok, msg = self.game.advance_phase()
        self.set_status(msg if ok else "Game started.")

    def update(self, dt: float) -> None:
        self.time += dt
        self._open_pending_siege_report_popup()
        if self.game.winner is not None and self.siege_report_popup is None:
            if self.next_scene is None:
                from .scene_win import WinScene

                self.next_scene = WinScene(self.app, self.game.winner)
            return
        if self.game.phase == "replenish" and self.game.winner is None:
            ok, msg = self.game.advance_phase()
            self.set_status(msg)
            if not ok:
                return
        self._build_buttons()
        self.action_scroll = max(0, min(self.action_scroll, self._action_scroll_limit()))
        self._recompute_hand_layout()
        for player_index in (0, 1):
            hand_len = len(self.game.players[player_index].hand)
            max_offset = max(0, hand_len - self.hand_visible_cards)
            self.hand_scroll[player_index] = max(0, min(self.hand_scroll[player_index], max_offset))
        active_hand_len = len(self._active_player().hand)
        if self.selected_hand_index is not None and self.selected_hand_index >= active_hand_len:
            self.selected_hand_index = None
        if self.pending_non_unit_target is not None:
            pending_player = self.pending_non_unit_target.get("player_index")
            pending_hand = self.pending_non_unit_target.get("hand_index")
            pending_mode = self.pending_non_unit_target.get("target_mode")
            if (
                not isinstance(pending_player, int)
                or pending_player != self._active_player_index()
                or not isinstance(pending_hand, int)
                or not isinstance(pending_mode, str)
                or pending_hand < 0
                or pending_hand >= active_hand_len
            ):
                self.pending_non_unit_target = None
            else:
                pending_card = self._active_player().hand[pending_hand]
                if self._non_unit_target_mode(pending_card) != pending_mode:
                    self.pending_non_unit_target = None
        active_barracks_len = len(self._active_player().barracks.units)
        if self.selected_barracks_index is not None and self.selected_barracks_index >= active_barracks_len:
            self.selected_barracks_index = None
        if self.selected_unit_card is not None:
            pidx, bidx, cidx = self.selected_unit_card
            if pidx != self._active_player_index():
                self.selected_unit_card = None
            elif bidx not in (0, 1):
                self.selected_unit_card = None
            else:
                battalion_cards = self._active_player().battalions[bidx].cards
                if cidx < 0 or cidx >= len(battalion_cards):
                    self.selected_unit_card = None
        self._refresh_tutorial_popup()

    def _recompute_hand_layout(self) -> None:
        self.hand_card_height = max(24, self.hand_panel_rect.height - 30)
        self.hand_card_width = max(1, int(round(self.hand_card_height * 5 / 7)))
        slot = self.hand_card_width + self.hand_card_gap
        self.hand_visible_cards = max(1, (self.hand_panel_rect.width - 20 + self.hand_card_gap) // slot)

    def _action_visible_rows(self) -> int:
        return max(1, self.action_panel_rect.height // 22)

    def _action_total_rows(self) -> int:
        return (len(self.buttons) + 1) // 2

    def _action_scroll_limit(self) -> int:
        return max(0, self._action_total_rows() - self._action_visible_rows())

    def handle_event(self, event: pygame.event.Event) -> None:
        deploy_popup_active = (
            self.game.phase == "siege"
            and self.game.pending_first_deployer_choice is not None
            and self.game.pending_siege_roll is not None
        )
        profitable_standoff_popup_active = (
            self.game.phase == "draw" and self.game.pending_profitable_standoff_draw_player is not None
        )
        stack_popup_active = self.stack_popup is not None
        siege_report_popup_active = self.siege_report_popup is not None
        tutorial_popup_active = self.tutorial_popup is not None
        popup_active = (
            deploy_popup_active
            or profitable_standoff_popup_active
            or stack_popup_active
            or siege_report_popup_active
            or tutorial_popup_active
        )
        if tutorial_popup_active:
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    self._advance_tutorial_popup()
                    return
                if event.key == pygame.K_ESCAPE:
                    self._skip_tutorial_popup()
                    return
                return
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.tutorial_next_rect.collidepoint(event.pos):
                    self._advance_tutorial_popup()
                    return
                if self.tutorial_skip_rect.collidepoint(event.pos):
                    self._skip_tutorial_popup()
                    return
                return
            if event.type == pygame.MOUSEWHEEL:
                return
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE and stack_popup_active:
                self._close_stack_popup()
                return
            if event.key == pygame.K_ESCAPE and siege_report_popup_active:
                self._close_siege_report_popup()
                return
            if popup_active:
                return
            if event.key == pygame.K_SPACE:
                self._btn_next_phase()
                return
            if event.key == pygame.K_r:
                self._btn_ready()
                return
            if event.key == pygame.K_ESCAPE:
                self.selected_hand_index = None
                self.selected_barracks_index = None
                self.selected_unit_card = None
                self.selected_target = None
                self.pending_non_unit_target = None
                self.set_status("Selections cleared.")
                return
            if event.key == pygame.K_1:
                self._btn_select_battalion(0)
                return
            if event.key == pygame.K_2:
                self._btn_select_battalion(1)
                return

        if event.type == pygame.MOUSEWHEEL:
            mouse = pygame.mouse.get_pos()
            if siege_report_popup_active and self.siege_report_list_rect.collidepoint(mouse):
                lines = self._siege_report_popup_lines()
                row_h = 18
                max_lines = max(1, self.siege_report_list_rect.height // row_h)
                max_offset = max(0, len(lines) - max_lines)
                self.siege_report_scroll = max(0, min(max_offset, self.siege_report_scroll - event.y))
                return
            if siege_report_popup_active:
                return
            if stack_popup_active and self.stack_popup_list_rect.collidepoint(mouse):
                cards = self._stack_popup_cards()
                row_h = 30
                max_lines = max(1, self.stack_popup_list_rect.height // row_h)
                max_offset = max(0, len(cards) - max_lines)
                self.stack_popup_scroll = max(0, min(max_offset, self.stack_popup_scroll - event.y))
                return
            if stack_popup_active:
                return
            if profitable_standoff_popup_active:
                return
            if self.action_panel_rect.collidepoint(mouse):
                max_offset = self._action_scroll_limit()
                self.action_scroll = max(0, min(max_offset, self.action_scroll - event.y))
                return
            if self.log_panel_rect.collidepoint(mouse):
                _, max_offset = self.adapter.logs_window(max_lines=2, offset=self.log_scroll)
                self.log_scroll = max(0, min(max_offset, self.log_scroll - event.y))
                return
            if self.hand_panel_rect.collidepoint(mouse):
                active = self._active_player_index()
                max_offset = max(0, len(self._active_player().hand) - self.hand_visible_cards)
                self.hand_scroll[active] = max(0, min(max_offset, self.hand_scroll[active] - event.y))
                return

        if not popup_active:
            for button in self.buttons:
                if self.action_panel_rect.colliderect(button.rect) and button.handle_event(event):
                    return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for rect, callback in reversed(self.click_map):
                if rect.collidepoint(event.pos):
                    callback()
                    return

    def _selected_hand_card(self) -> object | None:
        if self.selected_hand_index is None:
            return None
        hand = self._active_player().hand
        if 0 <= self.selected_hand_index < len(hand):
            return hand[self.selected_hand_index]
        return None

    def _selected_barracks_card(self) -> object | None:
        if self.selected_barracks_index is None:
            return None
        units = self._active_player().barracks.units
        if 0 <= self.selected_barracks_index < len(units):
            return units[self.selected_barracks_index]
        return None

    def _selected_unit_target(self) -> tuple[int, int, object] | None:
        if self.selected_unit_card is None:
            return None
        pidx, bidx, cidx = self.selected_unit_card
        if pidx != self._active_player_index() or bidx not in (0, 1):
            return None
        battalion = self._active_player().battalions[bidx]
        if cidx < 0 or cidx >= len(battalion.cards):
            return None
        return bidx, cidx, battalion.cards[cidx]

    def _non_unit_target_mode(self, card: object | None) -> str:
        name = getattr(card, "name", "")
        if name == "Aegis Pulse":
            return "friendly_unit"
        if name == "Sabotage Lines":
            return "enemy_frontline"
        if name in ("Entrench", "Iron Discipline", "Reserve Rotation"):
            return "battalion"
        return "instant"

    def _stack_popup_cards(self) -> list[object]:
        if self.stack_popup is None:
            return []
        cards = self.stack_popup.get("cards", [])
        if isinstance(cards, list):
            return cards
        return list(cards)

    def _siege_report_popup_lines(self) -> list[str]:
        if self.siege_report_popup is None:
            return []
        lines = self.siege_report_popup.get("lines", [])
        if isinstance(lines, list):
            return [str(line) for line in lines]
        return []

    def _to_int(self, value: object, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _controller_label(self, controller: object) -> str:
        if isinstance(controller, int) and controller in (0, 1):
            return f"P{controller + 1}"
        return "Neutral"

    def _format_name_list(self, values: object) -> str:
        if not isinstance(values, list) or not values:
            return "-"
        return ", ".join(str(value) for value in values)

    def _format_siege_cards(self, cards: object) -> str:
        if not isinstance(cards, list) or not cards:
            return "-"
        bits: list[str] = []
        for card in cards:
            if isinstance(card, dict):
                name = str(card.get("name", "Card"))
                attack = card.get("attack")
                base_might = self._to_int(card.get("base_might"), 0)
                base_will = self._to_int(card.get("base_will"), 0)
                might_mod = self._to_int(card.get("might_mod"), 0)
                will_mod = self._to_int(card.get("will_mod"), 0)

                card_text = f"{name} (M{base_might}/W{base_will})"
                if isinstance(attack, int) and attack != base_might:
                    card_text += f" -> Atk {attack}"
                if might_mod != 0 or will_mod != 0:
                    card_text += f" [mods M{might_mod:+}/W{will_mod:+}]"
                bits.append(card_text)
            else:
                bits.append(str(card))
        return ", ".join(bits)

    def _format_siege_side_lines(self, label: str, side: object) -> list[str]:
        if not isinstance(side, dict):
            return [f"  {label} Total Might 0 | Attack 0", "    Front 0: -", "    Back 0: -"]

        total_might = self._to_int(side.get("total_might"), 0)
        attack_might = self._to_int(side.get("attack_might"), max(0, total_might))
        line_mix_penalty = self._to_int(side.get("line_mix_penalty"), 0)
        front_might = self._to_int(side.get("front_might"), 0)
        back_might = self._to_int(side.get("back_might"), 0)
        other_might = self._to_int(side.get("other_might"), 0)
        front_cards = side.get("front_cards")
        back_cards = side.get("back_cards")
        other_cards = side.get("other_cards")

        summary_line = f"  {label} Total Might {total_might} | Attack {attack_might}"
        if line_mix_penalty != 0:
            summary_line += f" | Spire Penalty {line_mix_penalty}"

        lines = [
            summary_line,
            f"    Front {front_might}: {self._format_siege_cards(front_cards)}",
            f"    Back {back_might}: {self._format_siege_cards(back_cards)}",
        ]
        if isinstance(other_cards, list) and other_cards:
            lines.append(f"    Other {other_might}: {self._format_siege_cards(other_cards)}")
        return lines

    def _format_siege_report_lines(self, report: dict[str, object]) -> list[str]:
        lines: list[str] = []

        slot_battles_raw = report.get("slot_battles", [])
        slot_battles = slot_battles_raw if isinstance(slot_battles_raw, list) else []
        if not slot_battles:
            lines.append("No slot battles were resolved.")

        for battle in slot_battles:
            if not isinstance(battle, dict):
                continue
            slot = battle.get("slot")
            slot_label = f"Slot {slot}" if isinstance(slot, int) else "Slot ?"
            battlefield_raw = battle.get("battlefield_name")
            battlefield_name = str(battlefield_raw) if battlefield_raw else "No Battlefield"
            lines.append(f"{slot_label} - {battlefield_name}")

            if bool(battle.get("skipped", False)):
                lines.append("  No units deployed to this slot.")
                lines.append("")
                continue

            lines.extend(self._format_siege_side_lines("P1", battle.get("p1")))
            lines.extend(self._format_siege_side_lines("P2", battle.get("p2")))

            deaths = battle.get("deaths")
            if isinstance(deaths, dict):
                lines.append(f"  Dead | P1: {self._format_name_list(deaths.get('p1'))}")
                lines.append(f"  Dead | P2: {self._format_name_list(deaths.get('p2'))}")
            else:
                lines.append("  Dead | P1: -")
                lines.append("  Dead | P2: -")

            prior_control = self._controller_label(battle.get("prior_controller"))
            new_control = self._controller_label(battle.get("new_controller"))
            lines.append(f"  Control: {prior_control} -> {new_control}")
            lines.append("")

        barracks_raw = report.get("barracks_battles", [])
        barracks_battles = barracks_raw if isinstance(barracks_raw, list) else []
        if barracks_battles:
            lines.append("Barracks Battles")
            lines.append("")
            for battle in barracks_battles:
                if not isinstance(battle, dict):
                    continue
                attacker_index = battle.get("attacker_index")
                defender_index = battle.get("defender_index")
                attacker_label = (
                    f"P{attacker_index + 1}" if isinstance(attacker_index, int) and attacker_index in (0, 1) else "P?"
                )
                defender_label = (
                    f"P{defender_index + 1}" if isinstance(defender_index, int) and defender_index in (0, 1) else "P?"
                )
                lines.append(f"{attacker_label} Assault on {defender_label} Barracks")
                lines.extend(self._format_siege_side_lines(f"{attacker_label} Attackers", battle.get("attacker")))
                lines.extend(self._format_siege_side_lines(f"{defender_label} Defenders", battle.get("defender")))
                deaths = battle.get("deaths")
                if isinstance(deaths, dict):
                    attacker_key = (
                        f"p{attacker_index + 1}"
                        if isinstance(attacker_index, int) and attacker_index in (0, 1)
                        else "p?"
                    )
                    defender_key = (
                        f"p{defender_index + 1}"
                        if isinstance(defender_index, int) and defender_index in (0, 1)
                        else "p?"
                    )
                    lines.append(
                        f"  Dead | {attacker_label}: {self._format_name_list(deaths.get(attacker_key))}"
                    )
                    lines.append(
                        f"  Dead | {defender_label}: {self._format_name_list(deaths.get(defender_key))}"
                    )
                lines.append("")

        winner_raw = report.get("winner")
        winner_label = (
            f"P{winner_raw + 1} won during siege."
            if isinstance(winner_raw, int) and winner_raw in (0, 1)
            else "No winner this siege."
        )
        lines.append(winner_label)
        return lines

    def _open_pending_siege_report_popup(self) -> None:
        if self.siege_report_popup is not None:
            return
        report_raw = getattr(self.game, "pending_siege_report", None)
        if not isinstance(report_raw, dict):
            return

        turn_raw = report_raw.get("turn")
        turn_label = f"Turn {turn_raw}" if isinstance(turn_raw, int) else "Turn"
        self.siege_report_popup = {
            "title": f"Siege Results - {turn_label}",
            "lines": self._format_siege_report_lines(report_raw),
        }
        self.siege_report_scroll = 0
        self.siege_report_list_rect = pygame.Rect(0, 0, 0, 0)
        self.game.pending_siege_report = None
        self.set_status("Siege recap is ready. Review battle outcomes.")

    def _close_siege_report_popup(self, announce: bool = True) -> None:
        self.siege_report_popup = None
        self.siege_report_scroll = 0
        self.siege_report_list_rect = pygame.Rect(0, 0, 0, 0)
        if announce:
            self.set_status("Closed siege recap.")

    def _open_stack_popup(
        self,
        title: str,
        cards: list[object],
        *,
        owner_index: int | None = None,
        conceal_unrevealed_for_opponents: bool = False,
        grave_player_index: int | None = None,
        row_click: Callable[[int], None] | None = None,
    ) -> None:
        self.stack_popup = {
            "title": title,
            "cards": list(cards),
            "owner_index": owner_index,
            "conceal_unrevealed_for_opponents": conceal_unrevealed_for_opponents,
            "grave_player_index": grave_player_index,
            "row_click": row_click,
        }
        self.stack_popup_scroll = 0
        self.stack_popup_list_rect = pygame.Rect(0, 0, 0, 0)
        self.set_status(f"Opened {title}.")

    def _close_stack_popup(self, announce: bool = True) -> None:
        self.stack_popup = None
        self.stack_popup_scroll = 0
        self.stack_popup_list_rect = pygame.Rect(0, 0, 0, 0)
        if announce:
            self.set_status("Closed stack view.")

    def _invoke(
        self,
        func: Callable[..., tuple[bool, str]],
        *args: object,
        clear_hand: bool = False,
    ) -> bool:
        ok, msg = func(*args)
        self.set_status(msg)
        if ok and clear_hand:
            self.selected_hand_index = None
            self.pending_non_unit_target = None
        return ok

    def _active_player_index(self) -> int:
        return self.game.current_player_index

    def _active_player(self):
        return self.game.players[self._active_player_index()]

    def _has_existing_popup(self) -> bool:
        deploy_popup_active = (
            self.game.phase == "siege"
            and self.game.pending_first_deployer_choice is not None
            and self.game.pending_siege_roll is not None
        )
        profitable_standoff_popup_active = (
            self.game.phase == "draw" and self.game.pending_profitable_standoff_draw_player is not None
        )
        return (
            deploy_popup_active
            or profitable_standoff_popup_active
            or self.stack_popup is not None
            or self.siege_report_popup is not None
        )

    def _tutorial_progress(self) -> tuple[int, int]:
        if self.tutorial_popup is None:
            return (1, 3)
        if self.tutorial_popup.key == "game_draw_overview":
            return (1, 3)
        if self.tutorial_popup.key == "game_preparations_overview":
            return (2, 3)
        return (3, 3)

    def _refresh_tutorial_popup(self) -> None:
        if self.tutorial_popup is not None or not self.app.tutorial_enabled:
            return
        if self._has_existing_popup():
            return
        if self.game.turn != 1:
            return
        if self.game.phase == "draw" and self.app.tutorial_pending("game_draw_overview"):
            self.tutorial_popup = TutorialCard(
                key="game_draw_overview",
                title="Draw Phase Walkthrough",
                lines=(
                    "Each turn starts here. Players draw and can use draw-phase actions.",
                    "Only the active player can act. The header shows whose turn it is.",
                    "Use the hand and action panels to plan resources and set up the next phase.",
                    "When done, press Ready so both players can move into Preparations.",
                ),
                continue_label="Next Tip",
            )
            return
        if self.game.phase == "preparations" and self.app.tutorial_pending("game_preparations_overview"):
            self.tutorial_popup = TutorialCard(
                key="game_preparations_overview",
                title="Preparations Walkthrough",
                lines=(
                    "Build battalions here. Click a Unit in hand, then click Battalion 1 or 2 to assign it.",
                    "Barracks units can also be moved into battalions with the action buttons.",
                    "For tactic cards, press Cast Non-Unit and then pick any required target card.",
                    "After both players are ready, the game advances to Siege.",
                ),
                continue_label="Next Tip",
            )
            return
        if (
            self.game.phase == "siege"
            and self.game.pending_first_deployer_choice is None
            and self.app.tutorial_pending("game_siege_overview")
        ):
            self.tutorial_popup = TutorialCard(
                key="game_siege_overview",
                title="Siege To Cleanup Walkthrough",
                lines=(
                    "In Siege, deploy each non-empty battalion once to a legal slot or barracks target.",
                    "Select Battalion 1 or 2, click a highlighted target, and repeat until all deployments are set.",
                    "Combat resolves automatically, battlefield control may change, then Field Cleanup runs.",
                    "That completes the turn loop. Next turn starts back at Draw.",
                ),
                continue_label="Finish Guide",
            )

    def _advance_tutorial_popup(self) -> None:
        if self.tutorial_popup is None:
            return
        self.app.mark_tutorial_seen(self.tutorial_popup.key)
        self.tutorial_popup = None
        self.tutorial_next_rect = pygame.Rect(0, 0, 0, 0)
        self.tutorial_skip_rect = pygame.Rect(0, 0, 0, 0)
        self.set_status("Tutorial tip completed.")
        self._refresh_tutorial_popup()

    def _skip_tutorial_popup(self) -> None:
        self.app.skip_all_tutorials()
        self.tutorial_popup = None
        self.tutorial_next_rect = pygame.Rect(0, 0, 0, 0)
        self.tutorial_skip_rect = pygame.Rect(0, 0, 0, 0)
        self.set_status("Tutorial guide skipped.")

    # ------------------------------------------------------------------ #
    # Button actions
    # ------------------------------------------------------------------ #
    def _btn_next_phase(self) -> None:
        self._invoke(self.game.advance_phase)

    def _btn_ready(self) -> None:
        idx = self._active_player_index()
        self._invoke(self.game.ready_current_player, idx)

    def _btn_select_battalion(self, battalion: int) -> None:
        self.selected_battalion = battalion
        self.set_status(f"Selected Battalion {battalion + 1} for targeted actions.")

    def _btn_assign_hand(self, battalion: int) -> None:
        if self.selected_hand_index is None:
            self.set_status("Select a hand card first.")
            return
        idx = self._active_player_index()
        self._invoke(
            self.game.assign_hand_card_to_battalion,
            idx,
            self.selected_hand_index,
            battalion,
            clear_hand=True,
        )

    def _btn_return_battalion(self, battalion: int) -> None:
        idx = self._active_player_index()
        self._invoke(self.game.remove_battalion_card_to_hand, idx, battalion, 0)

    def _btn_barracks_to_battalion(self, battalion: int) -> None:
        idx = self._active_player_index()
        barracks_index = self.selected_barracks_index if self.selected_barracks_index is not None else 0
        ok = self._invoke(self.game.assign_barracks_unit_to_battalion, idx, barracks_index, battalion)
        if ok:
            self.selected_barracks_index = None

    def _btn_deploy(self, battalion: int) -> None:
        if self.selected_target is None:
            self.set_status("Select a deployment target (slot or barracks) first.")
            return
        idx = self._active_player_index()
        self._invoke(self.game.assign_battalion_to_slot, idx, battalion, self.selected_target)

    def _btn_cast_non_unit(self) -> None:
        if self.selected_hand_index is None:
            self.set_status("Select a hand card first.")
            return
        idx = self._active_player_index()
        hand = self._active_player().hand
        if self.selected_hand_index < 0 or self.selected_hand_index >= len(hand):
            self.set_status("Invalid hand selection.")
            return
        card = hand[self.selected_hand_index]
        if getattr(card, "card_type", None) == "Unit":
            self.set_status("Selected hand card is not a non-unit.")
            return

        target_mode = self._non_unit_target_mode(card)
        if target_mode == "instant":
            self._invoke(
                self.game.play_non_unit_card,
                idx,
                self.selected_hand_index,
                None,
                None,
                None,
                clear_hand=True,
            )
            return

        self.pending_non_unit_target = {
            "player_index": idx,
            "hand_index": self.selected_hand_index,
            "target_mode": target_mode,
            "card_name": card.name,
        }
        if target_mode == "friendly_unit":
            self.set_status("Select one of your battalion cards to target this tactic.")
            return
        if target_mode == "enemy_frontline":
            self.set_status("Select an enemy front-line battalion card to target this tactic.")
            return
        self.set_status("Select one of your battalion cards to choose the target battalion.")

    def _resolve_pending_non_unit_target_from_card(
        self, player_index: int, battalion_index: int, card_index: int
    ) -> bool:
        pending = self.pending_non_unit_target
        if pending is None:
            return False
        active = self._active_player_index()
        pending_player = pending.get("player_index")
        pending_hand = pending.get("hand_index")
        target_mode = pending.get("target_mode")
        if pending_player != active or not isinstance(pending_hand, int) or not isinstance(target_mode, str):
            self.pending_non_unit_target = None
            return False
        hand = self._active_player().hand
        if pending_hand < 0 or pending_hand >= len(hand):
            self.pending_non_unit_target = None
            self.set_status("Selected tactic is no longer in hand.")
            return True

        if target_mode == "battalion":
            if player_index != active:
                self.set_status("Select one of your battalion cards to target a battalion.")
                return True
            self._invoke(
                self.game.play_non_unit_card,
                active,
                pending_hand,
                battalion_index,
                None,
                None,
                clear_hand=True,
            )
            return True

        if target_mode == "friendly_unit":
            if player_index != active:
                self.set_status("This tactic must target one of your battalion units.")
                return True
            self._invoke(
                self.game.play_non_unit_card,
                active,
                pending_hand,
                battalion_index,
                active,
                card_index,
                clear_hand=True,
            )
            return True

        if target_mode == "enemy_frontline":
            if player_index == active:
                self.set_status("This tactic must target an enemy front-line battalion unit.")
                return True
            battalion = self.game.players[player_index].battalions[battalion_index]
            if card_index < 0 or card_index >= len(battalion.cards):
                self.set_status("Invalid target card.")
                return True
            target_card = battalion.cards[card_index]
            if target_card.effective_line() != "Front":
                self.set_status("Target must be an enemy front-line unit.")
                return True
            self._invoke(
                self.game.play_non_unit_card,
                active,
                pending_hand,
                battalion_index,
                player_index,
                card_index,
                clear_hand=True,
            )
            return True

        self.pending_non_unit_target = None
        return False

    def _btn_trade(self, resource: str) -> None:
        idx = self._active_player_index()
        self._invoke(self.game.trade_rations_for_special, idx, resource)

    def _btn_efficient_tithe(self, resource: str) -> None:
        idx = self._active_player_index()
        self._invoke(self.game.use_efficient_tithe, idx, resource)

    def _btn_choose_first(self, chosen: int) -> None:
        chooser = self.game.pending_first_deployer_choice
        if chooser is None:
            self.set_status("No first deployer choice is pending.")
            return
        self._invoke(self.game.choose_first_deployer, chooser, chosen)

    def _btn_choose_profitable_standoff(self, top_index: int) -> None:
        owner = self.game.pending_profitable_standoff_draw_player
        if owner is None:
            self.set_status("No Profitable Standoff choice is pending.")
            return
        self._invoke(self.game.choose_profitable_standoff_card, owner, top_index)

    def _btn_clairvoyance(self) -> None:
        idx = self._active_player_index()
        self._invoke(self.game.use_clairvoyance, idx)

    def _btn_hall(self) -> None:
        idx = self._active_player_index()
        self._invoke(self.game.use_hall_of_mirrors, idx)

    def _btn_ossuary(self) -> None:
        idx = self._active_player_index()
        self._invoke(self.game.use_ossuary_keep, idx)

    def _btn_ashen(self) -> None:
        idx = self._active_player_index()
        self._invoke(self.game.start_ashen_recall, idx)

    def _btn_chirurgeon(self) -> None:
        idx = self._active_player_index()
        self._invoke(self.game.start_chirurgeon_recovery, idx)

    def _btn_miracle(self, battalion: int) -> None:
        idx = self._active_player_index()
        self._invoke(self.game.start_miracle_of_faith, idx, battalion)

    def _btn_tactical_bluff(self) -> None:
        idx = self._active_player_index()
        self._invoke(self.game.use_tactical_bluff, idx)

    def _btn_calc_deploy(self) -> None:
        idx = self._active_player_index()
        self._invoke(self.game.use_calculated_deployment, idx)

    def _btn_tactical_gambit(self) -> None:
        idx = self._active_player_index()
        self._invoke(self.game.use_tactical_gambit, idx)

    def _btn_relentless(self) -> None:
        idx = self._active_player_index()
        self._invoke(self.game.use_relentless_push, idx, self.selected_battalion, 0, None)

    def _btn_eye_storm(self) -> None:
        idx = self._active_player_index()
        self._invoke(self.game.use_eye_of_storm, idx, self.selected_battalion, 0)

    def _btn_pyre(self) -> None:
        idx = self._active_player_index()
        self._invoke(self.game.use_pyre_decree, idx)

    def _on_total_conquest_popup_row_click(self, barracks_index: int) -> None:
        owner = self.game.pending_total_conquest_pick_player
        if owner is None:
            self.set_status("No Total Conquest choice is pending.")
            return
        if self._invoke(self.game.choose_total_conquest_target, owner, barracks_index):
            self._close_stack_popup(announce=False)

    def _btn_total_conquest(self) -> None:
        idx = self._active_player_index()
        enemy_index = 1 - idx
        if self.game.pending_total_conquest_pick_player == idx:
            self._open_stack_popup(
                f"P{enemy_index + 1} Barracks - Total Conquest",
                self.game.players[enemy_index].barracks.units,
                owner_index=enemy_index,
                conceal_unrevealed_for_opponents=False,
                row_click=self._on_total_conquest_popup_row_click,
            )
            return
        if self._invoke(self.game.use_total_conquest, idx):
            self._open_stack_popup(
                f"P{enemy_index + 1} Barracks - Total Conquest",
                self.game.players[enemy_index].barracks.units,
                owner_index=enemy_index,
                conceal_unrevealed_for_opponents=False,
                row_click=self._on_total_conquest_popup_row_click,
            )

    def _btn_ironheart(self) -> None:
        idx = self._active_player_index()
        selected_target = self._selected_unit_target()
        card_index = 0
        battalion = self.selected_battalion
        if selected_target is not None:
            battalion, card_index, _ = selected_target
            self.selected_battalion = battalion
        self._invoke(self.game.use_ironheart_forges_boost, idx, battalion, card_index)

    def _build_buttons(self) -> None:
        self.buttons = []
        game = self.game
        phase = game.phase
        player_index = self._active_player_index()
        player = self._active_player()
        enemy = game.players[1 - player_index]
        selected_card = self._selected_hand_card()
        class_name = game._class_name(player_index)
        class_level = game._class_level(player_index)
        can_act, _ = game._legal_active_action(player_index)
        pending_choice = game.pending_first_deployer_choice is not None
        pending_roll = game.pending_siege_roll
        deploy_popup_active = phase == "siege" and pending_choice and pending_roll is not None
        standoff_popup_active = phase == "draw" and game.pending_profitable_standoff_draw_player is not None
        popup_active = (
            deploy_popup_active
            or standoff_popup_active
            or self.siege_report_popup is not None
            or self.tutorial_popup is not None
        )
        can_advance_siege = phase == "siege" and game._all_nonempty_battalions_deployed() and game.winner is None
        battalion_1 = player.battalions[0]
        battalion_2 = player.battalions[1]
        can_barracks_to_b1 = any(battalion_1.has_room(unit) for unit in player.barracks.units)
        can_barracks_to_b2 = any(battalion_2.has_room(unit) for unit in player.barracks.units)
        can_miracle_to_b1 = any(
            getattr(grave_card, "card_type", None) == "Unit" and battalion_1.has_room(grave_card)
            for grave_card in player.grave
        )
        can_miracle_to_b2 = any(
            getattr(grave_card, "card_type", None) == "Unit" and battalion_2.has_room(grave_card)
            for grave_card in player.grave
        )

        def has_hidden_battalion_card() -> bool:
            for battalion in player.battalions:
                for card in battalion.cards:
                    if not card.revealed:
                        return True
            return False

        def has_frontline_any() -> bool:
            return game._find_frontline_target(player_index, None, None) is not None

        def has_frontline_target_for_selected() -> bool:
            return game._find_frontline_target(player_index, self.selected_battalion, 0) is not None

        def selected_non_unit_playable() -> bool:
            if phase != "preparations" or not can_act:
                return False
            if selected_card is None or getattr(selected_card, "card_type", None) == "Unit":
                return False
            if not player.has_resources(dict(selected_card.cost)):
                return False

            enemy = game.players[1 - player_index]
            name = selected_card.name
            if name == "Aegis Pulse":
                return any(b.cards for b in player.battalions)
            if name == "Entrench":
                return any(b.cards for b in player.battalions)
            if name == "Iron Discipline":
                return any(b.cards for b in player.battalions)
            if name == "Mass Benediction":
                return any(
                    unit.effective_line() == "Back"
                    for battalion in player.battalions
                    for unit in battalion.cards
                )
            if name == "Reserve Rotation":
                return any(b.cards for b in player.battalions) and any(
                    hand_card is not selected_card and getattr(hand_card, "card_type", None) == "Unit"
                    for hand_card in player.hand
                )
            if name == "Rite of Ash":
                return bool(player.grave)
            if name == "Sabotage Lines":
                return any(
                    unit.effective_line() == "Front"
                    for battalion in enemy.battalions
                    for unit in battalion.cards
                )
            if name == "Supply Cache":
                return True
            return False

        def add_button(label: str, callback: Callable[[], None], enabled: bool = True) -> None:
            if popup_active or not enabled:
                return
            index = len(self.buttons)
            col = index % 2
            row = index // 2
            scroll_px = self.action_scroll * 22
            rect = pygame.Rect(926 + col * 167, self.action_panel_rect.y + row * 22 - scroll_px, 160, 20)
            self.buttons.append(Button(rect=rect, label=label, callback=callback, enabled=enabled))

        add_button(
            "Next Phase",
            self._btn_next_phase,
            enabled=game.winner is None and (phase == "field_cleanup" or can_advance_siege),
        )
        add_button("Ready", self._btn_ready, enabled=phase in ("draw", "preparations") and can_act)
        add_button(
            "Return B1",
            lambda: self._btn_return_battalion(0),
            enabled=phase == "preparations" and can_act and bool(player.battalions[0].cards),
        )
        add_button(
            "Return B2",
            lambda: self._btn_return_battalion(1),
            enabled=phase == "preparations" and can_act and bool(player.battalions[1].cards),
        )
        add_button(
            "Barracks -> B1",
            lambda: self._btn_barracks_to_battalion(0),
            enabled=phase == "preparations" and can_act and bool(player.barracks.units) and can_barracks_to_b1,
        )
        add_button(
            "Barracks -> B2",
            lambda: self._btn_barracks_to_battalion(1),
            enabled=phase == "preparations" and can_act and bool(player.barracks.units) and can_barracks_to_b2,
        )
        add_button("Cast Non-Unit", self._btn_cast_non_unit, enabled=selected_non_unit_playable())
        can_trade = phase in ("draw", "preparations", "siege") and can_act and player.resources.get("rations", 0) >= 3
        add_button("Trade Ore", lambda: self._btn_trade("ore"), enabled=can_trade and player.resources.get("ore", 0) < 5)
        add_button(
            "Trade Materia",
            lambda: self._btn_trade("materia"),
            enabled=can_trade and player.resources.get("materia", 0) < 5,
        )
        add_button(
            "Trade Magium",
            lambda: self._btn_trade("magium"),
            enabled=can_trade and player.resources.get("magium", 0) < 5,
        )
        add_button("Trade Faith", lambda: self._btn_trade("faith"), enabled=can_trade and player.resources.get("faith", 0) < 5)
        add_button(
            "Trade Sacrifice",
            lambda: self._btn_trade("sacrifice"),
            enabled=can_trade and player.resources.get("sacrifice", 0) < 5,
        )
        add_button(
            "Eff Tithe Ore",
            lambda: self._btn_efficient_tithe("ore"),
            enabled=(
                phase == "draw"
                and can_act
                and class_name == "Arch-Hierarch"
                and class_level >= 1
                and player.resources.get("efficient_tithe_used", 0) == 0
                and player.resources.get("rations", 0) >= 2
                and player.resources.get("ore", 0) < 5
            ),
        )
        add_button(
            "Clairvoyance",
            self._btn_clairvoyance,
            enabled=(
                phase == "draw"
                and can_act
                and player.resources.get("clairvoyance_used", 0) == 0
                and game._player_controls_battlefield(player_index, "Arcane Nexus")
                and player.resources.get("magium", 0) >= 1
                and bool(player.deck)
            ),
        )
        add_button(
            "Hall Mirrors",
            self._btn_hall,
            enabled=(
                phase == "preparations"
                and can_act
                and player.resources.get("hall_of_mirrors_used", 0) == 0
                and game._player_controls_battlefield(player_index, "Hall of Mirrors")
            ),
        )
        add_button(
            "Ossuary Keep",
            self._btn_ossuary,
            enabled=(
                phase == "preparations"
                and can_act
                and player.barracks.card.name == "Ossuary Keep"
                and player.resources.get("ossuary_keep_used", 0) == 0
                and bool(player.grave)
                and player.resources.get("faith", 0) >= 1
            ),
        )
        add_button(
            "Ashen Recall",
            self._btn_ashen,
            enabled=(
                phase == "preparations"
                and can_act
                and class_name == "Ash Chancellor"
                and class_level >= 3
                and player.resources.get("ashen_recall_used", 0) == 0
                and bool(player.grave)
                and player.resources.get("sacrifice", 0) >= 1
            ),
        )
        add_button(
            "Chirurgeon",
            self._btn_chirurgeon,
            enabled=(
                phase == "preparations"
                and can_act
                and player.resources.get("chirurgeon_uses_left", 0) > 0
                and bool(player.grave)
                and player.resources.get("materia", 0) >= 1
            ),
        )
        add_button(
            "Miracle -> B1",
            lambda: self._btn_miracle(0),
            enabled=(
                phase == "preparations"
                and can_act
                and class_name == "Arch-Hierarch"
                and class_level >= 6
                and player.resources.get("miracle_of_faith_used", 0) == 0
                and bool(player.grave)
                and player.resources.get("sacrifice", 0) >= 1
                and player.resources.get("faith", 0) >= 1
                and can_miracle_to_b1
            ),
        )
        add_button(
            "Miracle -> B2",
            lambda: self._btn_miracle(1),
            enabled=(
                phase == "preparations"
                and can_act
                and class_name == "Arch-Hierarch"
                and class_level >= 6
                and player.resources.get("miracle_of_faith_used", 0) == 0
                and bool(player.grave)
                and player.resources.get("sacrifice", 0) >= 1
                and player.resources.get("faith", 0) >= 1
                and can_miracle_to_b2
            ),
        )
        add_button(
            "Tactical Bluff",
            self._btn_tactical_bluff,
            enabled=(
                phase == "preparations"
                and can_act
                and class_name == "Grand Strategist"
                and class_level >= 1
                and player.resources.get("tactical_bluff_used", 0) == 0
                and bool(player.hand)
                and has_hidden_battalion_card()
            ),
        )
        add_button(
            "Tact Gambit",
            self._btn_tactical_gambit,
            enabled=(
                phase == "siege"
                and can_act
                and class_name == "Grand Strategist"
                and class_level >= 6
                and player.resources.get("tactical_gambit_used", 0) == 0
                and game.siege_assignments[player_index][0] is not None
                and game.siege_assignments[player_index][1] is not None
            ),
        )
        add_button(
            "Relentless",
            self._btn_relentless,
            enabled=(
                phase == "siege"
                and can_act
                and class_name == "Vanguard"
                and class_level >= 3
                and player.resources.get("relentless_push_used", 0) == 0
                and has_frontline_target_for_selected()
                and (player.resources.get("ore", 0) >= 1 or player.resources.get("materia", 0) >= 1)
            ),
        )
        add_button(
            "Eye of Storm",
            self._btn_eye_storm,
            enabled=(
                phase == "siege"
                and can_act
                and class_name == "Storm Warden"
                and class_level >= 6
                and player.resources.get("eye_of_storm_used", 0) == 0
                and player.resources.get("magium", 0) >= 1
                and has_frontline_target_for_selected()
            ),
        )
        add_button(
            "Pyre Decree",
            self._btn_pyre,
            enabled=(
                phase == "siege"
                and can_act
                and class_name == "Ash Chancellor"
                and class_level >= 6
                and player.resources.get("pyre_decree_used", 0) == 0
                and player.resources.get("sacrifice", 0) >= 2
                and has_frontline_any()
            ),
        )
        add_button(
            "Total Conq",
            self._btn_total_conquest,
            enabled=(
                phase == "draw"
                and can_act
                and class_name == "Vanguard"
                and class_level >= 6
                and player.resources.get("total_conquest_used", 0) == 0
                and bool(enemy.barracks.units)
                and (
                    player.resources.get("total_conquest_ready", 0) == 1
                    or game.pending_total_conquest_pick_player == player_index
                )
            ),
        )
        add_button(
            "Ironheart +1",
            self._btn_ironheart,
            enabled=(
                phase == "preparations"
                and can_act
                and player.resources.get("ironheart_used", 0) == 0
                and game._player_controls_battlefield(player_index, "Ironheart Forges")
                and player.resources.get("ore", 0) >= 1
                and bool(player.battalions[self.selected_battalion].cards)
            ),
        )
        add_button(
            "Calc Deploy",
            self._btn_calc_deploy,
            enabled=(
                phase == "siege"
                and pending_choice
                and pending_roll is not None
                and class_name == "Grand Strategist"
                and class_level >= 3
                and player.resources.get("calculated_deployment_used", 0) == 0
                and pending_roll.get("loser") == player_index
            ),
        )

    def _action_tooltip_text(self, label: str) -> str | None:
        if label == "Next Phase":
            return "Advance the game phase when valid for the current state."
        if label == "Ready":
            return "Lock in this player's turn for the current phase."
        if label.startswith("Return B"):
            btag = label.replace("Return ", "")
            return (
                f"Return the first card in {btag}. Cards that came from barracks return to barracks; "
                "other cards return to hand."
            )
        if label.startswith("Barracks -> B"):
            battalion = label.split("->", 1)[1].strip()
            return f"Move the selected barracks unit into {battalion} for free."
        if label == "Cast Non-Unit":
            return "Play selected non-unit. Targeted tactics require selecting a battalion card after pressing."
        if label.startswith("Trade "):
            resource = label.split(" ", 1)[1].lower()
            return f"Spend 3 rations to gain 1 {resource} (max 5)."
        if label == "Eff Tithe Ore":
            return "Arch-Hierarch: Spend 2 rations to gain 1 ore this draw phase."
        if label == "Clairvoyance":
            return "Arcane Nexus: Spend 1 magium to draw 2, then discard 1."
        if label == "Hall Mirrors":
            return "Hall of Mirrors trigger. In preparations, gain 1 magium and draw 1."
        if label == "Ossuary Keep":
            return "Ossuary Keep: Pay 1 faith to recover a Unit from grave."
        if label == "Ashen Recall":
            return "Ash Chancellor: Pay 1 sacrifice to recover a Unit from grave."
        if label == "Chirurgeon":
            return "Pay 1 materia to recover a Unit from grave (limited uses)."
        if label.startswith("Miracle -> B"):
            battalion = label.split("->", 1)[1].strip()
            return f"Arch-Hierarch: recover a Unit from grave directly into {battalion}."
        if label == "Tactical Bluff":
            return "Grand Strategist: swap a hidden battalion card with a hand card."
        if label == "Tact Gambit":
            return "Grand Strategist: force redeployment order adjustment in siege."
        if label == "Relentless":
            return "Vanguard: pay ore or materia to buff a frontline engagement."
        if label == "Eye of Storm":
            return "Storm Warden: spend magium for a frontline combat swing."
        if label == "Pyre Decree":
            return "Ash Chancellor: spend 2 sacrifice for a strong siege effect."
        if label == "Total Conq":
            return "Vanguard: in draw, choose one enemy barracks unit to fell (once per game, after conquest)."
        if label == "Ironheart +1":
            return "Ironheart Forges: spend 1 ore to boost selected battalion Unit."
        if label == "Calc Deploy":
            return "Grand Strategist: reroll or alter first-deployer determination."
        return None

    def _draw_action_tooltip(self, surface: pygame.Surface, text: str, anchor: tuple[int, int]) -> None:
        max_width = 300
        lines = wrap_text(self.font_small, text, max_width - 16, 8)
        if not lines:
            return
        text_width = max(self.font_small.size(line)[0] for line in lines)
        width = min(max_width, text_width + 16)
        height = 10 + len(lines) * 16

        x = anchor[0] + 12
        y = anchor[1] - height - 10
        if x + width > surface.get_width() - 8:
            x = surface.get_width() - width - 8
        if y < 8:
            y = anchor[1] + 12
        if y + height > surface.get_height() - 8:
            y = surface.get_height() - height - 8

        tooltip = pygame.Rect(x, y, width, height)
        draw_panel(surface, tooltip, fill=(36, 44, 58), border=(19, 22, 30), radius=7, glow=ACCENT)
        for idx, line in enumerate(lines):
            draw_text(surface, self.font_small, line, tooltip.x + 8, tooltip.y + 6 + idx * 16, TEXT, max_width=width - 12)

    # ------------------------------------------------------------------ #
    # Card and board click handling
    # ------------------------------------------------------------------ #
    def _on_hand_click(self, player_index: int, hand_index: int) -> None:
        if self.game.pending_clairvoyance_discard_player == player_index:
            self._invoke(self.game.choose_clairvoyance_discard, player_index, hand_index)
            return
        if player_index != self._active_player_index():
            self.set_status("Only active player's hand can be selected.")
            return
        self.pending_non_unit_target = None
        self.selected_hand_index = hand_index
        self.selected_barracks_index = None
        self.selected_unit_card = None
        card = self.game.players[player_index].hand[hand_index]
        self.set_status(f"Selected hand card: {card.name}")

    def _on_barracks_unit_click(self, player_index: int, barracks_index: int) -> None:
        if self.pending_non_unit_target is not None:
            self.set_status("Select a battalion card to finish targeting the pending tactic.")
            return
        if player_index != self._active_player_index():
            units = self.game.players[player_index].barracks.units
            if len(units) > 2:
                self._open_stack_popup(
                    f"P{player_index + 1} Barracks",
                    units,
                    owner_index=player_index,
                    conceal_unrevealed_for_opponents=False,
                )
            else:
                self.set_status("Only active player's barracks units can be selected.")
            return
        units = self.game.players[player_index].barracks.units
        if barracks_index < 0 or barracks_index >= len(units):
            self.set_status("Invalid barracks unit.")
            return
        self.selected_barracks_index = barracks_index
        self.selected_hand_index = None
        self.selected_unit_card = None
        self.pending_non_unit_target = None
        self.set_status(f"Selected barracks card: {units[barracks_index].name}")

    def _on_barracks_box_click(self, player_index: int) -> None:
        units = self.game.players[player_index].barracks.units
        if len(units) > 2:
            self._open_stack_popup(
                f"P{player_index + 1} Barracks",
                units,
                owner_index=player_index,
                conceal_unrevealed_for_opponents=False,
            )
            return
        if player_index != self._active_player_index():
            self.set_status("Only active player's barracks can be interacted with.")
            return
        self.set_status("Select a visible barracks unit card.")

    def _open_grave_stack_popup(self, player_index: int) -> None:
        grave = self.game.players[player_index].grave
        self._open_stack_popup(
            f"P{player_index + 1} Grave",
            grave,
            owner_index=player_index,
            conceal_unrevealed_for_opponents=False,
            grave_player_index=player_index,
        )

    def _on_grave_box_click(self, player_index: int) -> None:
        self._open_grave_stack_popup(player_index)

    def _open_battalion_stack_popup(self, player_index: int, battalion_index: int) -> None:
        if battalion_index not in (0, 1):
            return
        battalion = self.game.players[player_index].battalions[battalion_index]
        if len(battalion.cards) <= 2:
            return
        self._open_stack_popup(
            f"P{player_index + 1} Battalion {battalion_index + 1}",
            battalion.cards,
            owner_index=player_index,
            conceal_unrevealed_for_opponents=True,
        )

    def _on_battalion_card_click(self, player_index: int, battalion_index: int, card_index: int) -> None:
        if battalion_index not in (0, 1):
            self.set_status("Invalid battalion.")
            return
        battalion = self.game.players[player_index].battalions[battalion_index]
        if card_index < 0 or card_index >= len(battalion.cards):
            self.set_status("Invalid battalion card.")
            return
        if self._resolve_pending_non_unit_target_from_card(player_index, battalion_index, card_index):
            return
        if player_index != self._active_player_index():
            if len(battalion.cards) > 2:
                self._open_battalion_stack_popup(player_index, battalion_index)
            else:
                self.set_status("Only active player's battalion cards can be selected.")
            return

        if self.selected_hand_index is not None or self.selected_barracks_index is not None or self.game.phase == "siege":
            self._on_battalion_click(player_index, battalion_index)
            return

        self.selected_battalion = battalion_index
        self.selected_unit_card = (player_index, battalion_index, card_index)
        card = battalion.cards[card_index]
        self.set_status(f"Selected battalion card: {card.name}")

    def _on_grave_click(self, player_index: int, grave_index: int) -> bool:
        pending = self.game.pending_grave_pick
        if not pending or int(pending["player"]) != player_index:
            self.set_status("No grave selection pending for this player.")
            return False
        return self._invoke(self.game.choose_grave_card, player_index, grave_index)

    def _on_grave_popup_row_click(self, player_index: int, grave_index: int) -> None:
        if self._on_grave_click(player_index, grave_index):
            self._close_stack_popup(announce=False)

    def _on_battalion_click(self, player_index: int, battalion_index: int) -> None:
        if battalion_index not in (0, 1):
            self.set_status("Invalid battalion.")
            return
        if self.pending_non_unit_target is not None:
            self.set_status("Select a battalion card to target the pending tactic.")
            return
        battalion = self.game.players[player_index].battalions[battalion_index]
        if player_index != self._active_player_index():
            if len(battalion.cards) > 2:
                self._open_battalion_stack_popup(player_index, battalion_index)
            else:
                self.set_status("Only active player's battalions can be targeted.")
            return

        self.selected_battalion = battalion_index
        if self.game.phase == "preparations" and self.selected_barracks_index is None and self.selected_hand_index is None:
            self.selected_unit_card = None
        if self.game.phase == "preparations" and self.selected_barracks_index is not None:
            ok = self._invoke(
                self.game.assign_barracks_unit_to_battalion,
                player_index,
                self.selected_barracks_index,
                battalion_index,
            )
            if ok:
                self.selected_barracks_index = None
            return

        selected_card = self._selected_hand_card()
        selected_type = getattr(selected_card, "card_type", None)
        if self.game.phase == "preparations" and selected_type == "Unit":
            self._invoke(
                self.game.assign_hand_card_to_battalion,
                player_index,
                self.selected_hand_index,
                battalion_index,
                clear_hand=True,
            )
            return
        if self.selected_hand_index is not None and selected_type == "Tactic":
            self.set_status("Press Cast Non-Unit, then select a battalion card target.")
            return
        if self.game.phase == "preparations" and self.selected_hand_index is not None:
            self.set_status("Selected hand card is not a Unit.")
            return

        if self.game.phase == "siege":
            self.set_status(f"Battalion {battalion_index + 1} selected. Click a battlefield target.")
            return

        if len(battalion.cards) > 2:
            self._open_battalion_stack_popup(player_index, battalion_index)
            return

        self.set_status(f"Selected Battalion {battalion_index + 1}.")

    def _on_slot_click(self, slot: int) -> None:
        self.selected_target = slot
        if self.game.phase == "siege" and self.game.pending_first_deployer_choice is None:
            active = self._active_player_index()
            if self.adapter.battalion_can_deploy(active, self.selected_battalion):
                self._invoke(self.game.assign_battalion_to_slot, active, self.selected_battalion, slot)
                return
        self.set_status(f"Selected siege target slot {slot}.")

    def _on_barracks_target_click(self, player_index: int) -> None:
        target = f"barracks:{player_index}"
        self.selected_target = target
        if self.game.phase == "siege" and self.game.pending_first_deployer_choice is None:
            active = self._active_player_index()
            if self.adapter.battalion_can_deploy(active, self.selected_battalion):
                self._invoke(self.game.assign_battalion_to_slot, active, self.selected_battalion, target)
                return
        self.set_status(f"Selected siege target {target}.")

    # ------------------------------------------------------------------ #
    # Drawing
    # ------------------------------------------------------------------ #
    def draw(self, surface: pygame.Surface) -> None:
        self.click_map = []
        self.hovered_card = None
        self.hovered_card_hidden_preview = False
        draw_board_background(surface, self.time)

        board_rect = pygame.Rect(10, 10, 900, 700)
        side_rect = pygame.Rect(920, 10, 350, 700)
        draw_panel(surface, board_rect, fill=PANEL, border=(20, 24, 32), radius=10)
        draw_panel(surface, side_rect, fill=PANEL, border=(20, 24, 32), radius=10)

        self._draw_header(surface, pygame.Rect(20, 20, 880, 62))
        self._draw_player_zone(surface, player_index=1, rect=pygame.Rect(20, 90, 880, 136))
        self._draw_battlefield_grid(surface, pygame.Rect(20, 234, 880, 230))
        self._draw_player_zone(surface, player_index=0, rect=pygame.Rect(20, 472, 880, 136))
        self._draw_active_hand_panel(surface, pygame.Rect(20, 616, 880, 84))
        self._draw_side_panel(surface)
        self._draw_stack_popup(surface)
        self._draw_profitable_standoff_popup(surface)
        self._draw_deploy_roll_popup(surface)
        self._draw_siege_report_popup(surface)
        self._draw_tutorial_popup(surface)

    def _draw_header(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        draw_panel(surface, rect, fill=PANEL_ALT, border=(19, 22, 31), radius=8)
        winner_text = "None" if self.game.winner is None else f"Player {self.game.winner + 1}"
        draw_text(
            surface,
            self.font_title,
            (
                f"Turn {self.game.turn}  |  Phase: {self.game.phase.upper()}  |  "
                f"Active: P{self.game.current_player_index + 1}  |  Winner: {winner_text}"
            ),
            rect.x + 10,
            rect.y + 8,
            TEXT,
            max_width=rect.width - 20,
        )

        notes: list[str] = []
        if self.game.pending_first_deployer_choice is not None:
            notes.append(f"P{self.game.pending_first_deployer_choice + 1} must choose first deployer.")
        if self.game.pending_grave_pick is not None:
            pending = self.game.pending_grave_pick
            notes.append(f"Pending grave pick: P{int(pending['player']) + 1} ({pending['source']}).")
        if self.game.pending_clairvoyance_discard_player is not None:
            notes.append(f"P{self.game.pending_clairvoyance_discard_player + 1} must discard for Clairvoyance.")
        if self.game.pending_profitable_standoff_draw_player is not None:
            notes.append(
                f"P{self.game.pending_profitable_standoff_draw_player + 1} must order top cards for Profitable Standoff."
            )
        if self.game.pending_total_conquest_pick_player is not None:
            notes.append(
                f"P{self.game.pending_total_conquest_pick_player + 1} must choose an enemy barracks unit for Total Conquest."
            )
        if self.pending_non_unit_target is not None:
            pending_name = self.pending_non_unit_target.get("card_name", "Tactic")
            notes.append(f"Pending tactic target: {pending_name}. Click a battalion card.")
        note_text = (
            "  |  ".join(notes)
            if notes
            else "Space: Next Phase  R: Ready  Click card then Battalion to assign  Esc: Clear"
        )
        draw_text(surface, self.font_small, note_text, rect.x + 10, rect.y + 42, INFO, max_width=rect.width - 20)

    def _resource_line(self, player_index: int) -> str:
        player = self.game.players[player_index]
        res = player.resources
        return (
            f"Rations {res['rations']}  Ore {res['ore']}  Materia {res['materia']}  "
            f"Magium {res['magium']}  Faith {res['faith']}  Sacrifice {res['sacrifice']}"
        )

    def _draw_player_zone(self, surface: pygame.Surface, player_index: int, rect: pygame.Rect) -> None:
        player = self.game.players[player_index]
        active = player_index == self._active_player_index()
        base = (48, 59, 79) if player_index == 0 else (81, 56, 63)
        glow = P1_COLOR if player_index == 0 else P2_COLOR
        draw_panel(surface, rect, fill=base, border=(20, 24, 32), radius=8, glow=glow if active else None)

        top_color = P1_COLOR if player_index == 0 else P2_COLOR
        draw_text(
            surface,
            self.font_body,
            (
                f"P{player_index + 1} {player.name}  |  XP {player.xp}  "
                f"(Lv {player.class_level()})  |  Class {player.player_class.name}  |  Barracks {player.barracks.card.name}"
            ),
            rect.x + 10,
            rect.y + 6,
            top_color,
            max_width=rect.width - 20,
        )
        draw_text(
            surface,
            self.font_small,
            self._resource_line(player_index),
            rect.x + 10,
            rect.y + 24,
            TEXT,
            max_width=rect.width - 20,
        )

        battalion_y = rect.y + 44
        frame_h = max(74, min(108, rect.bottom - battalion_y - 6))
        battalion_slot_h = max(42, frame_h - 28)
        pulse = 0.5 + 0.5 * math.sin(self.time * 6.0)
        for bidx, battalion in enumerate(player.battalions):
            frame = pygame.Rect(rect.x + 10 + bidx * 248, battalion_y, 236, frame_h)
            highlight = (
                active
                and self.selected_battalion == bidx
                and (170 + int(40 * pulse), 160 + int(28 * pulse), 95 + int(10 * pulse))
            )
            draw_panel(
                surface,
                frame,
                fill=PANEL_ALT if not highlight else (68, 86, 117),
                border=(22, 26, 34),
                radius=7,
                glow=highlight if highlight else None,
            )
            draw_text(surface, self.font_small, f"Battalion {bidx + 1}", frame.x + 8, frame.y + 5, MUTED)
            self.click_map.append((frame, lambda p=player_index, b=bidx: self._on_battalion_click(p, b)))

            for cidx, card in enumerate(battalion.cards[:2]):
                slot_rect = pygame.Rect(frame.x + 8 + cidx * 114, frame.y + 22, 106, battalion_slot_h)
                click_rect = slot_rect.inflate(-2, 0)
                card_rect = fit_card_rect(slot_rect, card.card_type)
                hovered = click_rect.collidepoint(pygame.mouse.get_pos())
                if hovered:
                    self.hovered_card = card
                    self.hovered_card_hidden_preview = (
                        not card.revealed and player_index != self._active_player_index()
                    )
                    card_rect = card_rect.move(0, -3)
                selected_unit = (
                    self.selected_unit_card is not None
                    and self.selected_unit_card == (player_index, bidx, cidx)
                )
                draw_tcg_card(
                    surface,
                    card_rect,
                    card=card,
                    selected=selected_unit or (active and self.selected_battalion == bidx),
                    hidden=not card.revealed,
                    title_font=self.font_card_title,
                    body_font=self.font_card_body,
                    tiny_font=self.font_card_tiny,
                )
                self.click_map.append(
                    (
                        click_rect,
                        lambda p=player_index, b=bidx, c=cidx: self._on_battalion_card_click(p, b, c),
                    )
                )

            if len(battalion.cards) > 2:
                more_rect = pygame.Rect(frame.x + frame.width - 80, frame.y + frame.height - 18, 72, 14)
                draw_text(
                    surface,
                    self.font_small,
                    f"+{len(battalion.cards) - 2} more",
                    more_rect.x + 6,
                    more_rect.y - 2,
                    MUTED,
                )
                self.click_map.append(
                    (
                        more_rect,
                        lambda p=player_index, b=bidx: self._open_battalion_stack_popup(p, b),
                    )
                )

        barracks_box = pygame.Rect(rect.x + 506, battalion_y, 156, frame_h)
        draw_panel(surface, barracks_box, fill=PANEL_ALT, border=(21, 25, 33), radius=7)
        draw_text(surface, self.font_small, "Barracks Units", barracks_box.x + 8, barracks_box.y + 5, MUTED)
        self.click_map.append((barracks_box, lambda p=player_index: self._on_barracks_box_click(p)))
        barracks_slot_h = max(42, frame_h - 28)
        for idx, card in enumerate(player.barracks.units[:2]):
            slot_rect = pygame.Rect(barracks_box.x + 8 + idx * 74, barracks_box.y + 22, 70, barracks_slot_h).inflate(4, 0)
            click_rect = slot_rect.inflate(6, 2)
            card_rect = fit_card_rect(slot_rect, card.card_type)
            selected_barracks = active and idx == self.selected_barracks_index
            if click_rect.collidepoint(pygame.mouse.get_pos()):
                self.hovered_card = card
                self.hovered_card_hidden_preview = False
                card_rect = card_rect.move(0, -2)
            draw_tcg_card(
                surface,
                card_rect,
                card=card,
                selected=selected_barracks,
                hidden=False,
                title_font=self.font_card_title,
                body_font=self.font_card_body,
                tiny_font=self.font_card_tiny,
            )
            self.click_map.append((click_rect, lambda p=player_index, bidx=idx: self._on_barracks_unit_click(p, bidx)))
        if len(player.barracks.units) > 2:
            draw_text(
                surface,
                self.font_small,
                f"+{len(player.barracks.units) - 2}",
                barracks_box.x + 108,
                barracks_box.y + 5,
                MUTED,
            )

        grave_box = pygame.Rect(rect.x + 670, battalion_y, 96, frame_h)
        draw_panel(surface, grave_box, fill=PANEL_ALT, border=(21, 25, 33), radius=7)
        draw_text(surface, self.font_small, f"Grave {len(player.grave)}", grave_box.x + 8, grave_box.y + 5, MUTED)
        self.click_map.append((grave_box, lambda p=player_index: self._on_grave_box_click(p)))
        grave_rows = 4
        grave_row_gap = 4
        grave_row_h = max(14, min(20, (max(0, frame_h - 28) - grave_row_gap * (grave_rows - 1)) // grave_rows))
        for i, card in enumerate(player.grave[:grave_rows]):
            row_rect = pygame.Rect(
                grave_box.x + 10,
                grave_box.y + 24 + i * (grave_row_h + grave_row_gap),
                76,
                grave_row_h,
            )
            pygame.draw.rect(surface, (72, 79, 96), row_rect, border_radius=4)
            pygame.draw.rect(surface, (20, 23, 31), row_rect, width=1, border_radius=4)
            draw_text(surface, self.font_small, truncate_text(self.font_small, card.name, 66), row_rect.x + 4, row_rect.y + 2, TEXT)
            self.click_map.append((row_rect, lambda p=player_index, idx=i: self._on_grave_click(p, idx)))
            if row_rect.collidepoint(pygame.mouse.get_pos()):
                self.hovered_card = card
                self.hovered_card_hidden_preview = False
        if len(player.grave) > grave_rows:
            draw_text(
                surface,
                self.font_small,
                f"+{len(player.grave) - grave_rows}",
                grave_box.right - 24,
                grave_box.y + 5,
                MUTED,
            )

        info_box = pygame.Rect(rect.x + 774, battalion_y, 116, frame_h)
        draw_panel(surface, info_box, fill=PANEL_ALT, border=(21, 25, 33), radius=7)
        info_line_gap = max(14, min(20, (frame_h - 16) // 2))
        draw_text(surface, self.font_small, f"Deck: {len(player.deck)}", info_box.x + 8, info_box.y + 8, MUTED)
        draw_text(surface, self.font_small, f"Hand: {len(player.hand)}", info_box.x + 8, info_box.y + 8 + info_line_gap, MUTED)

    def _draw_battlefield_grid(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        draw_panel(surface, rect, fill=PANEL_ALT, border=(20, 24, 32), radius=8)
        draw_text(surface, self.font_body, "Battlefield Grid", rect.x + 10, rect.y + 8, INFO)

        active = self._active_player_index()
        legal_targets = self.adapter.legal_deploy_targets(active)
        deployment_preview = self.adapter.battalion_can_deploy(active, self.selected_battalion)
        top = rect.y + 24
        content_h = rect.height - 30
        side_w = 126
        left_target = pygame.Rect(rect.x + 8, top, side_w, content_h)
        right_target = pygame.Rect(rect.right - side_w - 8, top, side_w, content_h)
        center = pygame.Rect(
            left_target.right + 10,
            top,
            right_target.x - left_target.right - 20,
            content_h,
        )

        grid_rect = center.inflate(0, -4)
        grid_rect.y += 2
        gap = 6
        cell_w = (grid_rect.width - gap * 2) // 3
        cell_h = (grid_rect.height - gap) // 2
        mouse = pygame.mouse.get_pos()

        def badge_style(_label: str) -> tuple[int, int]:
            # Keep all assignment badges a consistent size.
            return (70, 20)

        def draw_assignment_badge(badge: pygame.Rect, label: str, color: tuple[int, int, int]) -> None:
            pygame.draw.rect(surface, (34, 40, 52), badge, border_radius=4)
            pygame.draw.rect(surface, color, badge, width=1, border_radius=4)
            clipped_label = truncate_text(self.font_small, label, badge.width - 8)
            text_w, text_h = self.font_small.size(clipped_label)
            text_x = badge.x + (badge.width - text_w) // 2
            text_y = badge.y + (badge.height - text_h) // 2
            draw_text(surface, self.font_small, clipped_label, text_x, text_y, color, max_width=badge.width - 8)

        assignment_labels: dict[int | str, list[tuple[str, tuple[int, int, int]]]] = {}
        if self.game.phase == "siege":
            for pidx in (0, 1):
                p_color = P1_COLOR if pidx == 0 else P2_COLOR
                for bidx, target in enumerate(self.game.siege_assignments[pidx]):
                    if target is None:
                        continue
                    assignment_labels.setdefault(target, []).append((f"P{pidx + 1}B{bidx + 1}", p_color))

        for slot in range(6):
            row = slot // 3
            col = slot % 3
            cell_rect = pygame.Rect(
                grid_rect.x + col * (cell_w + gap),
                grid_rect.y + row * (cell_h + gap),
                cell_w,
                cell_h,
            )
            slot_data = self.game.battlefield_gap[slot]
            control = slot_data["controlled_by"]
            card = slot_data["card"]

            fill = (73, 80, 98)
            if control == 0:
                fill = (76, 111, 156)
            elif control == 1:
                fill = (146, 86, 94)

            glow: tuple[int, int, int] | None = None
            if deployment_preview and slot in legal_targets:
                fill = (
                    min(255, fill[0] + 10),
                    min(255, fill[1] + 22),
                    min(255, fill[2] + 10),
                )
                glow = LEGAL_TARGET
            if self.selected_target == slot:
                glow = ACCENT if slot in legal_targets or not deployment_preview else INVALID_TARGET

            draw_panel(surface, cell_rect, fill=fill, border=(22, 25, 33), radius=6, glow=glow)
            card_slot = cell_rect.inflate(-6, -6)
            if card is not None:
                card_rect = fit_card_rect(card_slot, "Battlefield")
                draw_tcg_card(
                    surface,
                    card_rect,
                    card=card,
                    selected=self.selected_target == slot,
                    hidden=False,
                    title_font=self.font_card_title,
                    body_font=self.font_card_body,
                    tiny_font=self.font_card_tiny,
                )
                if card_rect.collidepoint(mouse):
                    self.hovered_card = card
                    self.hovered_card_hidden_preview = False
            else:
                draw_text(surface, self.font_small, "Empty", cell_rect.x + 10, cell_rect.y + 8, MUTED)
            draw_text(surface, self.font_small, f"S{slot}", cell_rect.x + 6, cell_rect.y + 4, INFO)
            for lidx, (label, color) in enumerate(assignment_labels.get(slot, [])[:2]):
                badge_w, badge_h = badge_style(label)
                badge = pygame.Rect(cell_rect.right - badge_w - 4, cell_rect.y + 4 + lidx * 20, badge_w, badge_h)
                draw_assignment_badge(badge, label, color)
            self.click_map.append((cell_rect, lambda s=slot: self._on_slot_click(s)))

        for pidx, target_rect in ((0, left_target), (1, right_target)):
            key = f"barracks:{pidx}"
            fill = (73, 80, 98)
            if key in legal_targets and deployment_preview:
                fill = (82, 118, 100)
            glow: tuple[int, int, int] | None = None
            if self.selected_target == key:
                glow = ACCENT if key in legal_targets or not deployment_preview else INVALID_TARGET
            draw_panel(surface, target_rect, fill=fill, border=(22, 25, 33), radius=6, glow=glow)
            draw_text(
                surface,
                self.font_small,
                f"P{pidx + 1} Barracks",
                target_rect.x + 8,
                target_rect.y + 5,
                P1_COLOR if pidx == 0 else P2_COLOR,
                max_width=target_rect.width - 12,
            )
            barracks_card = self.game.players[pidx].barracks.card
            card_slot = pygame.Rect(target_rect.x + 6, target_rect.y + 20, target_rect.width - 12, target_rect.height - 26)
            card_rect = fit_card_rect(card_slot, barracks_card.card_type)
            draw_tcg_card(
                surface,
                card_rect,
                card=barracks_card,
                selected=self.selected_target == key,
                hidden=False,
                title_font=self.font_card_title,
                body_font=self.font_card_body,
                tiny_font=self.font_card_tiny,
            )
            if card_rect.collidepoint(mouse):
                self.hovered_card = barracks_card
                self.hovered_card_hidden_preview = False
            for lidx, (label, color) in enumerate(assignment_labels.get(key, [])[:2]):
                badge_w, badge_h = badge_style(label)
                badge = pygame.Rect(target_rect.right - badge_w - 4, target_rect.y + 5 + lidx * 20, badge_w, badge_h)
                draw_assignment_badge(badge, label, color)
            self.click_map.append((target_rect, lambda target_player=pidx: self._on_barracks_target_click(target_player)))

    def _draw_active_hand_panel(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        self.hand_panel_rect = rect
        self._recompute_hand_layout()
        draw_panel(surface, rect, fill=PANEL_ALT, border=(20, 24, 32), radius=8)
        active = self._active_player_index()
        player = self.game.players[active]

        draw_text(surface, self.font_body, f"Active Hand - Player {active + 1}", rect.x + 10, rect.y + 6, INFO)
        start = self.hand_scroll[active]
        total = len(player.hand)
        max_offset = max(0, total - self.hand_visible_cards)
        self.hand_scroll[active] = max(0, min(start, max_offset))
        start = self.hand_scroll[active]
        end = min(total, start + self.hand_visible_cards)

        x = rect.x + 10
        y = rect.y + 24
        for idx in range(start, end):
            card = player.hand[idx]
            card_rect = pygame.Rect(x, y, self.hand_card_width, self.hand_card_height)
            click_rect = card_rect.inflate(self.hand_card_gap, 0)
            hovered = click_rect.collidepoint(pygame.mouse.get_pos())
            if hovered:
                self.hovered_card = card
                self.hovered_card_hidden_preview = False
                card_rect = card_rect.move(0, -4)
            selected = idx == self.selected_hand_index
            draw_tcg_card(
                surface,
                card_rect,
                card=card,
                selected=selected,
                hidden=False,
                title_font=self.font_card_title,
                body_font=self.font_card_body,
                tiny_font=self.font_card_tiny,
            )
            self.click_map.append((click_rect, lambda p=active, hidx=idx: self._on_hand_click(p, hidx)))
            x += self.hand_card_width + self.hand_card_gap

        if start > 0:
            draw_text(surface, self.font_small, "< wheel for earlier", rect.x + rect.width - 220, rect.y + 8, MUTED)
        if end < total:
            draw_text(surface, self.font_small, "wheel for later >", rect.x + rect.width - 220, rect.y + 78, MUTED)

    def _draw_side_panel(self, surface: pygame.Surface) -> None:
        draw_text(surface, self.font_body, "Actions", 930, 26, TEXT)
        draw_text(surface, self.font_small, f"Selected battalion: B{self.selected_battalion + 1}", 930, 46, INFO)
        selected_hand = self.selected_hand_index if self.selected_hand_index is not None else "-"
        draw_text(surface, self.font_small, f"Selected hand index: {selected_hand}", 930, 62, INFO)
        selected_barracks = self.selected_barracks_index if self.selected_barracks_index is not None else "-"
        draw_text(surface, self.font_small, f"Selected barracks index: {selected_barracks}", 930, 78, INFO)
        draw_panel(surface, self.action_panel_rect, fill=PANEL_ALT, border=(19, 22, 30), radius=8)
        max_action_offset = self._action_scroll_limit()
        if max_action_offset > 0:
            draw_text(
                surface,
                self.font_small,
                f"{self.action_scroll}/{max_action_offset}",
                self.action_panel_rect.right - 52,
                self.action_panel_rect.y + 4,
                MUTED,
            )
        clip_prev = surface.get_clip()
        surface.set_clip(self.action_panel_rect.inflate(-2, -2))
        mouse = pygame.mouse.get_pos()
        hovered_action_label: str | None = None
        for button in self.buttons:
            if self.action_panel_rect.colliderect(button.rect):
                button.draw(
                    surface,
                    self.font_small,
                    bg=(68, 98, 141),
                    text_color=TEXT,
                    disabled_bg=(56, 60, 69),
                )
                if button.rect.collidepoint(mouse):
                    hovered_action_label = button.label
        surface.set_clip(clip_prev)
        if hovered_action_label is not None:
            tooltip = self._action_tooltip_text(hovered_action_label)
            if tooltip:
                self._draw_action_tooltip(surface, tooltip, mouse)

        preview_panel = pygame.Rect(926, 346, 338, 260)
        draw_panel(surface, preview_panel, fill=PANEL_ALT, border=(19, 22, 30), radius=8)
        draw_text(surface, self.font_small, "Card Preview", preview_panel.x + 8, preview_panel.y + 6, MUTED)

        preview_card = self.hovered_card
        preview_hidden = bool(self.hovered_card_hidden_preview and preview_card is not None)
        if preview_card is None and self.selected_hand_index is not None:
            active_hand = self._active_player().hand
            if 0 <= self.selected_hand_index < len(active_hand):
                preview_card = active_hand[self.selected_hand_index]
        if preview_card is None:
            preview_card = self._selected_barracks_card()
        if preview_card is None:
            selected_unit = self._selected_unit_target()
            if selected_unit is not None:
                _, _, preview_card = selected_unit

        if preview_card is not None:
            preview_slot = pygame.Rect(preview_panel.x + 8, preview_panel.y + 24, 140, 226)
            preview_rect = fit_card_rect(preview_slot, preview_card.card_type)
            draw_tcg_card(
                surface,
                preview_rect,
                card=preview_card,
                selected=False,
                hidden=preview_hidden,
                title_font=self.font_card_title,
                body_font=self.font_card_body,
                tiny_font=self.font_card_tiny,
            )
            detail_x = preview_slot.right + 8
            detail_w = max(40, preview_panel.right - detail_x - 8)
            detail_y = preview_panel.y + 26
            if preview_hidden:
                draw_text(surface, self.font_small, "Hidden Card", detail_x, detail_y, MUTED, max_width=detail_w)
                detail_y += 18
                lines = wrap_text(
                    self.font_small,
                    "No information available.",
                    detail_w,
                    9,
                )
            else:
                draw_text(
                    surface,
                    self.font_small,
                    truncate_text(self.font_small, preview_card.name, detail_w),
                    detail_x,
                    detail_y,
                    TEXT,
                    max_width=detail_w,
                )
                detail_y += 18

                line_value = preview_card.effective_line()
                if line_value in ("Front", "Back"):
                    draw_text(
                        surface,
                        self.font_small,
                        f"Line: {line_value}",
                        detail_x,
                        detail_y,
                        INFO,
                        max_width=detail_w,
                    )
                    detail_y += 18

                if preview_card.card_type in ("Battlefield", "Unit", "Tactic"):
                    if preview_card.card_type == "Battlefield":
                        fallback_effect = "Battlefield Effect"
                    elif preview_card.card_type == "Unit":
                        fallback_effect = "Unit Effect"
                    else:
                        fallback_effect = "Tactic Effect"
                    effect_name = preview_card.ability or fallback_effect
                    draw_text(surface, self.font_small, effect_name, detail_x, detail_y, INFO, max_width=detail_w)
                    detail_y += 18
                    details = preview_card.description or "No effect text."
                    lines = wrap_text(self.font_small, details, detail_w, 9)
                else:
                    details = preview_card.ability or preview_card.description or "No additional text."
                    lines = wrap_text(self.font_small, details, detail_w, 9)

            for idx, line in enumerate(lines):
                draw_text(surface, self.font_small, line, detail_x, detail_y + idx * 16, TEXT)
        else:
            draw_text(surface, self.font_small, "Hover a card to inspect it.", preview_panel.x + 10, preview_panel.y + 40, MUTED)

        self.log_panel_rect = pygame.Rect(926, 616, 338, 64)
        draw_panel(surface, self.log_panel_rect, fill=PANEL_ALT, border=(19, 22, 30), radius=8)
        draw_text(surface, self.font_small, "Logs (wheel to scroll)", self.log_panel_rect.x + 8, self.log_panel_rect.y + 6, MUTED)
        logs, max_offset = self.adapter.logs_window(max_lines=2, offset=self.log_scroll)
        for i, line in enumerate(logs):
            draw_text(
                surface,
                self.font_small,
                truncate_text(self.font_small, line, self.log_panel_rect.width - 16),
                self.log_panel_rect.x + 8,
                self.log_panel_rect.y + 24 + i * 15,
                TEXT,
            )
        if max_offset > 0:
            draw_text(
                surface,
                self.font_small,
                f"{self.log_scroll}/{max_offset}",
                self.log_panel_rect.right - 50,
                self.log_panel_rect.y + 6,
                MUTED,
            )

        status_color = self.adapter.status_color(self.status_text)
        draw_text(surface, self.font_small, truncate_text(self.font_small, self.status_text, 332), 930, 686, status_color)

    def _draw_tutorial_popup(self, surface: pygame.Surface) -> None:
        if self.tutorial_popup is None:
            return
        step_index, total_steps = self._tutorial_progress()
        popup_rects = draw_tutorial_popup(
            surface,
            title_font=self.tutorial_title_font,
            body_font=self.font_body,
            small_font=self.font_small,
            card=self.tutorial_popup,
            step_index=step_index,
            total_steps=total_steps,
        )
        self.tutorial_next_rect = popup_rects["next"]
        self.tutorial_skip_rect = popup_rects["skip"]

    def _draw_stack_popup(self, surface: pygame.Surface) -> None:
        if self.stack_popup is None:
            return

        blocker = surface.get_rect()
        self.click_map.append((blocker, self._close_stack_popup))

        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        overlay.fill((8, 10, 16, 155))
        surface.blit(overlay, (0, 0))

        popup = pygame.Rect(0, 0, 620, 420)
        popup.center = surface.get_rect().center
        draw_panel(surface, popup, fill=(36, 44, 58), border=(19, 22, 30), radius=12)
        self.click_map.append((popup, lambda: None))

        title = str(self.stack_popup.get("title", "Stack View"))
        draw_text(surface, self.font_title, title, popup.x + 16, popup.y + 12, TEXT, max_width=popup.width - 64)
        grave_player_raw = self.stack_popup.get("grave_player_index")
        grave_player_index = grave_player_raw if isinstance(grave_player_raw, int) else None
        row_click_raw = self.stack_popup.get("row_click")
        row_click = row_click_raw if callable(row_click_raw) else None
        pending_grave = self.game.pending_grave_pick
        grave_pick_pending = (
            pending_grave is not None
            and grave_player_index is not None
            and int(pending_grave["player"]) == grave_player_index
        )
        if grave_pick_pending:
            draw_text(
                surface,
                self.font_small,
                "Click a row to choose your grave card.",
                popup.x + 16,
                popup.y + 40,
                INFO,
                max_width=popup.width - 64,
            )
        elif row_click is not None:
            draw_text(
                surface,
                self.font_small,
                "Click a row to choose your target.",
                popup.x + 16,
                popup.y + 40,
                INFO,
                max_width=popup.width - 64,
            )

        close_btn = pygame.Rect(popup.right - 42, popup.y + 10, 28, 24)
        hovered = close_btn.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(surface, (93, 62, 66) if hovered else (76, 52, 56), close_btn, border_radius=6)
        pygame.draw.rect(surface, ACCENT, close_btn, width=1, border_radius=6)
        draw_text(surface, self.font_small, "X", close_btn.x + 9, close_btn.y + 4, TEXT)
        self.click_map.append((close_btn, self._close_stack_popup))

        preview_col_w = 188
        gutter = 10
        list_top = popup.y + (64 if (grave_pick_pending or row_click is not None) else 46)
        list_rect = pygame.Rect(
            popup.x + 14,
            list_top,
            popup.width - 28 - preview_col_w - gutter,
            popup.bottom - list_top - 14,
        )
        preview_rect = pygame.Rect(
            list_rect.right + gutter,
            list_rect.y,
            preview_col_w,
            list_rect.height,
        )
        self.stack_popup_list_rect = list_rect
        draw_panel(surface, list_rect, fill=(30, 37, 49), border=(18, 21, 28), radius=8)
        draw_panel(surface, preview_rect, fill=(30, 37, 49), border=(18, 21, 28), radius=8)
        draw_text(surface, self.font_small, "Hover Preview", preview_rect.x + 8, preview_rect.y + 6, MUTED)

        cards = self._stack_popup_cards()
        row_h = 30
        max_lines = max(1, list_rect.height // row_h)
        max_offset = max(0, len(cards) - max_lines)
        self.stack_popup_scroll = max(0, min(self.stack_popup_scroll, max_offset))

        if not cards:
            draw_text(surface, self.font_small, "No cards in this container.", list_rect.x + 10, list_rect.y + 10, MUTED)
            return

        active_player = self._active_player_index()
        owner_raw = self.stack_popup.get("owner_index")
        owner_index = owner_raw if isinstance(owner_raw, int) else None
        conceal_unrevealed = bool(self.stack_popup.get("conceal_unrevealed_for_opponents", False))
        mouse = pygame.mouse.get_pos()
        hovered_stack_card: object | None = None
        hovered_stack_hidden = False

        start = self.stack_popup_scroll
        end = min(len(cards), start + max_lines)
        for row, idx in enumerate(range(start, end)):
            card = cards[idx]
            row_rect = pygame.Rect(list_rect.x + 8, list_rect.y + 6 + row * row_h, list_rect.width - 16, row_h - 4)
            concealed_row = (
                conceal_unrevealed
                and owner_index is not None
                and owner_index != active_player
                and not bool(getattr(card, "revealed", True))
            )
            row_hovered = row_rect.collidepoint(mouse)
            if row_hovered:
                hovered_stack_card = card
                hovered_stack_hidden = concealed_row
            fill = (61, 73, 94) if row_hovered else ((54, 64, 82) if row % 2 == 0 else (47, 57, 74))
            pygame.draw.rect(surface, fill, row_rect, border_radius=5)
            pygame.draw.rect(surface, (20, 24, 32), row_rect, width=1, border_radius=5)
            if row_click is not None:
                self.click_map.append((row_rect, lambda f=row_click, i=idx: f(i)))
            elif grave_player_index is not None:
                self.click_map.append(
                    (
                        row_rect,
                        lambda p=grave_player_index, g=idx: self._on_grave_popup_row_click(p, g),
                    )
                )

            if concealed_row:
                name = "Hidden Card"
                ctype = ""
                line = None
            else:
                name = getattr(card, "name", str(card))
                ctype = getattr(card, "card_type", "")
                line = getattr(card, "line", None)
            right_bits = [bit for bit in (ctype, line) if bit]
            right_text = " | ".join(right_bits) if right_bits else "-"
            right_meta_w = min(132, max(88, row_rect.width // 3))
            name_max_w = max(40, row_rect.width - right_meta_w - 14)

            draw_text(
                surface,
                self.font_small,
                f"{idx + 1}. {truncate_text(self.font_small, str(name), name_max_w)}",
                row_rect.x + 8,
                row_rect.y + 6,
                TEXT,
                max_width=name_max_w,
            )
            draw_text(
                surface,
                self.font_small,
                truncate_text(self.font_small, right_text, right_meta_w),
                row_rect.right - right_meta_w - 4,
                row_rect.y + 6,
                MUTED,
                max_width=right_meta_w,
            )

        if hovered_stack_card is None:
            draw_text(
                surface,
                self.font_small,
                "Hover a row to preview card art.",
                preview_rect.x + 10,
                preview_rect.y + 28,
                MUTED,
                max_width=preview_rect.width - 20,
            )
        elif hasattr(hovered_stack_card, "card_type"):
            card_slot = pygame.Rect(
                preview_rect.x + 10,
                preview_rect.y + 28,
                preview_rect.width - 20,
                preview_rect.height - 64,
            )
            if card_slot.width * 7 <= card_slot.height * 5:
                card_w = card_slot.width
                card_h = max(1, int(card_w * 7 / 5))
            else:
                card_h = card_slot.height
                card_w = max(1, int(card_h * 5 / 7))
            card_rect = pygame.Rect(
                card_slot.x + (card_slot.width - card_w) // 2,
                card_slot.y + (card_slot.height - card_h) // 2,
                card_w,
                card_h,
            )
            draw_tcg_card(
                surface,
                card_rect,
                card=hovered_stack_card,
                selected=False,
                hidden=hovered_stack_hidden,
                title_font=self.font_card_title,
                body_font=self.font_card_body,
                tiny_font=self.font_card_tiny,
            )
            preview_label = "Hidden Card" if hovered_stack_hidden else str(getattr(hovered_stack_card, "name", "Card"))
            draw_text(
                surface,
                self.font_small,
                truncate_text(self.font_small, preview_label, preview_rect.width - 20),
                preview_rect.x + 10,
                preview_rect.bottom - 26,
                MUTED if hovered_stack_hidden else TEXT,
                max_width=preview_rect.width - 20,
            )

        if max_offset > 0:
            draw_text(
                surface,
                self.font_small,
                f"{self.stack_popup_scroll}/{max_offset}  (wheel)",
                list_rect.right - 120,
                list_rect.y + 8,
                MUTED,
            )

    def _draw_profitable_standoff_popup(self, surface: pygame.Surface) -> None:
        owner = self.game.pending_profitable_standoff_draw_player
        if self.game.phase != "draw" or owner is None:
            return
        player = self.game.players[owner]
        if len(player.deck) < 2:
            return

        blocker = surface.get_rect()
        self.click_map.append((blocker, lambda: None))

        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        overlay.fill((8, 10, 16, 170))
        surface.blit(overlay, (0, 0))

        popup = pygame.Rect(0, 0, 620, 330)
        popup.center = surface.get_rect().center
        draw_panel(surface, popup, fill=(36, 44, 58), border=(19, 22, 30), radius=12)
        draw_text(surface, self.font_title, "Profitable Standoff", popup.x + 16, popup.y + 14, TEXT)
        draw_text(
            surface,
            self.font_small,
            f"Player {owner + 1}: Choose which of the top 2 cards stays on top.",
            popup.x + 16,
            popup.y + 46,
            INFO,
            max_width=popup.width - 32,
        )
        draw_text(
            surface,
            self.font_small,
            "Then draw the top card now. The other remains second from top.",
            popup.x + 16,
            popup.y + 64,
            INFO,
            max_width=popup.width - 32,
        )

        left_slot = pygame.Rect(popup.x + 42, popup.y + 92, 236, 172)
        right_slot = pygame.Rect(popup.right - 42 - 236, popup.y + 92, 236, 172)
        top_two = player.deck[:2]

        for idx, slot in enumerate((left_slot, right_slot)):
            card = top_two[idx]
            hover = slot.collidepoint(pygame.mouse.get_pos())
            draw_panel(
                surface,
                slot,
                fill=(44, 54, 70),
                border=(22, 26, 34),
                radius=9,
                glow=ACCENT if hover else None,
            )
            card_rect = fit_card_rect(slot.inflate(-8, -8), card.card_type)
            draw_tcg_card(
                surface,
                card_rect,
                card=card,
                selected=False,
                hidden=False,
                title_font=self.font_card_title,
                body_font=self.font_card_body,
                tiny_font=self.font_card_tiny,
            )
            choose_btn = pygame.Rect(slot.x + 26, popup.bottom - 46, slot.width - 52, 30)
            hovered_btn = choose_btn.collidepoint(pygame.mouse.get_pos())
            fill = (84, 119, 168) if hovered_btn else (67, 95, 134)
            pygame.draw.rect(surface, fill, choose_btn, border_radius=8)
            pygame.draw.rect(surface, ACCENT, choose_btn, width=1, border_radius=8)
            draw_text(surface, self.font_small, "Put On Top", choose_btn.x + 34, choose_btn.y + 7, TEXT)
            self.click_map.append((choose_btn, lambda i=idx: self._btn_choose_profitable_standoff(i)))

    def _draw_deploy_roll_popup(self, surface: pygame.Surface) -> None:
        chooser = self.game.pending_first_deployer_choice
        roll = self.game.pending_siege_roll
        if self.game.phase != "siege" or chooser is None or roll is None:
            return

        blocker = surface.get_rect()
        self.click_map.append((blocker, lambda: None))

        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        overlay.fill((8, 10, 16, 170))
        surface.blit(overlay, (0, 0))

        popup = pygame.Rect(0, 0, 560, 320)
        popup.center = surface.get_rect().center
        draw_panel(surface, popup, fill=(36, 44, 58), border=(19, 22, 30), radius=12)
        draw_text(surface, self.font_title, "Siege Roll", popup.x + 16, popup.y + 14, TEXT)
        draw_text(
            surface,
            self.font_small,
            "Higher die chooses who deploys battalions first.",
            popup.x + 16,
            popup.y + 44,
            INFO,
            max_width=popup.width - 32,
        )

        p1_roll = int(roll.get("p1", 0))
        p2_roll = int(roll.get("p2", 0))
        winner = int(roll.get("winner", chooser))

        dice_w = 180
        dice_h = 120
        left_die = pygame.Rect(popup.x + 40, popup.y + 78, dice_w, dice_h)
        right_die = pygame.Rect(popup.right - 40 - dice_w, popup.y + 78, dice_w, dice_h)
        for idx, die_rect, value, color in (
            (0, left_die, p1_roll, P1_COLOR),
            (1, right_die, p2_roll, P2_COLOR),
        ):
            draw_panel(surface, die_rect, fill=(58, 70, 89), border=(22, 26, 34), radius=10, glow=color)
            draw_text(surface, self.font_body, f"Player {idx + 1}", die_rect.x + 12, die_rect.y + 10, color)
            draw_text(surface, self.font_title, str(value), die_rect.x + die_rect.width // 2 - 8, die_rect.y + 46, TEXT)

        draw_text(
            surface,
            self.font_body,
            f"Player {winner + 1} rolled higher and chooses first deployer.",
            popup.x + 16,
            popup.y + 212,
            TEXT,
            max_width=popup.width - 32,
        )

        btn_w = 210
        btn_h = 34
        btn_y = popup.bottom - 50
        p1_btn = pygame.Rect(popup.x + 34, btn_y, btn_w, btn_h)
        p2_btn = pygame.Rect(popup.right - 34 - btn_w, btn_y, btn_w, btn_h)
        for chosen, btn_rect, label in (
            (0, p1_btn, "Player 1 Deploys First"),
            (1, p2_btn, "Player 2 Deploys First"),
        ):
            hovered = btn_rect.collidepoint(pygame.mouse.get_pos())
            fill = (84, 119, 168) if hovered else (67, 95, 134)
            pygame.draw.rect(surface, fill, btn_rect, border_radius=8)
            pygame.draw.rect(surface, ACCENT, btn_rect, width=1, border_radius=8)
            draw_text(surface, self.font_small, label, btn_rect.x + 12, btn_rect.y + 8, TEXT)
            self.click_map.append((btn_rect, lambda c=chosen: self._btn_choose_first(c)))

    def _draw_siege_report_popup(self, surface: pygame.Surface) -> None:
        if self.siege_report_popup is None:
            return

        blocker = surface.get_rect()
        self.click_map.append((blocker, lambda: None))

        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        overlay.fill((8, 10, 16, 175))
        surface.blit(overlay, (0, 0))

        popup = pygame.Rect(0, 0, 1080, 640)
        popup.center = surface.get_rect().center
        draw_panel(surface, popup, fill=(36, 44, 58), border=(19, 22, 30), radius=12)
        self.click_map.append((popup, lambda: None))

        title = str(self.siege_report_popup.get("title", "Siege Results"))
        draw_text(surface, self.font_title, title, popup.x + 16, popup.y + 12, TEXT, max_width=popup.width - 120)
        draw_text(
            surface,
            self.font_small,
            "Each card shows base M/W from the card used; modified attack is shown separately when changed.",
            popup.x + 16,
            popup.y + 42,
            INFO,
            max_width=popup.width - 32,
        )

        close_btn = pygame.Rect(popup.right - 42, popup.y + 10, 28, 24)
        hovered_close = close_btn.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(surface, (93, 62, 66) if hovered_close else (76, 52, 56), close_btn, border_radius=6)
        pygame.draw.rect(surface, ACCENT, close_btn, width=1, border_radius=6)
        draw_text(surface, self.font_small, "X", close_btn.x + 9, close_btn.y + 4, TEXT)
        self.click_map.append((close_btn, self._close_siege_report_popup))

        list_rect = pygame.Rect(popup.x + 14, popup.y + 66, popup.width - 28, popup.height - 124)
        self.siege_report_list_rect = list_rect
        draw_panel(surface, list_rect, fill=(30, 37, 49), border=(18, 21, 28), radius=8)

        lines = self._siege_report_popup_lines()
        if not lines:
            draw_text(
                surface,
                self.font_small,
                "No siege data available.",
                list_rect.x + 10,
                list_rect.y + 10,
                MUTED,
                max_width=list_rect.width - 20,
            )
        else:
            row_h = 18
            max_lines = max(1, list_rect.height // row_h)
            max_offset = max(0, len(lines) - max_lines)
            self.siege_report_scroll = max(0, min(self.siege_report_scroll, max_offset))

            start = self.siege_report_scroll
            end = min(len(lines), start + max_lines)
            for row, idx in enumerate(range(start, end)):
                line = lines[idx]
                stripped = line.strip()
                color = TEXT
                if stripped.startswith("Slot ") or stripped.startswith("Barracks"):
                    color = INFO
                elif stripped.startswith("Control:"):
                    color = MUTED
                elif stripped.startswith("Dead |"):
                    color = P2_COLOR
                draw_text(
                    surface,
                    self.font_small,
                    truncate_text(self.font_small, line, list_rect.width - 16),
                    list_rect.x + 8,
                    list_rect.y + 4 + row * row_h,
                    color,
                    max_width=list_rect.width - 16,
                )

            if max_offset > 0:
                draw_text(
                    surface,
                    self.font_small,
                    f"{self.siege_report_scroll}/{max_offset}  (wheel)",
                    list_rect.right - 132,
                    list_rect.y + 6,
                    MUTED,
                )

        continue_btn = pygame.Rect(popup.right - 182, popup.bottom - 46, 166, 30)
        hovered_continue = continue_btn.collidepoint(pygame.mouse.get_pos())
        fill = (84, 119, 168) if hovered_continue else (67, 95, 134)
        pygame.draw.rect(surface, fill, continue_btn, border_radius=8)
        pygame.draw.rect(surface, ACCENT, continue_btn, width=1, border_radius=8)
        draw_text(surface, self.font_small, "Continue", continue_btn.x + 52, continue_btn.y + 7, TEXT)
        self.click_map.append((continue_btn, self._close_siege_report_popup))
