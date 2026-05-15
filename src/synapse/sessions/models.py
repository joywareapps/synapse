from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SessionMeta:
    name: str
    instance_id: str
    started_at: str          # ISO timestamp
    stopped_at: Optional[str] = None
    duration_s: Optional[float] = None
    files: list[str] = field(default_factory=list)  # relative paths of written funscript files

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "instance_id": self.instance_id,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "duration_s": self.duration_s,
            "files": self.files,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SessionMeta":
        return cls(
            name=d["name"],
            instance_id=d["instance_id"],
            started_at=d["started_at"],
            stopped_at=d.get("stopped_at"),
            duration_s=d.get("duration_s"),
            files=d.get("files", []),
        )
