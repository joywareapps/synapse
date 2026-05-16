from __future__ import annotations

"""Config REST endpoints (spec §8.1/§8.2)."""

import tempfile
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, File

from synapse.api.deps import ctx

router = APIRouter(tags=["config"])


@router.get("/api/config")
async def get_config() -> dict[str, Any]:
    """Return sanitized current config (no auth_key/bearer_token values)."""
    cfg = ctx.config
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
        "mcp": {
            "enabled": cfg.mcp.enabled,
            "transport": cfg.mcp.transport,
            "port": cfg.mcp.port,
            "localhost_only": cfg.mcp.localhost_only,
            # bearer_token omitted
        },
        "patterns": {
            "directory": cfg.patterns.directory,
            "transition": {
                "duck_amount": cfg.patterns.transition.duck_amount,
                "duck_ms": cfg.patterns.transition.duck_ms,
                "ramp_ms": cfg.patterns.transition.ramp_ms,
            },
        },
        "sensors": {
            "as5311": {
                "enabled": cfg.sensors.as5311.enabled,
                "url": cfg.sensors.as5311.url,
                "threshold_mm": cfg.sensors.as5311.threshold_mm,
                "range_mm": cfg.sensors.as5311.range_mm,
            },
            "heart_rate": {
                "enabled": cfg.sensors.heart_rate.enabled,
                "device_label": cfg.sensors.heart_rate.device_label,
                "scale_min_bpm": cfg.sensors.heart_rate.scale_min_bpm,
                "scale_max_bpm": cfg.sensors.heart_rate.scale_max_bpm,
                # device_address omitted (could be PII)
            },
        },
        "sessions": {
            "directory": cfg.sessions.directory,
            "auto_name": cfg.sessions.auto_name,
        },
        "profiles": {
            "directory": cfg.profiles.directory,
        },
        "logging": {"level": cfg.logging.level},
        "agent": {
            "provider": cfg.agent.provider,
            "ollama_url": cfg.agent.ollama_url,
            "lm_studio_url": cfg.agent.lm_studio_url,
            "model": cfg.agent.model,
            "loop_interval_s": cfg.agent.loop_interval_s,
            "loop_mode": cfg.agent.loop_mode,
            "max_tool_calls_per_tick": cfg.agent.max_tool_calls_per_tick,
        },
    }


@router.post("/api/config/reload")
async def config_reload() -> dict[str, Any]:
    """Re-parse the INI file and update the axis map; return new axis count."""
    from synapse.ini_parser import parse_ini_file

    ini_path = ctx.config.restim.ini_path
    # Prefer stored config_path if available (from main.py)
    config_path = getattr(ctx, "config_path", None)
    if config_path is not None:
        ini_path = ctx.config.restim.ini_path

    if not Path(ini_path).exists():
        raise HTTPException(status_code=404, detail=f"INI file not found: {ini_path}")

    axes = parse_ini_file(ini_path)
    ctx.axis_map.apply_ini(axes)
    return {"status": "ok", "axis_count": len(axes)}


@router.post("/api/config/reload-ini")
async def config_reload_ini() -> dict[str, Any]:
    """Alias for /api/config/reload."""
    from synapse.ini_parser import parse_ini_file

    ini_path = ctx.config.restim.ini_path
    if not Path(ini_path).exists():
        raise HTTPException(status_code=404, detail=f"INI file not found: {ini_path}")

    axes = parse_ini_file(ini_path)
    ctx.axis_map.apply_ini(axes)
    return {"status": "ok", "axis_count": len(axes)}


@router.post("/api/config/upload-ini")
async def upload_ini(file: UploadFile = File(...)) -> dict[str, Any]:
    """
    Multipart file upload: parse INI content, apply to axis map, return parsed axes.
    """
    from synapse.ini_parser import parse_ini

    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    # Write to tempfile for safety (parse_ini accepts string directly)
    axes = parse_ini(text)
    ctx.axis_map.apply_ini(axes)

    return {
        "status": "ok",
        "axis_count": len(axes),
        "axes": {
            name: {
                "tcode_id": a.tcode_id,
                "name": a.name,
                "value_type": a.value_type,
                "limit_min": a.limit_min,
                "limit_max": a.limit_max,
                "enabled": a.enabled,
            }
            for name, a in axes.items()
        },
    }
