from __future__ import annotations

import pygame

from .constants import ACCENT, INFO, PANEL_ALT, TEXT
from .primitives import Button
from .renderers import draw_board_background, draw_panel, draw_text
from .scene_base import SceneBase


class StartScene(SceneBase):
    def __init__(self, app: "PygameApp"):
        super().__init__(app)
        self.time = 0.0
        self.font_title = pygame.font.SysFont("cambria", 54, bold=True)
        self.font_subtitle = pygame.font.SysFont("cambria", 28, bold=True)
        self.font_body = pygame.font.SysFont("segoe ui", 20)
        self.font_button = pygame.font.SysFont("segoe ui", 22, bold=True)
        self.start_button = Button(
            rect=pygame.Rect(0, 0, 220, 56),
            label="Start",
            callback=self._start_game_flow,
            enabled=True,
        )

    def _start_game_flow(self) -> None:
        from .scene_select import SelectScene

        self.next_scene = SelectScene(self.app)

    def handle_event(self, event: pygame.event.Event) -> None:
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
