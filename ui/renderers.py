from __future__ import annotations

from difflib import SequenceMatcher
import math
from pathlib import Path

import pygame

from game.models import Card
from .constants import (
    ACCENT,
    BG_BOTTOM,
    BG_TOP,
    CARD_TYPE_COLORS,
    MUTED,
    PANEL,
    PANEL_ALT,
    PANEL_SOFT,
    RESOURCE_COLORS,
    TEXT,
)

_ASSETS_ROOT = Path(__file__).resolve().parent.parent / "assets"
_ASSET_TYPE_FOLDERS: dict[str, list[str]] = {
    "Unit": ["Soldiers", "Units"],
    "Tactic": ["Tactics"],
    "Battlefield": ["Battlefields"],
    "Barracks": ["Barracks"],
    "Class": ["Classes"],
}
_ASSET_TYPE_BACKDROPS: dict[str, str] = {
    "Unit": "Units.png",
    "Tactic": "Tactics.png",
    "Battlefield": "battlefields.png",
    "Barracks": "Barracks.png",
    "Class": "Classes.png",
}
CARD_ASPECT_W = 5
CARD_ASPECT_H = 7
_CARD_ASPECT_BY_TYPE: dict[str, tuple[int, int]] = {
    "Class": (4, 5),
    "Barracks": (47, 53),
}
_FUZZY_ASSET_MATCH_MIN = 0.88
_HIDDEN_CARD_BACK_KEY = "cardback"
_HIDDEN_CARD_BACK_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

_ART_FILES_BY_FOLDER: dict[str, dict[str, Path]] | None = None
_ART_STEMS_BY_FOLDER: dict[str, list[tuple[str, Path]]] | None = None
_CARD_ART_PATH_CACHE: dict[tuple[str, str], Path | None] = {}
_CARD_ART_IMAGE_CACHE: dict[Path, pygame.Surface] = {}
_CARD_ART_SCALED_CACHE: dict[tuple[Path, int, int], pygame.Surface] = {}
_CARD_ART_LOAD_FAILED: set[Path] = set()
_HIDDEN_CARD_BACK_PATH_CACHE: Path | None = None
_HIDDEN_CARD_BACK_LOOKUP_DONE = False


def draw_text(
    surface: pygame.Surface,
    font: pygame.font.Font,
    text: str,
    x: int,
    y: int,
    color: tuple[int, int, int] = TEXT,
    *,
    max_width: int | None = None,
) -> None:
    if max_width is not None:
        text = truncate_text(font, text, max_width)
    label = font.render(text, True, color)
    surface.blit(label, (x, y))


def truncate_text(font: pygame.font.Font, text: str, max_width: int) -> str:
    if font.size(text)[0] <= max_width:
        return text
    suffix = "..."
    available = max_width - font.size(suffix)[0]
    if available <= 0:
        return suffix
    trimmed = text
    while trimmed and font.size(trimmed)[0] > available:
        trimmed = trimmed[:-1]
    return f"{trimmed}{suffix}"


