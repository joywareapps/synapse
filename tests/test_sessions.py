from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from synapse.sessions.models import SessionMeta
from synapse.sessions.recorder import SessionRecorder
from synapse.sessions.manager import SessionManager


class TestSessionMeta:
    def test_to_dict_roundtrip(self):
        meta = SessionMeta(
            name="test-session",
            instance_id="primary",
            started_at="2026-01-01T00:00:00+00:00",
            stopped_at="2026-01-01T00:05:00+00:00",
            duration_s=300.0,
            files=["test-session.V0.funscript"],
        )
        d = meta.to_dict()
        assert d["name"] == "test-session"
        assert d["files"] == ["test-session.V0.funscript"]
        restored = SessionMeta.from_dict(d)
        assert restored.name == meta.name
        assert restored.duration_s == meta.duration_s
        assert restored.files == meta.files

    def test_from_dict_defaults(self):
        meta = SessionMeta.from_dict({
            "name": "x",
            "instance_id": "primary",
            "started_at": "2026-01-01T00:00:00+00:00",
        })
        assert meta.stopped_at is None
        assert meta.duration_s is None
        assert meta.files == []


class TestSessionRecorder:
    def test_start_creates_buffers(self, tmp_path):
        rec = SessionRecorder("my-session", "primary", tmp_path)
        rec.start(["V0", "L0"])
        assert "V0" in rec._buffers
        assert "L0" in rec._buffers

    def test_record_tick_buffers_values(self, tmp_path):
        rec = SessionRecorder("my-session", "primary", tmp_path)
        rec.start(["V0", "L0"])
        rec.record_tick({"V0": 0.5, "L0": 0.3}, timestamp_ms=100)
        assert len(rec._buffers["V0"]) == 1
        assert rec._buffers["V0"][0] == {"at": 100, "pos": 50}
        assert rec._buffers["L0"][0] == {"at": 100, "pos": 30}

    def test_record_tick_clamps_pos(self, tmp_path):
        rec = SessionRecorder("my-session", "primary", tmp_path)
        rec.start(["V0"])
        rec.record_tick({"V0": 1.5}, timestamp_ms=0)  # > 1.0 should clamp
        assert rec._buffers["V0"][0]["pos"] == 100
        rec.record_tick({"V0": -0.5}, timestamp_ms=20)  # < 0.0 should clamp
        assert rec._buffers["V0"][1]["pos"] == 0

    def test_record_tick_ignores_unknown_axis(self, tmp_path):
        rec = SessionRecorder("my-session", "primary", tmp_path)
        rec.start(["V0"])
        rec.record_tick({"V0": 0.5, "X9": 0.9}, timestamp_ms=0)
        assert "X9" not in rec._buffers

    def test_stop_returns_meta(self, tmp_path):
        rec = SessionRecorder("my-session", "primary", tmp_path)
        rec.start(["V0"])
        rec.record_tick({"V0": 0.4}, timestamp_ms=0)
        rec.record_tick({"V0": 0.5}, timestamp_ms=1000)
        meta = rec.stop()
        assert meta.name == "my-session"
        assert meta.instance_id == "primary"
        assert meta.stopped_at is not None
        assert meta.duration_s == pytest.approx(1.0, abs=0.01)

    def test_stop_flushes_to_disk(self, tmp_path):
        rec = SessionRecorder("my-session", "primary", tmp_path)
        rec.start(["V0"])
        rec.record_tick({"V0": 0.3}, timestamp_ms=0)
        rec.record_tick({"V0": 0.5}, timestamp_ms=20)
        meta = rec.stop()

        fpath = tmp_path / "my-session.V0.funscript"
        assert fpath.exists()
        data = json.loads(fpath.read_text())
        assert data["version"] == 1
        assert data["inverted"] is False
        assert data["range"] == 100
        assert len(data["actions"]) == 2
        assert data["actions"][0] == {"at": 0, "pos": 30}
        assert data["actions"][1] == {"at": 20, "pos": 50}

    def test_stop_returns_files_list(self, tmp_path):
        rec = SessionRecorder("my-session", "primary", tmp_path)
        rec.start(["V0", "L0"])
        rec.record_tick({"V0": 0.3, "L0": 0.5}, timestamp_ms=0)
        meta = rec.stop()
        assert len(meta.files) == 2
        assert any("V0" in f for f in meta.files)
        assert any("L0" in f for f in meta.files)

    def test_periodic_flush_writes_partial_data(self, tmp_path):
        rec = SessionRecorder("flush-test", "primary", tmp_path)
        rec.start(["V0"])
        rec.record_tick({"V0": 0.5}, timestamp_ms=0)
        # Force flush by manipulating last flush wall time
        rec._last_flush_wall = 0.0
        rec.record_tick({"V0": 0.6}, timestamp_ms=20)
        fpath = tmp_path / "flush-test.V0.funscript"
        assert fpath.exists()


