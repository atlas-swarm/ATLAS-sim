from enum import Enum


class MissionStatus(str, Enum):
    IDLE = "IDLE"
    LOADED = "LOADED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    ABORTED = "ABORTED"
    COMPLETED = "COMPLETED"