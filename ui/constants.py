WIDTH = 1280
HEIGHT = 720
FPS = 60

BG = (14, 18, 27)
BG_TOP = (20, 30, 44)
BG_BOTTOM = (11, 13, 20)

PANEL = (24, 32, 46)
PANEL_ALT = (34, 44, 62)
PANEL_SOFT = (45, 56, 78)

TEXT = (236, 240, 247)
MUTED = (155, 166, 184)
ACCENT = (231, 187, 96)
SUCCESS = (96, 184, 122)
DANGER = (214, 99, 105)
INFO = (112, 176, 230)

LEGAL_TARGET = (92, 170, 118)
INVALID_TARGET = (172, 88, 93)

P1_COLOR = (86, 167, 224)
P2_COLOR = (226, 116, 119)

CARD_TYPE_COLORS: dict[str, tuple[int, int, int]] = {
    "Unit": (170, 132, 78),
    "Tactic": (75, 109, 168),
    "Battlefield": (74, 136, 111),
    "Class": (124, 98, 140),
    "Barracks": (116, 102, 82),
}

RESOURCE_COLORS: dict[str, tuple[int, int, int]] = {
    "rations": (205, 186, 133),
    "ore": (154, 167, 181),
    "materia": (113, 199, 179),
    "magium": (121, 173, 220),
    "faith": (223, 213, 131),
    "sacrifice": (205, 112, 129),
}
