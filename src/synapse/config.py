from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class RestimInstanceConfig:
    id: str
    host: str
    tcode_port: int
    rest_port: int
    enabled: bool = True


@dataclass
class RestimConfig:
    ini_path: str = "./restim.ini"
    instances: list[RestimInstanceConfig] = field(default_factory=list)


@dataclass
class EngineConfig:
    update_rate_hz: int = 50
    reconnect_delay_ms: int = 1000
    max_reconnect_delay_ms: int = 30000


@dataclass
class ApiConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    auth_key: str = ""


@dataclass
class McpConfig:
    enabled: bool = True
    transport: str = "sse"
    port: int = 8081
    localhost_only: bool = True
    bearer_token: str = ""


@dataclass
class TransitionConfig:
    duck_amount: float = 1.0
    duck_ms: int = 200
    ramp_ms: int = 400


@dataclass
class PatternsConfig:
    directory: str = "./patterns"
    transition: TransitionConfig = field(default_factory=TransitionConfig)


@dataclass
class AS5311Config:
    enabled: bool = False
    url: str = "ws://localhost:12346/sensors/as5311"
    threshold_mm: float = 0.0
    range_mm: float = 2.0


@dataclass
class HeartRateConfig:
    enabled: bool = False
    device_address: str = ""
    device_label: str = ""
    scale_min_bpm: int = 40
    scale_max_bpm: int = 180


@dataclass
class SensorsConfig:
    as5311: AS5311Config = field(default_factory=AS5311Config)
    heart_rate: HeartRateConfig = field(default_factory=HeartRateConfig)


@dataclass
class SessionsConfig:
    directory: str = "./sessions"
    auto_name: bool = True


@dataclass
class ProfilesConfig:
    directory: str = "./profiles"


@dataclass
class LoggingConfig:
    level: str = "INFO"


@dataclass
class AgentConfig:
    provider: str = "auto"                        # "ollama" | "lm_studio" | "auto"
    ollama_url: str = "http://localhost:11434"
    lm_studio_url: str = "http://localhost:1234"
    model: str = ""                               # empty = first tool-capable model found
    loop_interval_s: float = 30.0
    loop_mode: str = "observe"
    max_tool_calls_per_tick: int = 2
    system_prompt_extra: str = ""


