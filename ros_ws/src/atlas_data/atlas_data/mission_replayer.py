from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class MissionReplayer:
    log_path: Path | None = None
    replay_speed: float = 1.0
    is_playing: bool = False
    loaded_frames: list[dict[str, Any]] = field(default_factory=list)
    current_timestamp: int = 0

    def load_log(self, file_path: str | Path) -> bool:
        """Load CSV log file into memory. Returns True on success, False if file doesn't exist."""
        path = Path(file_path)
        
        if not path.exists():
            return False
        
        self.log_path = path
        self.loaded_frames = []
        
        try:
            with path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    self.loaded_frames.append(dict(row))
            
            self.current_timestamp = 0
            return True
        except Exception:
            # If CSV reading fails, return False
            self.loaded_frames = []
            return False

    def play(self) -> None:
        self.is_playing = True

    def pause(self) -> None:
        self.is_playing = False

    def seek_to(self, timestamp_ms: int) -> None:
        """Seek to the closest frame by timestamp and update current_timestamp."""
        if not self.loaded_frames:
            return
        
        # Find the frame with timestamp closest to timestamp_ms
        closest_frame = min(
            self.loaded_frames,
            key=lambda frame: abs(int(frame.get("timestamp", 0)) - timestamp_ms)
        )
        
        self.current_timestamp = int(closest_frame.get("timestamp", 0))

    def get_frame_at(self, timestamp_ms: int) -> dict[str, Any] | None:
        """Return the frame closest to the given timestamp, or None if no frames loaded."""
        if not self.loaded_frames:
            return None
        
        # Find and return the frame with timestamp closest to timestamp_ms
        closest_frame = min(
            self.loaded_frames,
            key=lambda frame: abs(int(frame.get("timestamp", 0)) - timestamp_ms)
        )
        
        return closest_frame

    def set_replay_speed(self, multiplier: float) -> None:
        self.replay_speed = multiplier
