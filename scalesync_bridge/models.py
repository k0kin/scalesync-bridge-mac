from __future__ import annotations
from dataclasses import dataclass, field
import json
from datetime import datetime


@dataclass
class WeightReading:
    stable: bool
    weight_g: float | None = None       # gram weight; None in pure counting mode
    unit: str = "g"
    overload: bool = False
    piece_weight_g: float | None = None  # APW from scale; None if not transmitted
    piece_count: int | None = None       # piece count from PCS line
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_json(self) -> str:
        return json.dumps({
            "type": "weight",
            "weight_g": self.weight_g,
            "stable": self.stable,
            "unit": self.unit,
            "overload": self.overload,
            "piece_weight_g": self.piece_weight_g,
            "piece_count": self.piece_count,
        })


@dataclass
class ScaleInfo:
    make: str
    model: str
    port: str

    def to_dict(self) -> dict:
        return {"make": self.make, "model": self.model, "port": self.port}
