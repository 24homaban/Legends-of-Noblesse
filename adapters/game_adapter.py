from __future__ import annotations

from game.game import Game
from ui.constants import DANGER, INFO, SUCCESS


class GameAdapter:
    def __init__(self, game: Game):
        self.game = game

    def active_player_index(self) -> int:
        return self.game.current_player_index

    def legal_deploy_targets(self, player_index: int) -> set[int | str]:
        if self.game.phase != "siege":
            return set()
        if self.game.pending_first_deployer_choice is not None:
            return set()
        if self.game.current_player_index != player_index:
            return set()
        if not self.battalion_can_deploy(player_index, 0) and not self.battalion_can_deploy(player_index, 1):
            return set()
        getter = getattr(self.game, "_available_attack_targets", None)
        if getter is None:
            return set()
        try:
            return set(getter(player_index))
        except Exception:
            return set()

    def battalion_can_deploy(self, player_index: int, battalion_index: int) -> bool:
        if self.game.phase != "siege":
            return False
        if battalion_index not in (0, 1):
            return False
        player = self.game.players[player_index]
        if not player.battalions[battalion_index].cards:
            return False
        return self.game.siege_assignments[player_index][battalion_index] is None

    def logs_window(self, max_lines: int, offset: int) -> tuple[list[str], int]:
        logs = list(self.game.logs)
        max_offset = max(0, len(logs) - max_lines)
        clamped_offset = max(0, min(offset, max_offset))
        return logs[clamped_offset : clamped_offset + max_lines], max_offset

    def status_color(self, status: str) -> tuple[int, int, int]:
        text = status.lower()
        if "not" in text or "invalid" in text:
            return DANGER
        if "pending" in text:
            return INFO
        return SUCCESS
