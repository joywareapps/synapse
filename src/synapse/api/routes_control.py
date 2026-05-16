from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from synapse.api.deps import ctx
from synapse.patterns.models import AxisOscillator, Layer, Pattern

router = APIRouter()


class SetValueRequest(BaseModel):
    value: float = Field(..., ge=0.0, le=1.0)


class SetVolumeRequest(BaseModel):
    value: float = Field(..., ge=0.0, le=1.0)


class SpikeRequest(BaseModel):
    intensity: float = Field(0.3, ge=0.0, le=1.0)
    on_ms: int = Field(200, ge=0)
    off_ms: int = Field(100, ge=0)
    repeat: int = Field(1, ge=1)


@router.post("/api/axes/{tcode_id}/value")
async def set_axis_value(tcode_id: str, req: SetValueRequest) -> dict[str, Any]:
    axis = ctx.axis_map.get_by_id(tcode_id)
    if not axis:
        raise HTTPException(status_code=404, detail=f"Axis {tcode_id} not found")
    # Set via a hold pattern on the player
    for engine in ctx.engines.values():
        engine._current_values[tcode_id] = req.value
    return {"tcode_id": tcode_id, "value": req.value}


@router.post("/api/volume")
async def set_volume(req: SetVolumeRequest) -> dict[str, Any]:
    vol_axis = ctx.axis_map.volume_axis()
    if vol_axis and vol_axis.tcode_id:
        for engine in ctx.engines.values():
            engine._current_values[vol_axis.tcode_id] = req.value
    return {"value": req.value}


@router.post("/api/spike")
async def spike(req: SpikeRequest) -> dict[str, Any]:
    total_duration = (req.on_ms + req.off_ms) * req.repeat / 1000.0
    attack = req.on_ms / 1000.0 * 0.2
    sustain = req.on_ms / 1000.0 * 0.6
    release = req.on_ms / 1000.0 * 0.2

    spike_pattern = Pattern(
        name="__spike__",
        description="Auto-generated spike",
        duration=total_duration,
        layers=[
            Layer(
                name="spike",
                blend="add",
                axes={
                    "V0": AxisOscillator(
                        waveform="hold",
                        amplitude=req.intensity,
                        attack=attack,
                        sustain=sustain,
                        release=release,
                    )
                },
            )
        ],
    )

    transition_cfg = ctx.config.patterns.transition
    for inst_id, player in ctx.players.items():
        await player.play(
            spike_pattern,
            duck_amount=0.0,  # no duck for spikes
            duck_ms=0,
            ramp_ms=0,
        )

    return {"status": "ok", "duration_s": total_duration}


@router.post("/api/emergency-stop")
async def emergency_stop() -> dict[str, Any]:
    for player in ctx.players.values():
        player._playing = False
        player._pattern = None
    for engine in ctx.engines.values():
        await engine.emergency_stop()
    return {"status": "ok"}


@router.post("/api/restim/start")
async def restim_start() -> dict[str, Any]:
    results = {}
    for inst_id, client in ctx.restim_clients.items():
        results[inst_id] = await client.start_playback()
    return {"results": results}


@router.post("/api/restim/stop")
async def restim_stop() -> dict[str, Any]:
    results = {}
    for inst_id, client in ctx.restim_clients.items():
        results[inst_id] = await client.stop_playback()
    return {"results": results}