@dataclass
class Config:
    restim: RestimConfig = field(default_factory=RestimConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    mcp: McpConfig = field(default_factory=McpConfig)
    patterns: PatternsConfig = field(default_factory=PatternsConfig)
    sensors: SensorsConfig = field(default_factory=SensorsConfig)
    sessions: SessionsConfig = field(default_factory=SessionsConfig)
    profiles: ProfilesConfig = field(default_factory=ProfilesConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)


def _set_nested(d: dict, keys: list[str], value: str) -> None:
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    # Try to coerce value to appropriate type
    final_key = keys[-1]
    existing = d.get(final_key)
    if isinstance(existing, bool):
        d[final_key] = value.lower() in ("1", "true", "yes")
    elif isinstance(existing, int):
        d[final_key] = int(value)
    elif isinstance(existing, float):
        d[final_key] = float(value)
    else:
        d[final_key] = value


def _apply_env_overrides(data: dict) -> dict:
    prefix = "SYNAPSE_"
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        path = key[len(prefix):].lower().split("_")
        # Try to match path segments against nested dict keys
        # We do greedy matching: try all splits of the underscore-separated path
        _apply_path(data, path, value)
    return data


def _apply_path(data: dict, parts: list[str], value: str) -> bool:
    """Try to match parts against nested dict keys, returning True on success."""
    if not parts:
        return False
    # Try progressively longer key segments at this level
    for i in range(1, len(parts) + 1):
        candidate = "_".join(parts[:i])
        if candidate in data:
            if i == len(parts):
                # Leaf — set value
                existing = data[candidate]
                if isinstance(existing, bool):
                    data[candidate] = value.lower() in ("1", "true", "yes")
                elif isinstance(existing, int):
                    try:
                        data[candidate] = int(value)
                    except ValueError:
                        data[candidate] = value
                elif isinstance(existing, float):
                    try:
                        data[candidate] = float(value)
                    except ValueError:
                        data[candidate] = value
                else:
                    data[candidate] = value
                return True
            elif isinstance(data[candidate], dict):
                if _apply_path(data[candidate], parts[i:], value):
                    return True
    return False


def _dict_to_config(data: dict) -> Config:
    restim_data = data.get("restim", {})
    instances_data = restim_data.get("instances", [])
    instances = [
        RestimInstanceConfig(
            id=inst.get("id", "primary"),
            host=inst.get("host", "localhost"),
            tcode_port=int(inst.get("tcode_port", 12347)),
            rest_port=int(inst.get("rest_port", 12348)),
            enabled=bool(inst.get("enabled", True)),
        )
        for inst in instances_data
    ]
    restim = RestimConfig(
        ini_path=restim_data.get("ini_path", "./restim.ini"),
        instances=instances,
    )

    engine_data = data.get("engine", {})
    engine = EngineConfig(
        update_rate_hz=int(engine_data.get("update_rate_hz", 50)),
        reconnect_delay_ms=int(engine_data.get("reconnect_delay_ms", 1000)),
        max_reconnect_delay_ms=int(engine_data.get("max_reconnect_delay_ms", 30000)),
    )

    api_data = data.get("api", {})
    api = ApiConfig(
        host=api_data.get("host", "0.0.0.0"),
        port=int(api_data.get("port", 8080)),
        auth_key=api_data.get("auth_key", ""),
    )

    mcp_data = data.get("mcp", {})
    mcp = McpConfig(
        enabled=bool(mcp_data.get("enabled", True)),
        transport=mcp_data.get("transport", "sse"),
        port=int(mcp_data.get("port", 8081)),
        localhost_only=bool(mcp_data.get("localhost_only", True)),
        bearer_token=mcp_data.get("bearer_token", ""),
    )

    patterns_data = data.get("patterns", {})
    transition_data = patterns_data.get("transition", {})
    transition = TransitionConfig(
        duck_amount=float(transition_data.get("duck_amount", 1.0)),
        duck_ms=int(transition_data.get("duck_ms", 200)),
        ramp_ms=int(transition_data.get("ramp_ms", 400)),
    )
    patterns = PatternsConfig(
        directory=patterns_data.get("directory", "./patterns"),
        transition=transition,
    )

    sensors_data = data.get("sensors", {})
    as5311_data = sensors_data.get("as5311", {})
    as5311 = AS5311Config(
        enabled=bool(as5311_data.get("enabled", False)),
        url=as5311_data.get("url", "ws://localhost:12346/sensors/as5311"),
        threshold_mm=float(as5311_data.get("threshold_mm", 0.0)),
        range_mm=float(as5311_data.get("range_mm", 2.0)),
    )
    hr_data = sensors_data.get("heart_rate", {})
    heart_rate = HeartRateConfig(
        enabled=bool(hr_data.get("enabled", False)),
        device_address=hr_data.get("device_address", ""),
        device_label=hr_data.get("device_label", ""),
        scale_min_bpm=int(hr_data.get("scale_min_bpm", 40)),
        scale_max_bpm=int(hr_data.get("scale_max_bpm", 180)),
    )
    sensors = SensorsConfig(as5311=as5311, heart_rate=heart_rate)

    sessions_data = data.get("sessions", {})
    sessions = SessionsConfig(
        directory=sessions_data.get("directory", "./sessions"),
        auto_name=bool(sessions_data.get("auto_name", True)),
    )

    profiles_data = data.get("profiles", {})
    profiles = ProfilesConfig(
        directory=profiles_data.get("directory", "./profiles"),
    )

    logging_data = data.get("logging", {})
    logging_cfg = LoggingConfig(level=logging_data.get("level", "INFO"))

    agent_data = data.get("agent", {})
    agent_cfg = AgentConfig(
        provider=agent_data.get("provider", "auto"),
        ollama_url=agent_data.get("ollama_url", "http://localhost:11434"),
        lm_studio_url=agent_data.get("lm_studio_url", "http://localhost:1234"),
        model=agent_data.get("model", ""),
        loop_interval_s=float(agent_data.get("loop_interval_s", 30.0)),
        loop_mode=agent_data.get("loop_mode", "observe"),
        max_tool_calls_per_tick=int(agent_data.get("max_tool_calls_per_tick", 2)),
        system_prompt_extra=agent_data.get("system_prompt_extra", ""),
    )

    return Config(
        restim=restim,
        engine=engine,
        api=api,
        mcp=mcp,
        patterns=patterns,
        sensors=sensors,
        sessions=sessions,
        profiles=profiles,
        logging=logging_cfg,
        agent=agent_cfg,
    )


def load_config(path: Optional[str] = None) -> Config:
    data: dict = {}
    if path is None:
        path = "synapse.yaml"

    config_path = Path(path)
    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

    _apply_env_overrides(data)
    return _dict_to_config(data)
