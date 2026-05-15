from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from synapse.sessions.models import SessionMeta
from synapse.sessions.recorder import SessionRecorder

logger = logging.getLogger(__name__)


class SessionManager:
    """Holds active SessionRecorders and persists SessionMeta sidecar files."""

    def __init__(self, sessions_dir: str = "./sessions") -> None:
        self._sessions_dir = Path(sessions_dir)
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        # instance_id -> active recorder
        self._recorders: dict[str, SessionRecorder] = {}

    # ── Session lifecycle ──────────────────────────────────────────────────────

    def start_session(self, name: str, instance_id: str, axis_ids: Optional[list[str]] = None) -> None:
        """Begin recording for the given instance.

        axis_ids: list of tcode axis IDs to record (pass all enabled axis IDs).
        """
        if instance_id in self._recorders:
            logger.warning("Session already active for instance %s — stopping old one first", instance_id)
            self._stop_and_save(instance_id)

        recorder = SessionRecorder(name, instance_id, self._sessions_dir)
        recorder.start(axis_ids or [])
        self._recorders[instance_id] = recorder

    def stop_session(self, instance_id: str) -> Optional[SessionMeta]:
        """Stop recording, flush files, write sidecar, return metadata."""
        if instance_id not in self._recorders:
            return None
        return self._stop_and_save(instance_id)

    def _stop_and_save(self, instance_id: str) -> SessionMeta:
        recorder = self._recorders.pop(instance_id)
        meta = recorder.stop()
        self._write_sidecar(meta)
        return meta

    def record_tick(self, instance_id: str, axis_values: dict[str, float], timestamp_ms: int) -> None:
        """Forward a tick to the recorder for this instance (no-op if not recording)."""
        recorder = self._recorders.get(instance_id)
        if recorder is not None:
            recorder.record_tick(axis_values, timestamp_ms)

    def is_recording(self, instance_id: str) -> bool:
        return instance_id in self._recorders

    # ── Sidecar persistence ────────────────────────────────────────────────────

    def _sidecar_path(self, name: str) -> Path:
        return self._sessions_dir / f"{name}.meta.json"

    def _write_sidecar(self, meta: SessionMeta) -> None:
        path = self._sidecar_path(meta.name)
        try:
            with open(path, "w") as f:
                json.dump(meta.to_dict(), f, indent=2)
        except Exception:
            logger.exception("Failed to write session sidecar for %s", meta.name)

    # ── Queries ────────────────────────────────────────────────────────────────

    def list_sessions(self) -> list[SessionMeta]:
        """Read all .meta.json sidecar files from sessions dir."""
        metas = []
        for path in sorted(self._sessions_dir.glob("*.meta.json")):
            try:
                with open(path) as f:
                    data = json.load(f)
                metas.append(SessionMeta.from_dict(data))
            except Exception:
                logger.warning("Skipping bad sidecar: %s", path)
        return metas

    def get_session(self, name: str) -> Optional[SessionMeta]:
        path = self._sidecar_path(name)
        if not path.exists():
            return None
        try:
            with open(path) as f:
                return SessionMeta.from_dict(json.load(f))
        except Exception:
            logger.warning("Failed to read sidecar for %s", name)
            return None

    def delete_session(self, name: str) -> bool:
        """Remove all files (funscripts + meta) for a session. Returns True if any were removed."""
        removed = False
        meta_path = self._sidecar_path(name)
        if meta_path.exists():
            meta_path.unlink()
            removed = True
        for fpath in self._sessions_dir.glob(f"{name}.*.funscript"):
            fpath.unlink()
            removed = True
        return removed
