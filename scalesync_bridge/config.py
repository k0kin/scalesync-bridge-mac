from __future__ import annotations
import os
from dataclasses import dataclass, field


@dataclass
class BridgeConfig:
    host: str = "localhost"
    port: int = field(default_factory=lambda: int(os.environ.get("BRIDGE_PORT", "8765")))
    baud_rate: int = field(default_factory=lambda: int(os.environ.get("BRIDGE_BAUD", "9600")))
    serial_port: str | None = field(default_factory=lambda: os.environ.get("BRIDGE_SERIAL_PORT"))
    poll_interval: float = 0.1
