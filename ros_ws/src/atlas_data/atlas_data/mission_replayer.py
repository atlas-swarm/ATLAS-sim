from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class MissionReplayer:
    log_path: Path | None = None
    replay_speed: float = 1.0
    is_playing: bool = False
    loaded_frames: list[dict[str, Any]] = field(default_factory=list)

    def load_log(self, file_path: str | Path) -> None:
        self.log_path = Path(file_path)
        self.loaded_frames = []

    def play(self) -> None:
        self.is_playing = True

    def pause(self) -> None:
        self.is_playing = False

    def seek_to(self, timestamp_ms: int) -> None:
        _ = timestamp_ms

    def get_frame_at(self, timestamp_ms: int) -> dict[str, Any] | None:
        _ = timestamp_ms
        return None

    def set_replay_speed(self, multiplier: float) -> None:
        self.replay_speed = multiplier