def wrap_text(font: pygame.font.Font, text: str, max_width: int, max_lines: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if font.size(candidate)[0] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
    if len(lines) < max_lines:
        lines.append(current)

    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if lines and len(lines) == max_lines:
        lines[-1] = truncate_text(font, lines[-1], max_width)
    return lines


def fit_rect_to_aspect(
    rect: pygame.Rect,
    aspect_w: int = CARD_ASPECT_W,
    aspect_h: int = CARD_ASPECT_H,
    *,
    padding: int = 0,
) -> pygame.Rect:
    """Return the largest centered rect inside `rect` with the given aspect ratio."""
    available = rect.inflate(-padding * 2, -padding * 2)
    if available.width <= 0 or available.height <= 0:
        return pygame.Rect(rect.x, rect.y, 1, 1)

    target_ratio = aspect_w / aspect_h
    current_ratio = available.width / available.height
    if current_ratio >= target_ratio:
        h = available.height
        w = max(1, int(round(h * target_ratio)))
    else:
        w = available.width
        h = max(1, int(round(w / target_ratio)))

    x = available.x + (available.width - w) // 2
    y = available.y + (available.height - h) // 2
    return pygame.Rect(x, y, w, h)


def card_aspect(card_type: str | None) -> tuple[int, int]:
    if card_type is None:
        return (CARD_ASPECT_W, CARD_ASPECT_H)
    return _CARD_ASPECT_BY_TYPE.get(card_type, (CARD_ASPECT_W, CARD_ASPECT_H))


def fit_card_rect(
    rect: pygame.Rect,
    card_type: str | None,
    *,
    padding: int = 0,
) -> pygame.Rect:
    aspect_w, aspect_h = card_aspect(card_type)
    return fit_rect_to_aspect(rect, aspect_w=aspect_w, aspect_h=aspect_h, padding=padding)


def _blend(
    a: tuple[int, int, int],
    b: tuple[int, int, int],
    t: float,
) -> tuple[int, int, int]:
    clamped = max(0.0, min(1.0, t))
    return (
        int(a[0] + (b[0] - a[0]) * clamped),
        int(a[1] + (b[1] - a[1]) * clamped),
        int(a[2] + (b[2] - a[2]) * clamped),
    )


def draw_vertical_gradient(
    surface: pygame.Surface,
    rect: pygame.Rect,
    top_color: tuple[int, int, int],
    bottom_color: tuple[int, int, int],
) -> None:
    height = max(1, rect.height)
    for i in range(height):
        t = i / max(1, height - 1)
        color = _blend(top_color, bottom_color, t)
        pygame.draw.line(surface, color, (rect.x, rect.y + i), (rect.right - 1, rect.y + i))


def draw_board_background(surface: pygame.Surface, tick: float) -> None:
    full = surface.get_rect()
    draw_vertical_gradient(surface, full, BG_TOP, BG_BOTTOM)

    glow_layer = pygame.Surface(full.size, pygame.SRCALPHA)
    w, h = full.width, full.height
    pulse = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(tick * 1.8))

    pygame.draw.circle(
        glow_layer,
        (70, 120, 175, int(28 * pulse)),
        (int(w * 0.18), int(h * 0.32)),
        int(h * 0.42),
    )
    pygame.draw.circle(
        glow_layer,
        (150, 88, 102, int(24 * pulse)),
        (int(w * 0.82), int(h * 0.66)),
        int(h * 0.36),
    )

    grid_alpha = pygame.Surface(full.size, pygame.SRCALPHA)
    spacing = 36
    for x in range(0, w, spacing):
        pygame.draw.line(grid_alpha, (255, 255, 255, 6), (x, 0), (x, h))
    for y in range(0, h, spacing):
        pygame.draw.line(grid_alpha, (255, 255, 255, 5), (0, y), (w, y))

    surface.blit(glow_layer, (0, 0))
    surface.blit(grid_alpha, (0, 0))


def draw_panel(
    surface: pygame.Surface,
    rect: pygame.Rect,
    *,
    fill: tuple[int, int, int] = PANEL,
    border: tuple[int, int, int] = (18, 22, 31),
    radius: int = 10,
    glow: tuple[int, int, int] | None = None,
) -> None:
    shadow = rect.move(0, 2)
    pygame.draw.rect(surface, (0, 0, 0, 80), shadow, border_radius=radius)
    pygame.draw.rect(surface, fill, rect, border_radius=radius)
    pygame.draw.rect(surface, border, rect, width=1, border_radius=radius)
    if glow:
        glow_rect = rect.inflate(2, 2)
        pygame.draw.rect(surface, glow, glow_rect, width=1, border_radius=radius + 1)


def _type_color(card_type: str | None) -> tuple[int, int, int]:
    if not card_type:
        return PANEL_SOFT
    return CARD_TYPE_COLORS.get(card_type, PANEL_SOFT)


