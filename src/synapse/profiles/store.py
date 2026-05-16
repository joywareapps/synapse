from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from synapse.profiles.models import Memory, UserProfile

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProfileStore:
    """Stores user profiles as YAML in a directory."""

    def __init__(self, profiles_dir: str = "./profiles") -> None:
        self._dir = Path(profiles_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self._dir / f"{name}.yaml"

    def create(self, name: str) -> UserProfile:
        now = _now_iso()
        profile = UserProfile(name=name, created_at=now, updated_at=now)
        self.save(profile)
        return profile

    def get(self, name: str) -> Optional[UserProfile]:
        path = self._path(name)
        if not path.exists():
            return None
        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            return UserProfile.from_dict(data)
        except Exception:
            logger.exception("Failed to load profile %s", name)
            return None

    def list(self) -> list[UserProfile]:
        profiles = []
        for path in sorted(self._dir.glob("*.yaml")):
            try:
                with open(path) as f:
                    data = yaml.safe_load(f) or {}
                profiles.append(UserProfile.from_dict(data))
            except Exception:
                logger.warning("Skipping bad profile: %s", path)
        return profiles

    def save(self, profile: UserProfile) -> None:
        path = self._path(profile.name)
        try:
            with open(path, "w") as f:
                yaml.dump(profile.to_dict(), f, default_flow_style=False, allow_unicode=True)
        except Exception:
            logger.exception("Failed to save profile %s", profile.name)

    def delete(self, name: str) -> bool:
        path = self._path(name)
        if path.exists():
            path.unlink()
            return True
        return False

    def add_memory(
        self,
        profile_name: str,
        text: str,
        category: str = "general",
        session_name: Optional[str] = None,
    ) -> Memory:
        """Add a memory to a profile. Returns the new Memory."""
        from datetime import datetime, timezone
        profile = self.get(profile_name)
        if profile is None:
            raise ValueError(f"Profile '{profile_name}' not found")
        memory = Memory(
            id=str(__import__("uuid").uuid4()),
            text=text,
            category=category,
            created_at=datetime.now(timezone.utc).isoformat(),
            session_name=session_name,
        )
        memories: list[dict] = profile.tags.get("memories", [])
        memories.append(memory.to_dict())
        profile.tags["memories"] = memories
        profile.updated_at = _now_iso()
        self.save(profile)
        return memory

    def get_memories(self, profile_name: str, query: str = "") -> list[Memory]:
        """Return memories for a profile, optionally filtered by substring match."""
        profile = self.get(profile_name)
        if profile is None:
            return []
        raw: list[dict] = profile.tags.get("memories", [])
        memories = [Memory.from_dict(d) for d in raw]
        if query:
            q = query.lower()
            memories = [m for m in memories if q in m.text.lower()]
        return memories

    def delete_memory(self, profile_name: str, memory_id: str) -> bool:
        """Delete a memory by ID. Returns True if found and deleted."""
        profile = self.get(profile_name)
        if profile is None:
            return False
        memories: list[dict] = profile.tags.get("memories", [])
        before = len(memories)
        memories = [m for m in memories if m.get("id") != memory_id]
        if len(memories) == before:
            return False
        profile.tags["memories"] = memories
        profile.updated_at = _now_iso()
        self.save(profile)
        return True

    def update(self, name: str, **kwargs: Any) -> Optional[UserProfile]:
        """Partial update — sets updated_at automatically."""
        profile = self.get(name)
        if profile is None:
            return None

        for key, value in kwargs.items():
            if value is None:
                continue
            if key == "preferred_volume_range" and isinstance(value, (list, tuple)):
                profile.preferred_volume_range = (float(value[0]), float(value[1]))
            elif hasattr(profile, key):
                setattr(profile, key, value)
            else:
                logger.warning("Unknown profile field: %s", key)

        profile.updated_at = _now_iso()
        self.save(profile)
        return profile
