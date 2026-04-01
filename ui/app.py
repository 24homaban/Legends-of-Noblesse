from __future__ import annotations

import pygame

from .constants import BG, FPS
from .scene_start import StartScene


class PygameApp:
    def __init__(self, width: int, height: int, title: str):
        self.screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption(title)
        self.clock = pygame.time.Clock()
        self.running = True
        self.scene = StartScene(self)

    def run(self) -> None:
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                    break
                self.scene.handle_event(event)

            if not self.running:
                break

            self.scene.update(dt)
            self.screen.fill(BG)
            self.scene.draw(self.screen)
            pygame.display.flip()

            if self.scene.next_scene is not None:
                self.scene = self.scene.next_scene
