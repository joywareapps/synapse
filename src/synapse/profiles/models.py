from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class UserProfile:
    name: str
    created_at: str
    updated_at: str

    # Preferences discovered through exploration
    preferred_volume_range: tuple[float, float] = (0.2, 0.6)
    preferred_patterns: list[str] = field(default_factory=list)
    disliked_patterns: list[str] = field(default_factory=list)
    preferred_carrier_hz: Optional[float] = None
    preferred_pulse_hz: Optional[float] = None
    preferred_base_period_s: Optional[float] = None

    # Session history
    session_count: int = 0
    total_duration_s: float = 0.0
    last_session_at: Optional[str] = None

    # Freeform LLM notes
    notes: str = ""

    # Arbitrary key-value store for LLM use
    tags: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "preferred_volume_range": list(self.preferred_volume_range),
            "preferred_patterns": self.preferred_patterns,
            "disliked_patterns": self.disliked_patterns,
            "preferred_carrier_hz": self.preferred_carrier_hz,
            "preferred_pulse_hz": self.preferred_pulse_hz,
            "preferred_base_period_s": self.preferred_base_period_s,
            "session_count": self.session_count,
            "total_duration_s": self.total_duration_s,
            "last_session_at": self.last_session_at,
            "notes": self.notes,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "UserProfile":
        pvr = d.get("preferred_volume_range", [0.2, 0.6])
        return cls(
            name=d["name"],
            created_at=d["created_at"],
            updated_at=d["updated_at"],
            preferred_volume_range=(float(pvr[0]), float(pvr[1])),
            preferred_patterns=d.get("preferred_patterns", []),
            disliked_patterns=d.get("disliked_patterns", []),
            preferred_carrier_hz=d.get("preferred_carrier_hz"),
            preferred_pulse_hz=d.get("preferred_pulse_hz"),
            preferred_base_period_s=d.get("preferred_base_period_s"),
            session_count=d.get("session_count", 0),
            total_duration_s=d.get("total_duration_s", 0.0),
            last_session_at=d.get("last_session_at"),
            notes=d.get("notes", ""),
            tags=d.get("tags", {}),
        )


@dataclass
class ABTestResult:
    test_id: str           # uuid4
    timestamp: str
    variable: str          # what was compared, e.g. "carrier_freq"
    option_a: dict
    option_b: dict
    winner: Optional[str] = None  # "a", "b", or None
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "test_id": self.test_id,
            "timestamp": self.timestamp,
            "variable": self.variable,
            "option_a": self.option_a,
            "option_b": self.option_b,
            "winner": self.winner,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ABTestResult":
        return cls(
            test_id=d["test_id"],
            timestamp=d["timestamp"],
            variable=d["variable"],
            option_a=d["option_a"],
            option_b=d["option_b"],
            winner=d.get("winner"),
            notes=d.get("notes", ""),
        )

    @classmethod
    def new(cls, variable: str, option_a: dict, option_b: dict) -> "ABTestResult":
        from datetime import datetime, timezone
        return cls(
            test_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            variable=variable,
            option_a=option_a,
            option_b=option_b,
        )
