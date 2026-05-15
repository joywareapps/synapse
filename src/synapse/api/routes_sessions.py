from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from synapse.api.deps import ctx

router = APIRouter()


class StartSessionRequest(BaseModel):
    name: Optional[str] = None
    instance: str = "primary"
    profile_name: Optional[str] = None


class StopSessionRequest(BaseModel):
    instance: str = "primary"
    profile_name: Optional[str] = None


@router.post("/api/sessions/start")
async def start_session(req: StartSessionRequest) -> dict[str, Any]:
    name = req.name
    if not name:
        if ctx.config.sessions.auto_name:
            name = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        else:
            raise HTTPException(status_code=400, detail="name is required when auto_name is disabled")

    # Collect axis IDs from engine if available
    engine = ctx.engines.get(req.instance)
    axis_ids: list[str] = []
    if engine:
        axis_ids = [a.tcode_id for a in ctx.axis_map.all_enabled()]

    ctx.session_manager.start_session(name, req.instance, axis_ids)
    return {"status": "recording", "name": name, "instance": req.instance}


@router.post("/api/sessions/stop")
async def stop_session(req: StopSessionRequest) -> dict[str, Any]:
    meta = ctx.session_manager.stop_session(req.instance)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"No active session for instance '{req.instance}'")

    # Update profile if provided
    if req.profile_name:
        profile = ctx.profile_store.get(req.profile_name)
        if profile:
            profile.session_count += 1
            if meta.duration_s:
                profile.total_duration_s += meta.duration_s
            profile.last_session_at = meta.stopped_at
            from datetime import datetime, timezone as tz
            profile.updated_at = datetime.now(tz.utc).isoformat()
            ctx.profile_store.save(profile)

    return meta.to_dict()


@router.get("/api/sessions")
async def list_sessions() -> list[dict[str, Any]]:
    return [m.to_dict() for m in ctx.session_manager.list_sessions()]


@router.get("/api/sessions/{name}")
async def get_session(name: str) -> dict[str, Any]:
    meta = ctx.session_manager.get_session(name)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Session '{name}' not found")
    return meta.to_dict()


@router.delete("/api/sessions/{name}")
async def delete_session(name: str) -> dict[str, Any]:
    removed = ctx.session_manager.delete_session(name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Session '{name}' not found")
    return {"status": "deleted", "name": name}
