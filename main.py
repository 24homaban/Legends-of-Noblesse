import pygame

from ui.app import PygameApp


if __name__ == "__main__":
    pygame.init()
    app = PygameApp(width=1280, height=720, title="Legends of Noblesse")
    app.run()
    pygame.quit()
