from __future__ import annotations

"""Dependency injection container for FastAPI routes."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from synapse.axes import AxisMap
    from synapse.config import Config
    from synapse.engine import TCodeEngine
    from synapse.patterns.store import PatternStore
    from synapse.patterns.player import PatternPlayer
    from synapse.restim_client import RestimClient
    from synapse.sensors.manager import SensorManager
    from synapse.sessions.manager import SessionManager
    from synapse.profiles.store import ProfileStore


class AppContext:
    config: "Config"
    axis_map: "AxisMap"
    engines: "dict[str, TCodeEngine]"
    players: "dict[str, PatternPlayer]"
    store: "PatternStore"
    restim_clients: "dict[str, RestimClient]"
    sensor_manager: "SensorManager"
    session_manager: "SessionManager"
    profile_store: "ProfileStore"
    start_time: float


# Singleton context — set by main.py before serving
ctx = AppContext()
