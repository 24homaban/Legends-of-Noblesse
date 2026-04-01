from __future__ import annotations

import pygame


class SceneBase:
    def __init__(self, app: "PygameApp"):
        self.app = app
        self.next_scene: SceneBase | None = None
        self.status_text = ""

    def set_status(self, text: str) -> None:
        self.status_text = text

    def handle_event(self, event: pygame.event.Event) -> None:
        raise NotImplementedError

    def update(self, dt: float) -> None:
        _ = dt

    def draw(self, surface: pygame.Surface) -> None:
        raise NotImplementedError
