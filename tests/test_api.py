from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from synapse.api.app import create_app
from synapse.api.deps import ctx
from synapse.axes import AxisMap
from synapse.config import (
    Config,
    EngineConfig,
    McpConfig,
    PatternsConfig,
    RestimConfig,
    SensorsConfig,
    TransitionConfig,
    ApiConfig,
    LoggingConfig,
)
from synapse.patterns.player import PatternPlayer
from synapse.patterns.store import PatternStore
from synapse.sensors.manager import SensorManager


def _make_fake_engine():
    class FakeEngine:
        def get_current_values(self):
            return {"L0": 0.5, "V0": 0.3}

        def is_connected(self):
            return True

        async def emergency_stop(self):
            pass

        _current_values = {}

    return FakeEngine()


def _make_fake_restim_client():
    class FakeClient:
        def get_state(self):
            class S:
                playing = False
                volume_ui = 0.5
                volume_device = 0.48
                error = None
            return S()

        async def start_playback(self):
            return True

        async def stop_playback(self):
            return True

    return FakeClient()


@pytest.fixture
def client(tmp_path):
    app = create_app()

    axis_map = AxisMap()
    store = PatternStore(str(tmp_path / "patterns"))
    store.load_all()

    player = PatternPlayer()
    fake_engine = _make_fake_engine()
    fake_restim = _make_fake_restim_client()

    config = Config(
        restim=RestimConfig(),
        engine=EngineConfig(),
        api=ApiConfig(),
        mcp=McpConfig(),
        patterns=PatternsConfig(
            directory=str(tmp_path / "patterns"),
            transition=TransitionConfig(),
        ),
        sensors=SensorsConfig(),
        logging=LoggingConfig(),
    )

    ctx.config = config
    ctx.axis_map = axis_map
    ctx.engines = {"primary": fake_engine}
    ctx.players = {"primary": player}
    ctx.store = store
    ctx.restim_clients = {"primary": fake_restim}
    ctx.sensor_manager = SensorManager(config.sensors)
    ctx.start_time = time.monotonic()

    return TestClient(app)


class TestStatusEndpoint:
    def test_get_status(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "uptime_s" in data
        assert isinstance(data["instances"], list)

    def test_status_includes_instance(self, client):
        resp = client.get("/api/status")
        data = resp.json()
        assert len(data["instances"]) == 1
        assert data["instances"][0]["id"] == "primary"
        assert data["instances"][0]["connected"] is True


class TestAxesEndpoints:
    def test_get_all_axes(self, client):
        resp = client.get("/api/axes")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        names = [a["name"] for a in data]
        assert "alpha" in names
        assert "volume" in names

    def test_get_axis_by_id(self, client):
        resp = client.get("/api/axes/L0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tcode_id"] == "L0"
        assert data["name"] == "alpha"

    def test_get_unknown_axis_404(self, client):
        resp = client.get("/api/axes/X9")
        assert resp.status_code == 404


class TestRestimStateEndpoint:
    def test_get_restim_state(self, client):
        resp = client.get("/api/restim/state")
        assert resp.status_code == 200
        data = resp.json()
        assert "instances" in data
        assert len(data["instances"]) == 1
        assert data["instances"][0]["instance"] == "primary"


class TestSensorsEndpoints:
    def test_get_sensors_empty(self, client):
        resp = client.get("/api/sensors")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_unknown_sensor_404(self, client):
        resp = client.get("/api/sensors/nonexistent")
        assert resp.status_code == 404


class TestPatternEndpoints:
    def test_list_patterns_empty(self, client):
        resp = client.get("/api/patterns")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_and_get_pattern(self, client):
        resp = client.post("/api/patterns", json={
            "name": "test-pattern",
            "description": "A test",
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "test-pattern"

        resp = client.get("/api/patterns/test-pattern")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "test-pattern"
        assert data["description"] == "A test"

    def test_create_duplicate_409(self, client):
        client.post("/api/patterns", json={"name": "dup"})
        resp = client.post("/api/patterns", json={"name": "dup"})
        assert resp.status_code == 409

    def test_delete_pattern(self, client):
        client.post("/api/patterns", json={"name": "to-delete"})
        resp = client.delete("/api/patterns/to-delete")
        assert resp.status_code == 200

        resp = client.get("/api/patterns/to-delete")
        assert resp.status_code == 404

    def test_get_unknown_pattern_404(self, client):
        resp = client.get("/api/patterns/does-not-exist")
        assert resp.status_code == 404

    def test_patch_pattern(self, client):
        client.post("/api/patterns", json={"name": "patchable", "description": "old"})
        resp = client.patch("/api/patterns/patchable", json={"description": "new"})
        assert resp.status_code == 200
        resp = client.get("/api/patterns/patchable")
        assert resp.json()["description"] == "new"


class TestLayerEndpoints:
    def test_add_and_list_layers(self, client):
        client.post("/api/patterns", json={"name": "with-layers"})
        resp = client.post("/api/patterns/with-layers/layers", json={"blend": "set"})
        assert resp.status_code == 200
        layer_name = resp.json()["layer_name"]

        resp = client.get("/api/patterns/with-layers/layers")
        assert resp.status_code == 200
        layers = resp.json()
        assert len(layers) == 1
        assert layers[0]["name"] == layer_name

    def test_add_layer_axis(self, client):
        client.post("/api/patterns", json={"name": "with-axis"})
        client.post("/api/patterns/with-axis/layers", json={"name": "l1", "blend": "set"})

        resp = client.put("/api/patterns/with-axis/layers/l1/axes/V0", json={
            "waveform": "sine",
            "frequency": 1.0,
            "amplitude": 0.5,
            "center": 0.5,
        })
        assert resp.status_code == 200

        resp = client.get("/api/patterns/with-axis/layers/l1/axes/V0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["waveform"] == "sine"
        assert data["amplitude"] == 0.5

    def test_delete_layer(self, client):
        client.post("/api/patterns", json={"name": "layer-delete"})
        client.post("/api/patterns/layer-delete/layers", json={"name": "del-me", "blend": "set"})
        resp = client.delete("/api/patterns/layer-delete/layers/del-me")
        assert resp.status_code == 200

        resp = client.get("/api/patterns/layer-delete/layers")
        assert resp.json() == []


class TestControlEndpoints:
    def test_emergency_stop(self, client):
        resp = client.post("/api/emergency-stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_set_volume(self, client):
        resp = client.post("/api/volume", json={"value": 0.7})
        assert resp.status_code == 200
        assert resp.json()["value"] == pytest.approx(0.7)

    def test_set_axis_value(self, client):
        resp = client.post("/api/axes/V0/value", json={"value": 0.5})
        assert resp.status_code == 200

    def test_set_unknown_axis_404(self, client):
        resp = client.post("/api/axes/X9/value", json={"value": 0.5})
        assert resp.status_code == 404

    def test_spike(self, client):
        resp = client.post("/api/spike", json={"intensity": 0.3, "on_ms": 200, "off_ms": 100, "repeat": 1})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestConfigEndpoints:
    def test_get_config(self, client):
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "engine" in data
        assert "patterns" in data
        # auth_key should not be present
        assert "auth_key" not in data.get("api", {})
