from __future__ import annotations

"""Tests for setup check endpoint and BLE scan."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from synapse.api.app import create_app
from synapse.api.deps import ctx


@pytest.fixture(autouse=True)
def _patch_ctx(tmp_path):
    """Wire a minimal AppContext so route handlers don't crash."""
    from synapse.config import (
        Config, RestimConfig, RestimInstanceConfig, EngineConfig,
        ApiConfig, McpConfig, PatternsConfig, TransitionConfig,
        SensorsConfig, AS5311Config, HeartRateConfig, SessionsConfig,
        ProfilesConfig, LoggingConfig, AgentConfig,
    )
    import time

    inst = RestimInstanceConfig(
        id="primary", host="localhost", tcode_port=12347, rest_port=12348
    )
    config = Config(
        restim=RestimConfig(ini_path="./nonexistent.ini", instances=[inst]),
        engine=EngineConfig(),
        api=ApiConfig(),
        mcp=McpConfig(),
        patterns=PatternsConfig(transition=TransitionConfig()),
        sensors=SensorsConfig(as5311=AS5311Config(), heart_rate=HeartRateConfig()),
        sessions=SessionsConfig(),
        profiles=ProfilesConfig(),
        logging=LoggingConfig(),
        agent=AgentConfig(),
    )

    mock_engine = MagicMock()
    mock_engine.is_connected.return_value = False

    mock_sensor_manager = MagicMock()
    mock_sensor_manager.get_all_with_restim.return_value = []

    ctx.config = config
    ctx.engines = {"primary": mock_engine}
    ctx.players = {}
    ctx.sensor_manager = mock_sensor_manager
    ctx.start_time = time.monotonic()

    yield


@pytest.fixture
def app():
    return create_app()


# ── /api/setup/check ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_setup_check_returns_structure(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with (
            patch("synapse.api.routes_setup._probe_tcp", new_callable=AsyncMock, return_value=False),
            patch("synapse.api.routes_setup._probe_http", new_callable=AsyncMock, return_value=False),
            patch("synapse.agent.llm_client.detect_providers", new_callable=AsyncMock, return_value=[]),
        ):
            resp = await client.get("/api/setup/check")

    assert resp.status_code == 200
    data = resp.json()
    assert "ok" in data
    assert "restim" in data
    assert "llm_providers" in data
    assert "sensors" in data
    assert "ini" in data


@pytest.mark.asyncio
async def test_setup_check_restim_entry(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with (
            patch("synapse.api.routes_setup._probe_tcp", new_callable=AsyncMock, return_value=True),
            patch("synapse.api.routes_setup._probe_http", new_callable=AsyncMock, return_value=True),
            patch("synapse.agent.llm_client.detect_providers", new_callable=AsyncMock, return_value=[]),
        ):
            resp = await client.get("/api/setup/check")

    data = resp.json()
    assert len(data["restim"]) == 1
    entry = data["restim"][0]
    assert entry["id"] == "primary"
    assert entry["tcode_reachable"] is True
    assert entry["rest_reachable"] is True


@pytest.mark.asyncio
async def test_setup_check_ini_missing(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with (
            patch("synapse.api.routes_setup._probe_tcp", new_callable=AsyncMock, return_value=False),
            patch("synapse.api.routes_setup._probe_http", new_callable=AsyncMock, return_value=False),
            patch("synapse.agent.llm_client.detect_providers", new_callable=AsyncMock, return_value=[]),
        ):
            resp = await client.get("/api/setup/check")

    data = resp.json()
    assert data["ini"]["path"] == "./nonexistent.ini"
    assert data["ini"]["exists"] is False
    assert data["ok"] is False


@pytest.mark.asyncio
async def test_setup_check_llm_provider_included(app):
    from synapse.agent.llm_client import LLMProvider
    provider = LLMProvider(
        name="ollama",
        base_url="http://localhost:11434",
        models=["llama3.1", "phi4"],
        tool_capable_models=["llama3.1", "phi4"],
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with (
            patch("synapse.api.routes_setup._probe_tcp", new_callable=AsyncMock, return_value=False),
            patch("synapse.api.routes_setup._probe_http", new_callable=AsyncMock, return_value=False),
            patch("synapse.agent.llm_client.detect_providers", new_callable=AsyncMock, return_value=[provider]),
        ):
            resp = await client.get("/api/setup/check")

    data = resp.json()
    assert len(data["llm_providers"]) == 1
    assert data["llm_providers"][0]["name"] == "ollama"
    assert "llama3.1" in data["llm_providers"][0]["models"]


# ── /api/sensors/ble-scan ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ble_scan_returns_devices(app):
    mock_device = MagicMock()
    mock_device.name = "Polar H10"
    mock_device.address = "AA:BB:CC:DD:EE:FF"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # BleakScanner is imported inside the route handler, so patch at the bleak module level
        with patch("bleak.BleakScanner.discover", new_callable=AsyncMock, return_value=[mock_device]):
            resp = await client.get("/api/sensors/ble-scan")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(d.get("name") == "Polar H10" for d in data)


@pytest.mark.asyncio
async def test_ble_scan_handles_exception(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("bleak.BleakScanner.discover", new_callable=AsyncMock, side_effect=OSError("No Bluetooth")):
            resp = await client.get("/api/sensors/ble-scan")

    assert resp.status_code == 200
    data = resp.json()
    # Returns either empty list or a single error-entry dict — must not 500
    assert isinstance(data, list)


# ── wizard helpers ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_probe_tcp_unreachable():
    from synapse.api.routes_setup import _probe_tcp
    result = await _probe_tcp("localhost", 1, timeout=0.2)
    assert result is False


@pytest.mark.asyncio
async def test_probe_http_unreachable():
    from synapse.api.routes_setup import _probe_http
    result = await _probe_http("http://localhost:1/bad", timeout=0.2)
    assert result is False


def test_wizard_find_ini_returns_none_when_missing():
    from synapse.setup.wizard import _find_restim_ini
    from unittest.mock import patch
    with patch("synapse.setup.wizard._ini_candidates", return_value=[]):
        result = _find_restim_ini()
    assert result is None
