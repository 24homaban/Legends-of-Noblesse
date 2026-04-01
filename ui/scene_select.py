from __future__ import annotations

import math
from typing import Callable

import pygame

from game.card_loader import create_card
from game.game import Game
from game.models import Card
from game.premade_decks import PREMADE_DECKS, validate_deck_map
from game.selection_data import CUSTOM_DECK_NAME, setup_options
from .constants import ACCENT, INFO, MUTED, PANEL, PANEL_ALT, PANEL_SOFT, TEXT
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


class SelectScene(SceneBase):
    def __init__(self, app: "PygameApp"):
        super().__init__(app)
        self.font_small = pygame.font.SysFont("segoe ui", 15)
        self.font_body = pygame.font.SysFont("segoe ui", 18)
        self.font_title = pygame.font.SysFont("cambria", 31, bold=True)
        self.font_subtitle = pygame.font.SysFont("cambria", 20, bold=True)
        self.font_tiny = pygame.font.SysFont("segoe ui", 12)
        self.font_card_title = pygame.font.SysFont("cambria", 16, bold=True)
        self.font_card_body = pygame.font.SysFont("segoe ui", 13)
        self.font_card_tiny = pygame.font.SysFont("segoe ui", 12)
        self.time = 0.0

        self.options = setup_options()
        self.stage = "select"
        self.steps = ("deck", "class", "barracks", "battlefields")
        self.step_idx = 0
        self.player_cursor = 0
        self.choices: list[dict[str, object]] = [
            {"deck": None, "class": None, "barracks": None, "battlefields": [], "custom_deck": {}},
            {"deck": None, "class": None, "barracks": None, "battlefields": [], "custom_deck": {}},
        ]

        self.card_cache: dict[str, Card] = {}
        self.hovered_card: Card | None = None
        self.custom_scroll = {0: 0, 1: 0}
        self.custom_list_rect: pygame.Rect | None = None
        self.custom_row_h = 28

        self.placement_player = 0
        self.placement_remaining: dict[int, list[str]] = {0: [], 1: []}
        self.selected_placement_card: str | None = None
        self.placements: list[dict[str, object]] = []

        self.click_map: list[tuple[pygame.Rect, Callable[[], None]]] = []
        self.set_status("Configure Player 1. Step 1/4: Deck.")
        self.tutorial_title_font = pygame.font.SysFont("cambria", 30, bold=True)
        self.tutorial_popup: TutorialCard | None = None
        self.tutorial_next_rect = pygame.Rect(0, 0, 0, 0)
        self.tutorial_skip_rect = pygame.Rect(0, 0, 0, 0)
        self._refresh_tutorial_popup()

    def _register_click(self, rect: pygame.Rect, callback: Callable[[], None]) -> None:
        self.click_map.append((rect, callback))

    def _tutorial_active(self) -> bool:
        return self.tutorial_popup is not None

    def _tutorial_progress(self) -> tuple[int, int]:
        if self.tutorial_popup is None:
            return (1, 2)
        if self.tutorial_popup.key == "setup_overview":
            return (1, 2)
        return (2, 2)

    def _refresh_tutorial_popup(self) -> None:
        if self.tutorial_popup is not None or not self.app.tutorial_enabled:
            return
        if self.stage == "select" and self.app.tutorial_pending("setup_overview"):
            self.tutorial_popup = TutorialCard(
                key="setup_overview",
                title="Setup Walkthrough",
                lines=(
                    "For each player, finish 4 setup steps: Deck, Class, Barracks, and 3 Battlefields.",
                    "Press Enter for next step, Backspace for previous, or use the side panel buttons.",
                    "Battlefields must be exactly 3 before you can save a player.",
                    "After both players are saved, you move into battlefield placement.",
                ),
                continue_label="Continue",
            )
            return
        if self.stage == "placement" and self.app.tutorial_pending("placement_overview"):
            self.tutorial_popup = TutorialCard(
                key="placement_overview",
                title="Placement Walkthrough",
                lines=(
                    "Before combat, players place the 6 battlefield cards onto the board.",
                    "Current player: select one remaining battlefield on the left, then click an empty slot.",
                    "Players alternate until all 6 slots are filled.",
                    "After placement, the match begins and your first turn starts in Draw phase.",
                ),
                continue_label="Begin Match",
            )

    def _advance_tutorial_popup(self) -> None:
        if self.tutorial_popup is None:
            return
        self.app.mark_tutorial_seen(self.tutorial_popup.key)
        self.tutorial_popup = None
        self.tutorial_next_rect = pygame.Rect(0, 0, 0, 0)
        self.tutorial_skip_rect = pygame.Rect(0, 0, 0, 0)
        self._refresh_tutorial_popup()

    def _skip_tutorial_popup(self) -> None:
        self.app.skip_all_tutorials()
        self.tutorial_popup = None
        self.tutorial_next_rect = pygame.Rect(0, 0, 0, 0)
        self.tutorial_skip_rect = pygame.Rect(0, 0, 0, 0)

    def handle_event(self, event: pygame.event.Event) -> None:
        if self._tutorial_active():
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    self._advance_tutorial_popup()
                    return
                if event.key == pygame.K_ESCAPE:
                    self._skip_tutorial_popup()
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
            if self.stage == "select" and event.key == pygame.K_RETURN:
                self._next_step()
                return
            if self.stage == "select" and event.key == pygame.K_BACKSPACE:
                self._prev_step()
                return
            if self.stage == "placement" and event.key == pygame.K_ESCAPE:
                self.selected_placement_card = None
                self.set_status("Placement card selection cleared.")
                return

        if event.type == pygame.MOUSEWHEEL and self.stage == "select":
            if self._handle_custom_wheel(event.y):
                return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for rect, callback in reversed(self.click_map):
                if rect.collidepoint(event.pos):
                    callback()
                    return

    def update(self, dt: float) -> None:
        self.time += dt
        self._refresh_tutorial_popup()

    def draw(self, surface: pygame.Surface) -> None:
        self.click_map = []
        self.custom_list_rect = None
        self.hovered_card = None
        draw_board_background(surface, self.time)

        if self.stage == "select":
            self._draw_select_stage(surface)
        else:
            self._draw_placement_stage(surface)

        status_box = pygame.Rect(16, 682, 1248, 26)
        draw_panel(surface, status_box, fill=PANEL_ALT, border=(18, 22, 31), radius=8)
        draw_text(
            surface,
            self.font_body,
            truncate_text(self.font_body, self.status_text, status_box.width - 16),
            24,
            686,
            ACCENT,
        )
        if self._tutorial_active() and self.tutorial_popup is not None:
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

    def _draw_option_item(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        label: str,
        selected: bool,
        on_click: Callable[[], None],
    ) -> None:
        hovered = rect.collidepoint(pygame.mouse.get_pos())
        fill = (70, 98, 135) if selected else PANEL_ALT
        if hovered and not selected:
            fill = PANEL_SOFT
        pygame.draw.rect(surface, fill, rect, border_radius=7)
        pygame.draw.rect(surface, ACCENT if selected else (21, 24, 31), rect, width=2 if selected else 1, border_radius=7)
        draw_text(surface, self.font_small, truncate_text(self.font_small, label, rect.width - 16), rect.x + 7, rect.y + 7, TEXT if selected else MUTED)
        self._register_click(rect, on_click)

    def _draw_button(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        label: str,
        *,
        enabled: bool,
        callback: Callable[[], None],
    ) -> None:
        hovered = enabled and rect.collidepoint(pygame.mouse.get_pos())
        fill = (78, 111, 153) if enabled else (54, 61, 74)
        if hovered:
            fill = (93, 129, 176)
        pygame.draw.rect(surface, fill, rect, border_radius=7)
        pygame.draw.rect(surface, ACCENT if enabled else (24, 29, 40), rect, width=1, border_radius=7)
        draw_text(surface, self.font_small, truncate_text(self.font_small, label, rect.width - 14), rect.x + 7, rect.y + 7, TEXT if enabled else MUTED)
        if enabled:
            self._register_click(rect, callback)

    def _step(self) -> str:
        return self.steps[self.step_idx]

    def _step_title(self, step: str) -> str:
        if step == "deck":
            return "Deck"
        if step == "class":
            return "Class"
        if step == "barracks":
            return "Barracks"
        return "Battlefields"

    def _deck_name(self, player_index: int) -> str | None:
        deck = self.choices[player_index]["deck"]
        return deck if isinstance(deck, str) else None

    def _custom_map(self, player_index: int) -> dict[str, int]:
        raw = self.choices[player_index]["custom_deck"]
        if not isinstance(raw, dict):
            self.choices[player_index]["custom_deck"] = {}
            return {}
        clean: dict[str, int] = {}
        for name, count in raw.items():
            if isinstance(name, str) and isinstance(count, int) and count > 0:
                clean[name] = count
        self.choices[player_index]["custom_deck"] = clean
        return clean

    def _custom_total(self, player_index: int) -> int:
        return sum(self._custom_map(player_index).values())

    def _deck_payload(self, player_index: int) -> str | dict[str, int]:
        name = self._deck_name(player_index)
        if name == CUSTOM_DECK_NAME:
            return dict(self._custom_map(player_index))
        if name is None:
            raise ValueError("Deck missing.")
        return name

    def _card(self, name: str) -> Card | None:
        if name in self.card_cache:
            return self.card_cache[name]
        try:
            card = create_card(name, owner_index=self.player_cursor, revealed=True)
        except KeyError:
            return None
        card.revealed = True
        self.card_cache[name] = card
        return card

    def _validate_step(self) -> tuple[bool, str]:
        c = self.choices[self.player_cursor]
        step = self._step()
        if step == "deck":
            deck = self._deck_name(self.player_cursor)
            if not deck:
                return False, "Select a deck to continue."
            if deck == CUSTOM_DECK_NAME:
                ok, msg = validate_deck_map(self._custom_map(self.player_cursor))
                if not ok:
                    return False, f"Custom deck invalid: {msg}"
            return True, "Deck confirmed."
        if step == "class":
            return (True, "Class confirmed.") if c["class"] else (False, "Select a class.")
        if step == "barracks":
            return (True, "Barracks confirmed.") if c["barracks"] else (False, "Select a barracks.")
        b = c["battlefields"]
        assert isinstance(b, list)
        return (True, "Battlefields confirmed.") if len(b) == 3 else (False, "Select exactly 3 battlefields.")

    def _next_step(self) -> None:
        ok, msg = self._validate_step()
        if not ok:
            self.set_status(msg)
            return
        if self.step_idx < len(self.steps) - 1:
            self.step_idx += 1
            self.set_status(f"{msg} Step {self.step_idx + 1}/4: {self._step_title(self._step())}.")
            return
        if self.player_cursor == 0:
            self.player_cursor = 1
            self.step_idx = 0
            self.set_status("Player 1 saved. Configure Player 2. Step 1/4: Deck.")
            return
        self.stage = "placement"
        self.placement_player = 0
        self.placement_remaining = {
            0: list(self.choices[0]["battlefields"]),  # type: ignore[arg-type]
            1: list(self.choices[1]["battlefields"]),  # type: ignore[arg-type]
        }
        self.selected_placement_card = None
        self.placements = []
        self.set_status("Placement started. Select a battlefield, then click an empty slot.")

    def _prev_step(self) -> None:
        if self.step_idx == 0:
            self.set_status("Already at the first setup step.")
            return
        self.step_idx -= 1
        self.set_status(f"Step {self.step_idx + 1}/4: {self._step_title(self._step())}.")

    def _set_choice(self, key: str, value: str) -> None:
        self.choices[self.player_cursor][key] = value
        if key == "deck" and value == CUSTOM_DECK_NAME:
            self.set_status(f"Selected Custom Deck ({self._custom_total(self.player_cursor)}/30).")
            return
        self.set_status(f"Selected {key}: {value}")

    def _toggle_battlefield(self, value: str) -> None:
        selected = self.choices[self.player_cursor]["battlefields"]
        assert isinstance(selected, list)
        if value in selected:
            selected.remove(value)
        else:
            if len(selected) >= 3:
                self.set_status("Exactly 3 battlefields are required.")
                return
            selected.append(value)
        self.set_status(f"Battlefields selected: {len(selected)}/3")

    def _clear_battlefields(self) -> None:
        selected = self.choices[self.player_cursor]["battlefields"]
        assert isinstance(selected, list)
        selected.clear()
        self.set_status("Battlefield selection cleared.")

    def _handle_custom_wheel(self, wheel_delta: int) -> bool:
        if self.custom_list_rect is None:
            return False
        if not self.custom_list_rect.collidepoint(pygame.mouse.get_pos()):
            return False
        if self._deck_name(self.player_cursor) != CUSTOM_DECK_NAME:
            return False
        visible = max(1, self.custom_list_rect.height // self.custom_row_h)
        max_scroll = max(0, len(self.options["deck_cards"]) - visible)
        current = self.custom_scroll[self.player_cursor]
        self.custom_scroll[self.player_cursor] = max(0, min(max_scroll, current - wheel_delta))
        return True

    def _adjust_custom_card(self, name: str, delta: int) -> None:
        if self._deck_name(self.player_cursor) != CUSTOM_DECK_NAME:
            self.set_status("Select Custom Deck first.")
            return
        deck = self._custom_map(self.player_cursor)
        current = deck.get(name, 0)
        total = sum(deck.values())
        if delta > 0:
            if current >= 4:
                self.set_status(f"{name} already at 4 copies.")
                return
            if total >= 30:
                self.set_status("Custom deck already has 30 cards.")
                return
            deck[name] = current + 1
        else:
            if current <= 0:
                return
            if current == 1:
                deck.pop(name, None)
            else:
                deck[name] = current - 1
        self.set_status(f"Custom deck: {self._custom_total(self.player_cursor)}/30")

    def _draw_select_stage(self, surface: pygame.Surface) -> None:
        draw_text(surface, self.font_title, "Legends of Noblesse", 24, 20, TEXT)
        draw_text(
            surface,
            self.font_body,
            f"Setup | Player {self.player_cursor + 1} | Step {self.step_idx + 1}/4: {self._step_title(self._step())}",
            26,
            56,
            INFO,
        )
        draw_text(surface, self.font_small, "Enter: next step | Backspace: previous step", 26, 82, MUTED)

        content = pygame.Rect(20, 108, 940, 564)
        summary = pygame.Rect(972, 108, 292, 564)
        draw_panel(surface, content, fill=PANEL, border=(19, 22, 30), radius=10)

        step = self._step()
        if step == "deck":
            self._draw_deck_step(surface, content)
        elif step == "class":
            selected = {str(self.choices[self.player_cursor]["class"])} if self.choices[self.player_cursor]["class"] else set()
            self._draw_card_step(surface, content, "Choose Class", "Pick one class card.", self.options["classes"], selected, lambda n: self._set_choice("class", n))
        elif step == "barracks":
            selected = {str(self.choices[self.player_cursor]["barracks"])} if self.choices[self.player_cursor]["barracks"] else set()
            self._draw_card_step(surface, content, "Choose Barracks", "Pick one barracks card.", self.options["barracks"], selected, lambda n: self._set_choice("barracks", n))
        else:
            self._draw_battlefield_step(surface, content)

        self._draw_summary(surface, summary)

    def _draw_deck_step(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        draw_text(surface, self.font_subtitle, "Choose Deck", rect.x + 12, rect.y + 10, TEXT)
        draw_text(surface, self.font_small, "Premade deck or custom 30-card deck.", rect.x + 12, rect.y + 36, INFO)

        left = pygame.Rect(rect.x + 10, rect.y + 58, 296, rect.height - 68)
        right = pygame.Rect(left.right + 12, rect.y + 58, rect.right - left.right - 22, rect.height - 68)
        draw_panel(surface, left, fill=PANEL_ALT, border=(20, 24, 32), radius=8)

        y = left.y + 10
        for deck_name in self.options["decks"]:
            label = deck_name if deck_name != CUSTOM_DECK_NAME else f"{deck_name} ({self._custom_total(self.player_cursor)}/30)"
            item = pygame.Rect(left.x + 10, y, left.width - 20, 30)
            self._draw_option_item(surface, item, label, self._deck_name(self.player_cursor) == deck_name, lambda d=deck_name: self._set_choice("deck", d))
            y += 36

        selected = self._deck_name(self.player_cursor)
        if selected is None:
            draw_panel(surface, right, fill=PANEL_ALT, border=(20, 24, 32), radius=8)
            draw_text(surface, self.font_body, "Select a deck to view cards.", right.x + 14, right.y + 14, MUTED)
            return
        if selected == CUSTOM_DECK_NAME:
            self._draw_custom_builder(surface, right)
            return

        draw_panel(surface, right, fill=PANEL_ALT, border=(20, 24, 32), radius=8)
        deck_map = PREMADE_DECKS.get(selected, {})
        draw_text(surface, self.font_subtitle, truncate_text(self.font_subtitle, selected, right.width - 16), right.x + 8, right.y + 8, TEXT)
        draw_text(surface, self.font_small, f"{sum(deck_map.values())} cards", right.x + 8, right.y + 34, INFO)
        names = [name for name, _ in sorted(deck_map.items(), key=lambda x: (-x[1], x[0]))]
        self._draw_card_grid(surface, pygame.Rect(right.x + 6, right.y + 54, right.width - 12, right.height - 60), names, set(), lambda _: None, 3, counts=deck_map)

    def _draw_custom_builder(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        draw_panel(surface, rect, fill=PANEL_ALT, border=(20, 24, 32), radius=8)
        draw_text(surface, self.font_subtitle, "Custom Deck Builder", rect.x + 8, rect.y + 8, TEXT)
        draw_text(surface, self.font_small, f"Total: {self._custom_total(self.player_cursor)}/30 (max 4 each)", rect.x + 8, rect.y + 34, INFO)

        list_rect = pygame.Rect(rect.x + 8, rect.y + 54, rect.width - 16, rect.height - 62)
        draw_panel(surface, list_rect, fill=PANEL, border=(18, 22, 30), radius=7)
        self.custom_list_rect = list_rect
        pool = self.options["deck_cards"]
        deck = self._custom_map(self.player_cursor)
        visible = max(1, list_rect.height // self.custom_row_h)
        max_scroll = max(0, len(pool) - visible)
        scroll = max(0, min(max_scroll, self.custom_scroll[self.player_cursor]))
        self.custom_scroll[self.player_cursor] = scroll
        end = min(len(pool), scroll + visible)

        for row, idx in enumerate(range(scroll, end)):
            name = pool[idx]
            count = deck.get(name, 0)
            r = pygame.Rect(list_rect.x + 4, list_rect.y + 4 + row * self.custom_row_h, list_rect.width - 8, self.custom_row_h - 2)
            hovered = r.collidepoint(pygame.mouse.get_pos())
            if hovered:
                card = self._card(name)
                if card is not None:
                    self.hovered_card = card
            fill = (66, 92, 124) if count > 0 else (45, 53, 69)
            if hovered:
                fill = (82, 112, 147)
            pygame.draw.rect(surface, fill, r, border_radius=5)
            pygame.draw.rect(surface, (18, 21, 29), r, width=1, border_radius=5)
            draw_text(surface, self.font_small, truncate_text(self.font_small, name, r.width - 84), r.x + 6, r.y + 5, TEXT if count > 0 else MUTED)
            minus = pygame.Rect(r.right - 66, r.y + 4, 18, 18)
            cbox = pygame.Rect(r.right - 44, r.y + 4, 20, 18)
            plus = pygame.Rect(r.right - 22, r.y + 4, 18, 18)
            for b in (minus, plus):
                pygame.draw.rect(surface, (90, 112, 140), b, border_radius=4)
                pygame.draw.rect(surface, (18, 21, 29), b, width=1, border_radius=4)
            pygame.draw.rect(surface, (33, 39, 50), cbox, border_radius=4)
            pygame.draw.rect(surface, (18, 21, 29), cbox, width=1, border_radius=4)
            draw_text(surface, self.font_small, "-", minus.x + 6, minus.y + 1, TEXT)
            draw_text(surface, self.font_small, str(count), cbox.x + 5, cbox.y + 1, TEXT)
            draw_text(surface, self.font_small, "+", plus.x + 5, plus.y + 1, TEXT)
            self._register_click(minus, lambda n=name: self._adjust_custom_card(n, -1))
            self._register_click(plus, lambda n=name: self._adjust_custom_card(n, 1))

    def _draw_card_step(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        title: str,
        subtitle: str,
        names: list[str],
        selected: set[str],
        on_select: Callable[[str], None],
    ) -> None:
        draw_text(surface, self.font_subtitle, title, rect.x + 12, rect.y + 10, TEXT)
        draw_text(surface, self.font_small, subtitle, rect.x + 12, rect.y + 36, INFO)
        self._draw_card_grid(surface, pygame.Rect(rect.x + 8, rect.y + 54, rect.width - 16, rect.height - 60), names, selected, on_select, 3)

    def _draw_battlefield_step(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        selected = self.choices[self.player_cursor]["battlefields"]
        assert isinstance(selected, list)
        draw_text(surface, self.font_subtitle, "Choose Battlefields", rect.x + 12, rect.y + 10, TEXT)
        draw_text(surface, self.font_small, f"Select exactly 3 ({len(selected)}/3).", rect.x + 12, rect.y + 36, INFO)
        self._draw_button(surface, pygame.Rect(rect.right - 170, rect.y + 10, 160, 30), "Clear", enabled=bool(selected), callback=self._clear_battlefields)
        self._draw_card_grid(surface, pygame.Rect(rect.x + 8, rect.y + 54, rect.width - 16, rect.height - 60), self.options["battlefields"], set(selected), self._toggle_battlefield, 3)

    def _draw_card_grid(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        names: list[str],
        selected: set[str],
        on_select: Callable[[str], None],
        cols: int,
        *,
        counts: dict[str, int] | None = None,
    ) -> None:
        if not names:
            draw_text(surface, self.font_small, "No cards.", rect.x + 8, rect.y + 8, MUTED)
            return
        gap = 10
        rows = max(1, math.ceil(len(names) / cols))
        w = max(120, (rect.width - gap * (cols + 1)) // cols)
        h = max(110, min(220, (rect.height - gap * (rows + 1)) // rows))
        for idx, name in enumerate(names):
            r = idx // cols
            c = idx % cols
            slot_rect = pygame.Rect(rect.x + gap + c * (w + gap), rect.y + gap + r * (h + gap), w, h)
            if slot_rect.bottom > rect.bottom:
                continue
            card = self._card(name)
            if card is None:
                continue
            padding = 0 if card.card_type in ("Class", "Barracks") else 2
            card_rect = fit_card_rect(slot_rect, card.card_type, padding=padding)
            click_rect = slot_rect.inflate(-2, -2)
            hovered = click_rect.collidepoint(pygame.mouse.get_pos())
            draw_rect = card_rect.move(0, -3) if hovered else card_rect
            draw_tcg_card(surface, draw_rect, card=card, selected=name in selected, hidden=False, title_font=self.font_card_title, body_font=self.font_card_body, tiny_font=self.font_card_tiny)
            if hovered:
                self.hovered_card = card
            self._register_click(click_rect, lambda n=name: on_select(n))
            if counts is not None:
                ct = counts.get(name, 0)
                badge = pygame.Rect(draw_rect.right - 28, draw_rect.y + 4, 24, 16)
                pygame.draw.rect(surface, (232, 196, 112), badge, border_radius=6)
                pygame.draw.rect(surface, (22, 24, 33), badge, width=1, border_radius=6)
                draw_text(surface, self.font_small, f"x{ct}", badge.x + 3, badge.y + 1, (24, 24, 30))

    def _preview_for_step(self) -> Card | None:
        step = self._step()
        if step == "class" and isinstance(self.choices[self.player_cursor]["class"], str):
            return self._card(str(self.choices[self.player_cursor]["class"]))
        if step == "barracks" and isinstance(self.choices[self.player_cursor]["barracks"], str):
            return self._card(str(self.choices[self.player_cursor]["barracks"]))
        if step == "battlefields":
            b = self.choices[self.player_cursor]["battlefields"]
            if isinstance(b, list) and b:
                return self._card(str(b[0]))
        deck = self._deck_name(self.player_cursor)
        if deck == CUSTOM_DECK_NAME:
            custom = self._custom_map(self.player_cursor)
            if custom:
                return self._card(max(custom.items(), key=lambda it: it[1])[0])
        if deck and deck in PREMADE_DECKS and PREMADE_DECKS[deck]:
            return self._card(next(iter(PREMADE_DECKS[deck].keys())))
        return None

    def _draw_summary(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        draw_panel(surface, rect, fill=PANEL_ALT, border=(19, 22, 30), radius=10)
        draw_text(surface, self.font_subtitle, "Summary", rect.x + 10, rect.y + 8, TEXT)
        draw_text(surface, self.font_small, f"Player {self.player_cursor + 1} | Step {self.step_idx + 1}/4", rect.x + 10, rect.y + 34, INFO)

        p1 = self.choices[0]
        p2 = self.choices[1]
        lines1 = [f"Deck: {self._deck_name(0) or '-'}", f"Class: {p1['class'] or '-'}", f"Barracks: {p1['barracks'] or '-'}", f"Fields: {len(p1['battlefields'])}/3"]
        lines2 = [f"Deck: {self._deck_name(1) or '-'}", f"Class: {p2['class'] or '-'}", f"Barracks: {p2['barracks'] or '-'}", f"Fields: {len(p2['battlefields'])}/3"]
        draw_text(surface, self.font_small, "P1", rect.x + 10, rect.y + 60, (120, 182, 235))
        for i, line in enumerate(lines1):
            draw_text(surface, self.font_small, truncate_text(self.font_small, line, rect.width - 20), rect.x + 10, rect.y + 78 + i * 17, MUTED)
        draw_text(surface, self.font_small, "P2", rect.x + 10, rect.y + 152, (232, 145, 151))
        for i, line in enumerate(lines2):
            draw_text(surface, self.font_small, truncate_text(self.font_small, line, rect.width - 20), rect.x + 10, rect.y + 170 + i * 17, MUTED)

        preview = pygame.Rect(rect.x + 10, rect.y + 246, rect.width - 20, 230)
        draw_panel(surface, preview, fill=PANEL, border=(18, 22, 30), radius=8)
        card = self.hovered_card or self._preview_for_step()
        if card is not None:
            if card.card_type == "Class":
                card_slot = pygame.Rect(preview.x + 8, preview.y + 8, 96, preview.height - 16)
                preview_rect = fit_card_rect(card_slot, card.card_type)
                draw_tcg_card(surface, preview_rect, card=card, selected=False, hidden=False, title_font=self.font_card_title, body_font=self.font_card_body, tiny_font=self.font_card_tiny)
                self._draw_class_powerups(surface, card, pygame.Rect(card_slot.right + 8, preview.y + 8, preview.right - card_slot.right - 16, preview.height - 16))
            else:
                preview_slot = pygame.Rect(preview.x + 8, preview.y + 8, preview.width - 16, preview.height - 16)
                preview_rect = fit_card_rect(preview_slot, card.card_type)
                draw_tcg_card(surface, preview_rect, card=card, selected=False, hidden=False, title_font=self.font_card_title, body_font=self.font_card_body, tiny_font=self.font_card_tiny)
        else:
            draw_text(surface, self.font_small, "Hover a card to preview.", preview.x + 10, preview.y + 10, MUTED)

        self._draw_button(surface, pygame.Rect(rect.x + 10, rect.bottom - 36, 132, 28), "Previous", enabled=self.step_idx > 0, callback=self._prev_step)
        next_label = "Next" if self.step_idx < 3 else ("Save P1" if self.player_cursor == 0 else "To Placement")
        self._draw_button(surface, pygame.Rect(rect.right - 142, rect.bottom - 36, 132, 28), next_label, enabled=True, callback=self._next_step)

    def _draw_panel(self, surface: pygame.Surface, rect: pygame.Rect, title: str, color: tuple[int, int, int] = PANEL) -> None:
        draw_panel(surface, rect, fill=color, border=(19, 22, 30), radius=10)
        draw_text(surface, self.font_subtitle, title, rect.x + 12, rect.y + 8, TEXT)

    def _level_powerup_entry(self, card: Card, target_level: int) -> tuple[str, str]:
        entry = None
        for level in card.levels:
            if not isinstance(level, dict):
                continue
            try:
                level_num = int(level.get("level", -1))
            except (TypeError, ValueError):
                continue
            if level_num == target_level:
                entry = level
                break
        if entry is None:
            return (f"Lv {target_level}", "Not defined.")
        name = str(entry.get("name") or "Power Up")
        desc = str(entry.get("description") or "No description.")
        return (f"Lv {target_level}: {name}", desc)

    def _draw_class_powerups(self, surface: pygame.Surface, card: Card, rect: pygame.Rect) -> None:
        draw_text(surface, self.font_small, "Class Power Ups", rect.x, rect.y, INFO, max_width=rect.width)
        y = rect.y + 18
        for target_level in (1, 3, 6):
            title, desc = self._level_powerup_entry(card, target_level)
            draw_text(surface, self.font_tiny, title, rect.x, y, TEXT, max_width=rect.width)
            y += 13
            for line in wrap_text(self.font_tiny, desc, rect.width, 3):
                if y > rect.bottom - 12:
                    return
                draw_text(surface, self.font_tiny, line, rect.x, y, MUTED, max_width=rect.width)
                y += 12
            y += 4

    def _draw_placement_stage(self, surface: pygame.Surface) -> None:
        draw_text(surface, self.font_title, "Battlefield Placement", 24, 20, TEXT)
        draw_text(surface, self.font_body, f"Current placer: Player {self.placement_player + 1} | Select field, then click empty slot", 24, 56, INFO)

        left_panel = pygame.Rect(20, 92, 300, 580)
        grid_panel = pygame.Rect(336, 92, 928, 580)
        self._draw_panel(surface, left_panel, "Remaining Battlefields")
        self._draw_panel(surface, grid_panel, "2x3 Board")

        remaining = self.placement_remaining[self.placement_player]
        y = left_panel.y + 44
        for name in remaining:
            rect = pygame.Rect(left_panel.x + 12, y, left_panel.width - 24, 32)
            self._draw_option_item(surface, rect, name, self.selected_placement_card == name, lambda n=name: self._select_placement_card(n))
            y += 38

        slot_w = 278
        slot_h = 240
        gap_x = 22
        gap_y = 22
        base_x = grid_panel.x + 20
        base_y = grid_panel.y + 52
        for slot in range(6):
            row = slot // 3
            col = slot % 3
            rect = pygame.Rect(base_x + col * (slot_w + gap_x), base_y + row * (slot_h + gap_y), slot_w, slot_h)
            placed = next((p for p in self.placements if p["slot"] == slot), None)
            if placed is None:
                fill = (66, 93, 128) if self.selected_placement_card is not None else PANEL_ALT
                pygame.draw.rect(surface, fill, rect, border_radius=10)
                pygame.draw.rect(surface, (20, 25, 30), rect, width=1, border_radius=10)
                draw_text(surface, self.font_subtitle, f"Slot {slot}", rect.x + 12, rect.y + 10, MUTED)
                draw_text(surface, self.font_small, "Empty", rect.x + 12, rect.y + 40, MUTED)
                if self.selected_placement_card is not None:
                    self._register_click(rect, lambda s=slot: self._place_slot(s))
            else:
                owner = int(placed["owner"])
                bf = placed["battlefield"]["name"]
                fill = (83, 124, 173) if owner == 0 else (161, 96, 101)
                pygame.draw.rect(surface, fill, rect, border_radius=10)
                pygame.draw.rect(surface, (20, 25, 30), rect, width=1, border_radius=10)
                draw_text(surface, self.font_subtitle, f"Slot {slot}", rect.x + 12, rect.y + 10, TEXT)
                draw_text(surface, self.font_body, truncate_text(self.font_body, bf, rect.width - 24), rect.x + 12, rect.y + 44, TEXT)
                draw_text(surface, self.font_small, f"Owner: P{owner + 1}", rect.x + 12, rect.y + 72, MUTED)

        if len(self.placements) == 6 and self.next_scene is None:
            self._start_game()

    def _select_placement_card(self, name: str) -> None:
        if name not in self.placement_remaining[self.placement_player]:
            self.set_status("Selected battlefield is not available for this player.")
            return
        self.selected_placement_card = name
        self.set_status(f"Selected battlefield: {name}. Click a slot.")

    def _place_slot(self, slot: int) -> None:
        if self.selected_placement_card is None:
            self.set_status("Select a battlefield first.")
            return
        if any(p["slot"] == slot for p in self.placements):
            self.set_status("That slot is already occupied.")
            return
        self.placements.append({"slot": slot, "owner": self.placement_player, "battlefield": {"name": self.selected_placement_card}})
        self.placement_remaining[self.placement_player].remove(self.selected_placement_card)
        self.set_status(f"Player {self.placement_player + 1} placed {self.selected_placement_card} at slot {slot}.")
        self.selected_placement_card = None
        self.placement_player = 1 - self.placement_player

    def _start_game(self) -> None:
        from .scene_game import GameScene

        setup_data = {
            "players": [
                {
                    "deck": self._deck_payload(0),
                    "class": self.choices[0]["class"],
                    "barracks": self.choices[0]["barracks"],
                    "battlefields": list(self.choices[0]["battlefields"]),
                },
                {
                    "deck": self._deck_payload(1),
                    "class": self.choices[1]["class"],
                    "barracks": self.choices[1]["barracks"],
                    "battlefields": list(self.choices[1]["battlefields"]),
                },
            ],
            "placements": list(self.placements),
        }
        self.next_scene = GameScene(self.app, Game(setup_data))
