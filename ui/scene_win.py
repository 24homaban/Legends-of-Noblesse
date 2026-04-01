from __future__ import annotations

import pygame

from .constants import ACCENT, INFO, P1_COLOR, P2_COLOR, PANEL_ALT, TEXT
from .primitives import Button
from .renderers import draw_board_background, draw_panel, draw_text
from .scene_base import SceneBase


class WinScene(SceneBase):
    def __init__(self, app: "PygameApp", winner_index: int):
        super().__init__(app)
        self.winner_index = winner_index
        self.time = 0.0

        self.font_title = pygame.font.SysFont("cambria", 58, bold=True)
        self.font_subtitle = pygame.font.SysFont("cambria", 28, bold=True)
        self.font_body = pygame.font.SysFont("segoe ui", 22)
        self.font_button = pygame.font.SysFont("segoe ui", 22, bold=True)

        self.return_button = Button(
            rect=pygame.Rect(0, 0, 260, 56),
            label="Return to Start",
            callback=self._return_to_start,
            enabled=True,
        )

    def _return_to_start(self) -> None:
        from .scene_start import StartScene

        self.next_scene = StartScene(self.app)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE):
            self._return_to_start()
            return
        self.return_button.handle_event(event)

    def update(self, dt: float) -> None:
        self.time += dt

    def draw(self, surface: pygame.Surface) -> None:
        draw_board_background(surface, self.time)
        sw, sh = surface.get_size()

        panel = pygame.Rect(0, 0, 760, 420)
        panel.center = (sw // 2, sh // 2)
        draw_panel(surface, panel, fill=PANEL_ALT, border=(20, 24, 32), radius=14)

        winner_num = self.winner_index + 1
        winner_color = P1_COLOR if self.winner_index == 0 else P2_COLOR
        draw_text(surface, self.font_title, f"Player {winner_num} Wins!", panel.x + 130, panel.y + 96, winner_color)
        draw_text(surface, self.font_subtitle, "Barracks Breached", panel.x + 234, panel.y + 170, ACCENT)
        draw_text(
            surface,
            self.font_body,
            "Press Enter/Space or click below to start a new game.",
            panel.x + 132,
            panel.y + 220,
            INFO,
        )

        self.return_button.rect = pygame.Rect(0, 0, 260, 56)
        self.return_button.rect.center = (panel.centerx, panel.y + 314)
        self.return_button.draw(
            surface,
            self.font_button,
            bg=(76, 112, 160),
            text_color=TEXT,
            disabled_bg=(60, 66, 80),
        )
