from __future__ import annotations

import pygame

from .constants import ACCENT, INFO, PANEL_ALT, TEXT
from .primitives import Button
from .renderers import draw_board_background, draw_panel, draw_text
from .scene_base import SceneBase
from .tutorial import TutorialCard, draw_tutorial_popup


class StartScene(SceneBase):
    def __init__(self, app: "PygameApp"):
        super().__init__(app)
        self.time = 0.0
        self.font_title = pygame.font.SysFont("cambria", 54, bold=True)
        self.font_subtitle = pygame.font.SysFont("cambria", 28, bold=True)
        self.font_body = pygame.font.SysFont("segoe ui", 20)
        self.font_small = pygame.font.SysFont("segoe ui", 16)
        self.font_button = pygame.font.SysFont("segoe ui", 22, bold=True)
        self.start_button = Button(
            rect=pygame.Rect(0, 0, 220, 56),
            label="Start",
            callback=self._start_game_flow,
            enabled=True,
        )
        self.tutorial_title_font = pygame.font.SysFont("cambria", 32, bold=True)
        self.tutorial_cards: list[TutorialCard] = []
        if self.app.tutorial_pending("start_overview"):
            self.tutorial_cards.append(
                TutorialCard(
                    key="start_overview",
                    title="Quick Playthrough Overview",
                    lines=(
                        "This guide will appear across setup, placement, and your first turn.",
                        "The turn loop is Draw -> Preparations -> Siege -> Field Cleanup.",
                        "By first cleanup, you should understand the core controls and flow.",
                        "Press Start to begin player setup when you are ready.",
                    ),
                    continue_label="Start Setup",
                )
            )
        self.tutorial_index = 0
        self.tutorial_next_rect = pygame.Rect(0, 0, 0, 0)
        self.tutorial_skip_rect = pygame.Rect(0, 0, 0, 0)

    def _start_game_flow(self) -> None:
        from .scene_select import SelectScene

        self.next_scene = SelectScene(self.app)

    def _tutorial_active(self) -> bool:
        return self.tutorial_index < len(self.tutorial_cards)

    def _advance_tutorial(self) -> None:
        if not self._tutorial_active():
            return
        card = self.tutorial_cards[self.tutorial_index]
        self.app.mark_tutorial_seen(card.key)
        self.tutorial_index += 1

    def _skip_tutorial(self) -> None:
        self.app.skip_all_tutorials()
        self.tutorial_cards = []
        self.tutorial_index = 0

    def handle_event(self, event: pygame.event.Event) -> None:
        if self._tutorial_active():
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    self._advance_tutorial()
                    return
                if event.key == pygame.K_ESCAPE:
                    self._skip_tutorial()
                    return
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.tutorial_next_rect.collidepoint(event.pos):
                    self._advance_tutorial()
                    return
                if self.tutorial_skip_rect.collidepoint(event.pos):
                    self._skip_tutorial()
                    return
                return
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE):
            self._start_game_flow()
            return
        self.start_button.handle_event(event)

    def update(self, dt: float) -> None:
        self.time += dt

    def draw(self, surface: pygame.Surface) -> None:
        draw_board_background(surface, self.time)
        sw, sh = surface.get_size()

        panel = pygame.Rect(0, 0, 760, 400)
        panel.center = (sw // 2, sh // 2)
        draw_panel(surface, panel, fill=PANEL_ALT, border=(20, 24, 32), radius=14)

        draw_text(surface, self.font_title, "Legends of Noblesse", panel.x + 78, panel.y + 70, TEXT)
        draw_text(surface, self.font_subtitle, "by Brandt Homan", panel.x + 242, panel.y + 142, ACCENT)
        draw_text(
            surface,
            self.font_body,
            "Press Start to configure both players and begin setup.",
            panel.x + 162,
            panel.y + 198,
            INFO,
        )

        self.start_button.rect = pygame.Rect(0, 0, 220, 56)
        self.start_button.rect.center = (panel.centerx, panel.y + 286)
        self.start_button.draw(
            surface,
            self.font_button,
            bg=(76, 112, 160),
            text_color=TEXT,
            disabled_bg=(60, 66, 80),
        )
        if self._tutorial_active():
            card = self.tutorial_cards[self.tutorial_index]
            popup_rects = draw_tutorial_popup(
                surface,
                title_font=self.tutorial_title_font,
                body_font=self.font_body,
                small_font=self.font_small,
                card=card,
                step_index=self.tutorial_index + 1,
                total_steps=len(self.tutorial_cards),
            )
            self.tutorial_next_rect = popup_rects["next"]
            self.tutorial_skip_rect = popup_rects["skip"]
