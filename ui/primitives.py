from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pygame


@dataclass
class Button:
    rect: pygame.Rect
    label: str
    callback: Callable[[], None]
    enabled: bool = True

    def is_hovered(self) -> bool:
        return self.rect.collidepoint(pygame.mouse.get_pos())

    def draw(
        self,
        surface: pygame.Surface,
        font: pygame.font.Font,
        *,
        bg: tuple[int, int, int],
        text_color: tuple[int, int, int],
        disabled_bg: tuple[int, int, int],
    ) -> None:
        color = bg if self.enabled else disabled_bg
        hovered = self.enabled and self.is_hovered()
        if hovered:
            color = (
                min(255, color[0] + 20),
                min(255, color[1] + 20),
                min(255, color[2] + 20),
            )
        pygame.draw.rect(surface, color, self.rect, border_radius=5)
        border = (15, 17, 24) if self.enabled else (42, 46, 56)
        pygame.draw.rect(surface, border, self.rect, width=1, border_radius=5)
        if hovered:
            pygame.draw.rect(surface, (236, 205, 124), self.rect.inflate(2, 2), width=1, border_radius=6)
        label = font.render(self.label, True, text_color)
        label_rect = label.get_rect(center=self.rect.center)
        surface.blit(label, label_rect)

    def handle_event(self, event: pygame.event.Event) -> bool:
        if not self.enabled:
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.callback()
                return True
        return False