class TestSessionManager:
    def test_start_and_stop_session(self, tmp_path):
        mgr = SessionManager(str(tmp_path))
        mgr.start_session("test", "primary", ["V0"])
        assert mgr.is_recording("primary")
        meta = mgr.stop_session("primary")
        assert meta is not None
        assert meta.name == "test"
        assert not mgr.is_recording("primary")

    def test_stop_nonexistent_returns_none(self, tmp_path):
        mgr = SessionManager(str(tmp_path))
        result = mgr.stop_session("nonexistent")
        assert result is None

    def test_record_tick_forwarded(self, tmp_path):
        mgr = SessionManager(str(tmp_path))
        mgr.start_session("tick-test", "primary", ["V0"])
        mgr.record_tick("primary", {"V0": 0.5}, 0)
        mgr.record_tick("primary", {"V0": 0.6}, 20)
        meta = mgr.stop_session("primary")
        assert meta is not None

    def test_record_tick_noop_when_not_recording(self, tmp_path):
        mgr = SessionManager(str(tmp_path))
        # Should not raise
        mgr.record_tick("primary", {"V0": 0.5}, 0)

    def test_sidecar_written_on_stop(self, tmp_path):
        mgr = SessionManager(str(tmp_path))
        mgr.start_session("sidecar-test", "primary", ["V0"])
        mgr.record_tick("primary", {"V0": 0.5}, 0)
        mgr.stop_session("primary")
        sidecar = tmp_path / "sidecar-test.meta.json"
        assert sidecar.exists()
        data = json.loads(sidecar.read_text())
        assert data["name"] == "sidecar-test"

    def test_list_sessions(self, tmp_path):
        mgr = SessionManager(str(tmp_path))
        mgr.start_session("alpha", "primary", ["V0"])
        mgr.record_tick("primary", {"V0": 0.1}, 0)
        mgr.stop_session("primary")
        mgr.start_session("beta", "primary", ["V0"])
        mgr.record_tick("primary", {"V0": 0.2}, 0)
        mgr.stop_session("primary")
        sessions = mgr.list_sessions()
        names = [s.name for s in sessions]
        assert "alpha" in names
        assert "beta" in names

    def test_get_session(self, tmp_path):
        mgr = SessionManager(str(tmp_path))
        mgr.start_session("get-test", "primary", ["V0"])
        mgr.stop_session("primary")
        meta = mgr.get_session("get-test")
        assert meta is not None
        assert meta.name == "get-test"

    def test_get_nonexistent_session(self, tmp_path):
        mgr = SessionManager(str(tmp_path))
        assert mgr.get_session("nope") is None

    def test_delete_session(self, tmp_path):
        mgr = SessionManager(str(tmp_path))
        mgr.start_session("del-test", "primary", ["V0"])
        mgr.record_tick("primary", {"V0": 0.5}, 0)
        mgr.stop_session("primary")
        removed = mgr.delete_session("del-test")
        assert removed is True
        assert mgr.get_session("del-test") is None
        # Funscript file should also be gone
        assert not any(tmp_path.glob("del-test.*.funscript"))

    def test_delete_nonexistent_session(self, tmp_path):
        mgr = SessionManager(str(tmp_path))
        assert mgr.delete_session("nope") is False

    def test_starting_session_while_one_active_stops_old_one(self, tmp_path):
        mgr = SessionManager(str(tmp_path))
        mgr.start_session("first", "primary", ["V0"])
        mgr.start_session("second", "primary", ["V0"])
        # first should have been auto-stopped and sidecar written
        sidecar = tmp_path / "first.meta.json"
        assert sidecar.exists()
        assert mgr.is_recording("primary")
        mgr.stop_session("primary")
