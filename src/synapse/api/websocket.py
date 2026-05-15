from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from synapse.api.deps import ctx

router = APIRouter()
logger = logging.getLogger(__name__)

WS_RATE_HZ = 10
WS_INTERVAL = 1.0 / WS_RATE_HZ

_connections: set[WebSocket] = set()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    _connections.add(websocket)
    try:
        while True:
            await asyncio.sleep(WS_INTERVAL)
            payload = _build_payload()
            await websocket.send_text(json.dumps(payload))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("WS disconnected: %s", e)
    finally:
        _connections.discard(websocket)


def _build_payload() -> dict[str, Any]:
    axes: dict[str, float] = {}
    for engine in ctx.engines.values():
        axes.update(engine.get_current_values())

    sensors = []
    try:
        for r in ctx.sensor_manager.get_all_with_restim():
            sensors.append({
                "name": r.name,
                "value": r.value,
                "raw": r.raw,
                "error": r.error,
            })
    except Exception:
        pass

    return {
        "t": time.time(),
        "axes": axes,
        "sensors": sensors,
    }
