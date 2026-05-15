from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from synapse.sessions.models import SessionMeta

logger = logging.getLogger(__name__)

_FLUSH_INTERVAL = 1.0  # seconds between periodic disk flushes


class SessionRecorder:
    """Records axis values to funscript files for one session instance."""

    def __init__(self, name: str, instance_id: str, sessions_dir: Path) -> None:
        self._name = name
        self._instance_id = instance_id
        self._sessions_dir = sessions_dir
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._start_time_ms: Optional[int] = None

        # axis_id -> list of {"at": ms, "pos": 0-100}
        self._buffers: dict[str, list[dict]] = {}
        # axis_id -> open file path
        self._file_paths: dict[str, Path] = {}
        # axis_id -> last flushed index in buffer
        self._flush_indices: dict[str, int] = {}
        # last wall time we flushed
        self._last_flush_wall: float = time.monotonic()

        self._sessions_dir.mkdir(parents=True, exist_ok=True)

    def start(self, axis_map_ids: list[str]) -> None:
        """Initialize buffers for the given axis tcode IDs."""
        for tcode_id in axis_map_ids:
            self._buffers[tcode_id] = []
            self._flush_indices[tcode_id] = 0
            fname = f"{self._name}.{tcode_id}.funscript"
            self._file_paths[tcode_id] = self._sessions_dir / fname

    def record_tick(self, axis_values: dict[str, float], timestamp_ms: int) -> None:
        """Called by engine on every tick. Buffers one entry per axis."""
        if self._start_time_ms is None:
            self._start_time_ms = timestamp_ms

        for tcode_id, value in axis_values.items():
            if tcode_id in self._buffers:
                pos = round(value * 100)
                pos = max(0, min(100, pos))
                self._buffers[tcode_id].append({"at": timestamp_ms, "pos": pos})

        # Periodic flush — every second
        now = time.monotonic()
        if now - self._last_flush_wall >= _FLUSH_INTERVAL:
            self._flush_to_disk()
            self._last_flush_wall = now

    def _flush_to_disk(self) -> None:
        """Write any buffered entries not yet on disk (append mode)."""
        for tcode_id, buf in self._buffers.items():
            last_flushed = self._flush_indices.get(tcode_id, 0)
            new_entries = buf[last_flushed:]
            if not new_entries:
                continue
            path = self._file_paths[tcode_id]
            try:
                # Read existing file to merge actions (or create skeleton)
                if path.exists():
                    with open(path) as f:
                        data = json.load(f)
                else:
                    data = {
                        "version": 1,
                        "inverted": False,
                        "range": 100,
                        "actions": [],
                    }
                data["actions"].extend(new_entries)
                with open(path, "w") as f:
                    json.dump(data, f)
                self._flush_indices[tcode_id] = len(buf)
            except Exception:
                logger.exception("Error flushing funscript for axis %s", tcode_id)

    def stop(self) -> SessionMeta:
        """Flush all remaining data and return session metadata."""
        self._flush_to_disk()

        stopped_at = datetime.now(timezone.utc).isoformat()
        duration_s: Optional[float] = None
        if self._start_time_ms is not None:
            # Estimate from last action
            all_ats = [
                entry["at"]
                for buf in self._buffers.values()
                for entry in buf
            ]
            if all_ats:
                duration_s = round((max(all_ats) - self._start_time_ms) / 1000.0, 3)

        files = [str(p.name) for p in self._file_paths.values() if p.exists()]

        return SessionMeta(
            name=self._name,
            instance_id=self._instance_id,
            started_at=self._started_at,
            stopped_at=stopped_at,
            duration_s=duration_s,
            files=files,
        )