def _hash_color_seed(text: str) -> tuple[int, int, int]:
    seed = sum((idx + 1) * ord(ch) for idx, ch in enumerate(text))
    r = 65 + (seed % 75)
    g = 72 + ((seed // 7) % 90)
    b = 88 + ((seed // 17) % 95)
    return (r, g, b)


def _normalize_asset_key(text: str) -> str:
    return "".join(ch.lower() for ch in text if ch.isalnum())


def _build_art_indexes() -> tuple[dict[str, dict[str, Path]], dict[str, list[tuple[str, Path]]]]:
    exact_by_folder: dict[str, dict[str, Path]] = {}
    stems_by_folder: dict[str, list[tuple[str, Path]]] = {}
    if not _ASSETS_ROOT.exists():
        return exact_by_folder, stems_by_folder

    for folder in _ASSETS_ROOT.iterdir():
        if not folder.is_dir():
            continue
        exact: dict[str, Path] = {}
        stem_list: list[tuple[str, Path]] = []
        for image_path in sorted(folder.glob("*.png")):
            stem_key = _normalize_asset_key(image_path.stem)
            if not stem_key:
                continue
            exact.setdefault(stem_key, image_path)
            stem_list.append((stem_key, image_path))
        if exact:
            key = folder.name.lower()
            exact_by_folder[key] = exact
            stems_by_folder[key] = stem_list
    return exact_by_folder, stems_by_folder


def _ensure_art_indexes() -> tuple[dict[str, dict[str, Path]], dict[str, list[tuple[str, Path]]]]:
    global _ART_FILES_BY_FOLDER
    global _ART_STEMS_BY_FOLDER
    if _ART_FILES_BY_FOLDER is None or _ART_STEMS_BY_FOLDER is None:
        _ART_FILES_BY_FOLDER, _ART_STEMS_BY_FOLDER = _build_art_indexes()
    return _ART_FILES_BY_FOLDER, _ART_STEMS_BY_FOLDER


def _candidate_asset_folders(card_type: str) -> list[str]:
    mapped = _ASSET_TYPE_FOLDERS.get(card_type)
    if mapped:
        return mapped
    return [card_type, f"{card_type}s"]


def _resolve_card_art_path(card_type: str, card_name: str) -> Path | None:
    cache_key = (card_type, card_name)
    if cache_key in _CARD_ART_PATH_CACHE:
        return _CARD_ART_PATH_CACHE[cache_key]

    target_stem = _normalize_asset_key(card_name)
    if not target_stem:
        _CARD_ART_PATH_CACHE[cache_key] = None
        return None

    exact_by_folder, stems_by_folder = _ensure_art_indexes()
    folder_candidates = [folder.lower() for folder in _candidate_asset_folders(card_type)]

    for folder in folder_candidates:
        exact = exact_by_folder.get(folder)
        if exact and target_stem in exact:
            match = exact[target_stem]
            _CARD_ART_PATH_CACHE[cache_key] = match
            return match

    best_match: tuple[float, Path] | None = None
    for folder in folder_candidates:
        candidates = stems_by_folder.get(folder, [])
        for stem, image_path in candidates:
            score = SequenceMatcher(None, target_stem, stem).ratio()
            if best_match is None or score > best_match[0]:
                best_match = (score, image_path)

    if best_match and best_match[0] >= _FUZZY_ASSET_MATCH_MIN:
        _CARD_ART_PATH_CACHE[cache_key] = best_match[1]
        return best_match[1]

    _CARD_ART_PATH_CACHE[cache_key] = None
    return None


def _get_card_art_surface(path: Path, size: tuple[int, int]) -> pygame.Surface | None:
    width, height = size
    if width <= 0 or height <= 0:
        return None

    if path in _CARD_ART_LOAD_FAILED:
        return None

    source = _CARD_ART_IMAGE_CACHE.get(path)
    if source is None:
        try:
            source = pygame.image.load(str(path)).convert_alpha()
        except (pygame.error, FileNotFoundError):
            _CARD_ART_LOAD_FAILED.add(path)
            return None
        _CARD_ART_IMAGE_CACHE[path] = source

    scaled_key = (path, width, height)
    scaled = _CARD_ART_SCALED_CACHE.get(scaled_key)
    if scaled is None:
        src_w, src_h = source.get_size()
        if src_w <= 0 or src_h <= 0:
            return None

        # Scale to fit the full card image without cropping any card details.
        scale = min(width / src_w, height / src_h)
        scaled_w = max(1, int(round(src_w * scale)))
        scaled_h = max(1, int(round(src_h * scale)))
        resized = pygame.transform.smoothscale(source, (scaled_w, scaled_h))
        scaled = pygame.Surface((width, height), pygame.SRCALPHA)
        blit_x = (width - scaled_w) // 2
        blit_y = (height - scaled_h) // 2
        scaled.blit(resized, (blit_x, blit_y))
        _CARD_ART_SCALED_CACHE[scaled_key] = scaled
    return scaled


def _resolve_type_backdrop_path(card_type: str) -> Path | None:
    filename = _ASSET_TYPE_BACKDROPS.get(card_type)
    if filename is None:
        return None
    path = _ASSETS_ROOT / filename
    if path.exists():
        return path
    return None


def _resolve_hidden_card_back_path() -> Path | None:
    global _HIDDEN_CARD_BACK_PATH_CACHE
    global _HIDDEN_CARD_BACK_LOOKUP_DONE

    if _HIDDEN_CARD_BACK_LOOKUP_DONE:
        return _HIDDEN_CARD_BACK_PATH_CACHE

    project_root = _ASSETS_ROOT.parent
    search_roots = (_ASSETS_ROOT, project_root)
    for root in search_roots:
        if not root.exists():
            continue
        for candidate in root.rglob("*"):
            if not candidate.is_file():
                continue
            if candidate.suffix.lower() not in _HIDDEN_CARD_BACK_EXTENSIONS:
                continue
            if _normalize_asset_key(candidate.stem) == _HIDDEN_CARD_BACK_KEY:
                _HIDDEN_CARD_BACK_PATH_CACHE = candidate
                _HIDDEN_CARD_BACK_LOOKUP_DONE = True
                return candidate

    _HIDDEN_CARD_BACK_LOOKUP_DONE = True
    return None


def _draw_cost_chips(
    surface: pygame.Surface,
    cost: dict[str, int],
    rect: pygame.Rect,
    font: pygame.font.Font,
) -> None:
    if not cost:
        return
    order = ("rations", "ore", "materia", "magium", "faith", "sacrifice")
    chips = [(key, cost[key]) for key in order if key in cost and cost[key] > 0]
    x = rect.x + 6
    y = rect.y + 2
    for key, value in chips[:5]:
        chip = pygame.Rect(x, y, 32, 16)
        color = RESOURCE_COLORS.get(key, PANEL_SOFT)
        pygame.draw.rect(surface, color, chip, border_radius=8)
        pygame.draw.rect(surface, (20, 24, 34), chip, width=1, border_radius=8)
        short = key[0].upper()
        draw_text(surface, font, f"{short}{value}", chip.x + 6, chip.y + 2, (18, 22, 29))
        x += 35


def draw_tcg_card(
    surface: pygame.Surface,
    rect: pygame.Rect,
    *,
    card: Card | None = None,
    title: str | None = None,
    subtitle: str = "",
    selected: bool = False,
    hidden: bool = False,
    subdued: bool = False,
    title_font: pygame.font.Font,
    body_font: pygame.font.Font,
    tiny_font: pygame.font.Font,
) -> None:
    name = card.name if card else (title or "Card")
    card_type = card.card_type if card else "Unit"

    shadow = rect.move(2, 3)
    pygame.draw.rect(surface, (8, 10, 15), shadow, border_radius=8)

    base = _type_color(card_type)
    if subdued:
        base = _blend(base, (42, 46, 58), 0.62)
    edge = ACCENT if selected else _blend(base, (16, 20, 27), 0.35)
    inner = rect.inflate(-4, -4)
    pygame.draw.rect(surface, _blend(base, (12, 14, 20), 0.55), rect, border_radius=8)
    pygame.draw.rect(surface, edge, rect, width=2, border_radius=8)

    art_path: Path | None = None
    if hidden:
        art_path = _resolve_hidden_card_back_path()
        if art_path is None:
            art_path = _resolve_type_backdrop_path(card_type)
    elif card is not None:
        art_path = _resolve_card_art_path(card_type, name)

    art_drawn = False
    if art_path is not None:
        art_surface = _get_card_art_surface(art_path, inner.size)
        if art_surface is not None:
            surface.blit(art_surface, inner.topleft)
            art_drawn = True

    if not art_drawn:
        pygame.draw.rect(surface, _blend(base, (18, 21, 29), 0.68), inner, border_radius=6)
        draw_text(
            surface,
            tiny_font,
            truncate_text(tiny_font, name, inner.width - 12),
            inner.x + 6,
            inner.y + 6,
            MUTED,
            max_width=inner.width - 12,
        )

    if subdued:
        veil = pygame.Surface(inner.size, pygame.SRCALPHA)
        veil.fill((20, 24, 32, 110))
        surface.blit(veil, inner.topleft)

    if hidden and not art_drawn:
        draw_text(surface, body_font, "Hidden", inner.x + 8, inner.y + 8, TEXT)


def draw_card_box(
    surface: pygame.Surface,
    rect: pygame.Rect,
    title: str,
    subtitle: str = "",
    *,
    selected: bool = False,
    hidden: bool = False,
    base_color: tuple[int, int, int] = PANEL_ALT,
    title_font: pygame.font.Font,
    small_font: pygame.font.Font,
) -> None:
    dummy = Card(
        name=title,
        card_type="Unit",
        ability=subtitle,
        line=subtitle,
    )
    draw_tcg_card(
        surface,
        rect,
        card=dummy,
        subtitle=subtitle,
        selected=selected,
        hidden=hidden,
        subdued=base_color == PANEL_ALT,
        title_font=title_font,
        body_font=small_font,
        tiny_font=small_font,
    )
