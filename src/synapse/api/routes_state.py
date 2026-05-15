from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException

from synapse.api.deps import ctx

router = APIRouter()


@router.get("/api/status")
async def get_status() -> dict[str, Any]:
    uptime = time.monotonic() - ctx.start_time
    instances = []
    for inst_id, engine in ctx.engines.items():
        player = ctx.players.get(inst_id)
        instances.append({
            "id": inst_id,
            "connected": engine.is_connected(),
            "active_pattern": player.current_pattern().name if player and player.current_pattern() else None,
            "playing": player.is_playing() if player else False,
        })
    return {
        "status": "ok",
        "uptime_s": round(uptime, 2),
        "instances": instances,
    }


@router.get("/api/axes")
async def get_axes() -> list[dict[str, Any]]:
    axes = []
    # Get current values from first engine
    values: dict[str, float] = {}
    for engine in ctx.engines.values():
        values.update(engine.get_current_values())
        break

    for axis in ctx.axis_map.all():
        axes.append({
            "tcode_id": axis.tcode_id,
            "name": axis.name,
            "value_type": axis.value_type,
            "limit_min": axis.limit_min,
            "limit_max": axis.limit_max,
            "enabled": axis.enabled,
            "current_value": values.get(axis.tcode_id),
        })
    return axes


@router.get("/api/axes/{tcode_id}")
async def get_axis(tcode_id: str) -> dict[str, Any]:
    axis = ctx.axis_map.get_by_id(tcode_id)
    if not axis:
        raise HTTPException(status_code=404, detail=f"Axis {tcode_id} not found")
    values: dict[str, float] = {}
    for engine in ctx.engines.values():
        values.update(engine.get_current_values())
        break
    return {
        "tcode_id": axis.tcode_id,
        "name": axis.name,
        "value_type": axis.value_type,
        "limit_min": axis.limit_min,
        "limit_max": axis.limit_max,
        "enabled": axis.enabled,
        "current_value": values.get(axis.tcode_id),
    }


@router.get("/api/restim/state")
async def get_restim_state() -> dict[str, Any]:
    states = []
    for inst_id, client in ctx.restim_clients.items():
        state = client.get_state()
        states.append({
            "instance": inst_id,
            "playing": state.playing,
            "volume_ui": state.volume_ui,
            "volume_device": state.volume_device,
            "error": state.error,
        })
    return {"instances": states}


@router.get("/api/sensors")
async def get_sensors() -> list[dict[str, Any]]:
    readings = ctx.sensor_manager.get_all_with_restim()
    return [
        {
            "name": r.name,
            "value": r.value,
            "raw": r.raw,
            "error": r.error,
            "timestamp": r.timestamp,
        }
        for r in readings
    ]


@router.get("/api/sensors/{name}")
async def get_sensor(name: str) -> dict[str, Any]:
    reading = ctx.sensor_manager.get_by_name(name)
    if reading is None:
        raise HTTPException(status_code=404, detail=f"Sensor '{name}' not found")
    return {
        "name": reading.name,
        "value": reading.value,
        "raw": reading.raw,
        "error": reading.error,
        "timestamp": reading.timestamp,
    }


@router.get("/api/config")
async def get_config() -> dict[str, Any]:
    cfg = ctx.config
    # Return sanitized config (no secrets)
    return {
        "restim": {
            "ini_path": cfg.restim.ini_path,
            "instances": [
                {
                    "id": inst.id,
                    "host": inst.host,
                    "tcode_port": inst.tcode_port,
                    "rest_port": inst.rest_port,
                    "enabled": inst.enabled,
                }
                for inst in cfg.restim.instances
            ],
        },
        "engine": {
            "update_rate_hz": cfg.engine.update_rate_hz,
            "reconnect_delay_ms": cfg.engine.reconnect_delay_ms,
            "max_reconnect_delay_ms": cfg.engine.max_reconnect_delay_ms,
        },
        "api": {
            "host": cfg.api.host,
            "port": cfg.api.port,
            # auth_key omitted
        },
        "patterns": {
            "directory": cfg.patterns.directory,
            "transition": {
                "duck_amount": cfg.patterns.transition.duck_amount,
                "duck_ms": cfg.patterns.transition.duck_ms,
                "ramp_ms": cfg.patterns.transition.ramp_ms,
            },
        },
        "logging": {"level": cfg.logging.level},
    }
