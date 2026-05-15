from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SensorReading:
    name: str
    value: float          # normalized 0.0–1.0
    raw: dict = field(default_factory=dict)
    error: Optional[str] = None
    timestamp: float = 0.0


@dataclass
class SensorConfig:
    enabled: bool = False
    label: str = ""
