from __future__ import annotations

"""Setup/diagnostics endpoints — health check and BLE device scan."""

import asyncio
import logging
from typing import Any

import httpx
from fastapi import APIRouter

from synapse.api.deps import ctx

router = APIRouter(tags=["setup"])
logger = logging.getLogger(__name__)


# ── /api/setup/check ─────────────────────────────────────────────────────────

@router.get("/api/setup/check")
async def setup_check() -> dict[str, Any]:
    """
    Validate the running configuration.
    Returns a summary of what is reachable: Restim instances, LLM providers,
    sensors, and the INI path status.
    """
    result: dict[str, Any] = {
        "ok": True,
        "restim": [],
        "llm_providers": [],
        "sensors": [],
        "ini": {},
    }

    # ── Restim instances ──────────────────────────────────────────────────────
    for inst in ctx.config.restim.instances:
        if not inst.enabled:
            continue
        tcode_ok = await _probe_tcp(inst.host, inst.tcode_port)
        rest_ok = await _probe_http(f"http://{inst.host}:{inst.rest_port}/v1/status")
        connected = False
        try:
            engine = ctx.engines.get(inst.id)
            connected = engine.is_connected() if engine else False
        except Exception:
            pass

        entry = {
            "id": inst.id,
            "host": inst.host,
            "tcode_port": inst.tcode_port,
            "tcode_reachable": tcode_ok,
            "rest_port": inst.rest_port,
            "rest_reachable": rest_ok,
            "engine_connected": connected,
            "ok": tcode_ok,
        }
        result["restim"].append(entry)
        if not tcode_ok:
            result["ok"] = False

    # ── INI ───────────────────────────────────────────────────────────────────
    import pathlib
    ini_path = ctx.config.restim.ini_path
    ini_exists = pathlib.Path(ini_path).exists()
    result["ini"] = {"path": ini_path, "exists": ini_exists}
    if not ini_exists:
        result["ok"] = False

    # ── LLM providers ─────────────────────────────────────────────────────────
    try:
        from synapse.agent.llm_client import detect_providers
        providers = await detect_providers(
            ctx.config.agent.ollama_url,
            ctx.config.agent.lm_studio_url,
        )
        for p in providers:
            result["llm_providers"].append({
                "name": p.name,
                "base_url": p.base_url,
                "models": p.models,
                "tool_capable_models": p.tool_capable_models,
                "ok": bool(p.models),
            })
    except Exception as exc:
        logger.debug("LLM provider probe failed: %s", exc)

    # ── Sensors ───────────────────────────────────────────────────────────────
    try:
        readings = ctx.sensor_manager.get_all_with_restim()
        for r in readings:
            result["sensors"].append({
                "name": r.name,
                "value": r.value,
                "error": r.error,
                "ok": r.error is None,
            })
    except Exception as exc:
        logger.debug("Sensor check failed: %s", exc)

    return result


# ── /api/sensors/ble-scan ─────────────────────────────────────────────────────

@router.get("/api/sensors/ble-scan")
async def ble_scan(timeout: float = 5.0) -> list[dict[str, Any]]:
    """
    Scan for nearby Bluetooth LE devices.
    Useful for finding the address of a heart rate monitor.
    Returns devices sorted by name.
    """
    try:
        from bleak import BleakScanner
    except ImportError:
        return [{"error": "bleak not installed"}]

    try:
        devices = await BleakScanner.discover(timeout=timeout)
        return sorted(
            [{"name": d.name or "Unknown", "address": d.address} for d in devices],
            key=lambda d: d["name"].lower(),
        )
    except Exception as exc:
        logger.warning("BLE scan failed: %s", exc)
        return [{"error": str(exc)}]


# ── helpers ───────────────────────────────────────────────────────────────────

async def _probe_tcp(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


async def _probe_http(url: str, timeout: float = 2.0) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            return resp.status_code == 200
    except Exception:
        return False
