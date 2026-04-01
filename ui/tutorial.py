from __future__ import annotations

from dataclasses import dataclass

import pygame

from .constants import ACCENT, INFO, MUTED, PANEL_ALT, TEXT
from .renderers import draw_panel, draw_text, wrap_text


@dataclass(frozen=True)
class TutorialCard:
    key: str
    title: str
    lines: tuple[str, ...]
    continue_label: str = "Continue"


def _draw_button(
    surface: pygame.Surface,
    rect: pygame.Rect,
    label: str,
    font: pygame.font.Font,
    *,
    hovered: bool,
    emphasized: bool,
) -> None:
    base = (75, 107, 149) if emphasized else (62, 72, 89)
    if hovered:
        base = (
            min(255, base[0] + 15),
            min(255, base[1] + 15),
            min(255, base[2] + 15),
        )
    pygame.draw.rect(surface, base, rect, border_radius=7)
    pygame.draw.rect(surface, ACCENT, rect, width=1, border_radius=7)
    draw_text(surface, font, label, rect.x + 14, rect.y + 7, TEXT, max_width=rect.width - 28)


def draw_tutorial_popup(
    surface: pygame.Surface,
    *,
    title_font: pygame.font.Font,
    body_font: pygame.font.Font,
    small_font: pygame.font.Font,
    card: TutorialCard,
    step_index: int,
    total_steps: int,
) -> dict[str, pygame.Rect]:
    overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    overlay.fill((8, 10, 16, 178))
    surface.blit(overlay, (0, 0))

    popup_w = min(860, max(620, surface.get_width() - 120))
    popup_h = min(430, max(320, surface.get_height() - 140))
    popup = pygame.Rect(0, 0, popup_w, popup_h)
    popup.center = surface.get_rect().center
    draw_panel(surface, popup, fill=PANEL_ALT, border=(19, 22, 30), radius=12, glow=ACCENT)

    draw_text(
        surface,
        small_font,
        f"How To Play {step_index}/{total_steps}",
        popup.x + 18,
        popup.y + 14,
        INFO,
        max_width=popup.width - 36,
    )
    draw_text(
        surface,
        title_font,
        card.title,
        popup.x + 18,
        popup.y + 36,
        TEXT,
        max_width=popup.width - 36,
    )

    max_line_w = popup.width - 40
    y = popup.y + 78
    max_y = popup.bottom - 90
    for paragraph in card.lines:
        if y > max_y:
            break
        wrapped = wrap_text(body_font, paragraph, max_line_w, 3)
        for line in wrapped:
            if y > max_y:
                break
            draw_text(surface, body_font, line, popup.x + 18, y, TEXT, max_width=max_line_w)
            y += 20
        y += 4

    draw_text(
        surface,
        small_font,
        "Enter/Space: continue   Esc: skip all guide popups",
        popup.x + 18,
        popup.bottom - 72,
        MUTED,
        max_width=popup.width - 36,
    )

    skip_rect = pygame.Rect(popup.x + 18, popup.bottom - 46, 180, 30)
    next_rect = pygame.Rect(popup.right - 198, popup.bottom - 46, 180, 30)
    mouse = pygame.mouse.get_pos()
    _draw_button(
        surface,
        skip_rect,
        "Skip Guide",
        small_font,
        hovered=skip_rect.collidepoint(mouse),
        emphasized=False,
    )
    _draw_button(
        surface,
        next_rect,
        card.continue_label,
        small_font,
        hovered=next_rect.collidepoint(mouse),
        emphasized=True,
    )

    return {"popup": popup, "skip": skip_rect, "next": next_rect}
