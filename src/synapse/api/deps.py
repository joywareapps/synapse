from __future__ import annotations

"""Dependency injection container for FastAPI routes."""

from typing import TYPE_CHECKING, Optional

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
    from synapse.agent.agent import SynapseAgent
    from synapse.agent.loop import AgentLoop


class AppContext:
    config: "Config"
    config_path: "Optional[str]" = None
    axis_map: "AxisMap"
    engines: "dict[str, TCodeEngine]"
    players: "dict[str, PatternPlayer]"
    store: "PatternStore"
    restim_clients: "dict[str, RestimClient]"
    sensor_manager: "SensorManager"
    session_manager: "SessionManager"
    profile_store: "ProfileStore"
    start_time: float

    # Agent (§18) — optional, created on first use
    agent: "Optional[SynapseAgent]" = None
    agent_loop: "Optional[AgentLoop]" = None
    active_profile_name: "Optional[str]" = None


# Singleton context — set by main.py before serving
ctx = AppContext()
