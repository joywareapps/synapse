from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from synapse.profiles.models import UserProfile

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
