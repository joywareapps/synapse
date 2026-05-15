from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from synapse.api.deps import ctx

router = APIRouter()


class CreateProfileRequest(BaseModel):
    name: str


class UpdateProfileRequest(BaseModel):
    preferred_volume_range: Optional[list[float]] = None
    preferred_patterns: Optional[list[str]] = None
    disliked_patterns: Optional[list[str]] = None
    preferred_carrier_hz: Optional[float] = None
    preferred_pulse_hz: Optional[float] = None
    preferred_base_period_s: Optional[float] = None
    notes: Optional[str] = None
    tags: Optional[dict[str, Any]] = None
    session_count: Optional[int] = None
    total_duration_s: Optional[float] = None
    last_session_at: Optional[str] = None


@router.get("/api/profiles")
async def list_profiles() -> list[dict[str, Any]]:
    return [p.to_dict() for p in ctx.profile_store.list()]


@router.post("/api/profiles", status_code=201)
async def create_profile(req: CreateProfileRequest) -> dict[str, Any]:
    if ctx.profile_store.get(req.name) is not None:
        raise HTTPException(status_code=409, detail=f"Profile '{req.name}' already exists")
    profile = ctx.profile_store.create(req.name)
    return profile.to_dict()


@router.get("/api/profiles/{name}")
async def get_profile(name: str) -> dict[str, Any]:
    profile = ctx.profile_store.get(name)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")
    return profile.to_dict()


@router.patch("/api/profiles/{name}")
async def update_profile(name: str, req: UpdateProfileRequest) -> dict[str, Any]:
    kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
    profile = ctx.profile_store.update(name, **kwargs)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")
    return profile.to_dict()


@router.delete("/api/profiles/{name}")
async def delete_profile(name: str) -> dict[str, Any]:
    removed = ctx.profile_store.delete(name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")
    return {"status": "deleted", "name": name}
