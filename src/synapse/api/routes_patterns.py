from __future__ import annotations

import copy
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from synapse.api.deps import ctx
from synapse.patterns.models import AxisOscillator, Layer, Pattern, SequenceStep, _auto_name_layers
from synapse.patterns.player import detect_circular

router = APIRouter()


# ── Request / Response models ─────────────────────────────────────────────────

class TransitionParams(BaseModel):
    duck_amount: Optional[float] = None
    duck_ms: Optional[int] = None
    ramp_ms: Optional[int] = None


class PlayPatternRequest(BaseModel):
    name: str
    instance: str = "primary"
    transition: Optional[TransitionParams] = None


class StopPatternRequest(BaseModel):
    instance: str = "primary"
    transition: Optional[TransitionParams] = None


class SnapshotRequest(BaseModel):
    name: str
    instance: str = "primary"
    description: str = ""


class CreatePatternRequest(BaseModel):
    name: str
    description: str = ""
    base_period: float = 1.0
    duration: float = 0.0


class CreateSequenceRequest(BaseModel):
    name: str
    description: str = ""
    loop: bool = False


class PatchPatternRequest(BaseModel):
    description: Optional[str] = None
    base_period: Optional[float] = None
    duration: Optional[float] = None


class AddLayerRequest(BaseModel):
    name: Optional[str] = None
    blend: str = "set"
    axes: Optional[dict] = None


class PatchLayerRequest(BaseModel):
    blend: Optional[str] = None
    name: Optional[str] = None


class MoveRequest(BaseModel):
    index: int


class OscillatorRequest(BaseModel):
    waveform: str = "sine"
    frequency: Optional[float] = None
    freq_multiple: Optional[float] = None
    amplitude: float = 0.5
    center: float = 0.5
    offset: float = 0.0
    attack: float = 0.0
    sustain: float = 0.0
    release: float = 0.0


class PatchOscillatorRequest(BaseModel):
    waveform: Optional[str] = None
    frequency: Optional[float] = None
    freq_multiple: Optional[float] = None
    amplitude: Optional[float] = None
    center: Optional[float] = None
    offset: Optional[float] = None
    attack: Optional[float] = None
    sustain: Optional[float] = None
    release: Optional[float] = None


class AddStepRequest(BaseModel):
    pattern: str
    duration: Optional[float] = None
    repeat: int = 1
    transition: Optional[dict] = None


class PatchStepRequest(BaseModel):
    pattern: Optional[str] = None
    duration: Optional[float] = None
    repeat: Optional[int] = None
    transition: Optional[dict] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_pattern_or_404(name: str) -> Pattern:
    p = ctx.store.get(name)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Pattern '{name}' not found")
    return p


def _get_layer_or_404(pattern: Pattern, layer_name: str) -> Layer:
    for layer in pattern.layers:
        if layer.name == layer_name:
            return layer
    raise HTTPException(status_code=404, detail=f"Layer '{layer_name}' not found")


def _osc_from_request(req: OscillatorRequest) -> AxisOscillator:
    return AxisOscillator(
        waveform=req.waveform,
        frequency=req.frequency,
        freq_multiple=req.freq_multiple,
        amplitude=req.amplitude,
        center=req.center,
        offset=req.offset,
        attack=req.attack,
        sustain=req.sustain,
        release=req.release,
    )


def _layer_to_dict(layer: Layer) -> dict:
    return {
        "name": layer.name,
        "blend": layer.blend,
        "axis_count": len(layer.axes),
        "axes": {
            tid: {
                "waveform": o.waveform,
                "frequency": o.frequency,
                "freq_multiple": o.freq_multiple,
                "amplitude": o.amplitude,
                "center": o.center,
                "offset": o.offset,
                "attack": o.attack,
                "sustain": o.sustain,
                "release": o.release,
            }
            for tid, o in layer.axes.items()
        },
    }


def _transition_defaults(req: Optional[TransitionParams]) -> dict:
    t = ctx.config.patterns.transition
    result = {
        "duck_amount": t.duck_amount,
        "duck_ms": t.duck_ms,
        "ramp_ms": t.ramp_ms,
    }
    if req:
        if req.duck_amount is not None:
            result["duck_amount"] = req.duck_amount
        if req.duck_ms is not None:
            result["duck_ms"] = req.duck_ms
        if req.ramp_ms is not None:
            result["ramp_ms"] = req.ramp_ms
    return result


# ── Pattern CRUD ──────────────────────────────────────────────────────────────

@router.get("/api/patterns")
async def list_patterns() -> list[dict[str, Any]]:
    names = ctx.store.list()
    result = []
    for name in names:
        p = ctx.store.get(name)
        if p:
            result.append({
                "name": p.name,
                "description": p.description,
                "is_sequence": p.is_sequence(),
                "layer_count": len(p.layers),
                "step_count": len(p.steps),
            })
    return result


@router.post("/api/patterns/play")
async def play_pattern(req: PlayPatternRequest) -> dict[str, Any]:
    pattern = _get_pattern_or_404(req.name)
    player = ctx.players.get(req.instance)
    if player is None:
        raise HTTPException(status_code=404, detail=f"Instance '{req.instance}' not found")

    if pattern.is_sequence():
        if detect_circular(req.name, ctx.store.get):
            raise HTTPException(status_code=400, detail="Circular sequence reference detected")

    t = _transition_defaults(req.transition)
    await player.play(pattern, duck_amount=t["duck_amount"], duck_ms=t["duck_ms"], ramp_ms=t["ramp_ms"])
    return {"status": "playing", "pattern": req.name, "instance": req.instance}


@router.post("/api/patterns/stop")
async def stop_pattern(req: StopPatternRequest) -> dict[str, Any]:
    player = ctx.players.get(req.instance)
    if player is None:
        raise HTTPException(status_code=404, detail=f"Instance '{req.instance}' not found")
    t = _transition_defaults(req.transition)
    await player.stop(duck_ms=t["duck_ms"])
    return {"status": "stopped", "instance": req.instance}


@router.post("/api/patterns/snapshot")
async def snapshot_pattern(req: SnapshotRequest) -> dict[str, Any]:
    player = ctx.players.get(req.instance)
    if player is None:
        raise HTTPException(status_code=404, detail=f"Instance '{req.instance}' not found")

    engine = ctx.engines.get(req.instance)
    values = engine.get_current_values() if engine else {}

    layers = [
        Layer(
            name="snapshot",
            blend="set",
            axes={
                tid: AxisOscillator(waveform="hold", amplitude=0.0, center=val)
                for tid, val in values.items()
            },
        )
    ]
    pattern = Pattern(
        name=req.name,
        description=req.description or f"Snapshot from instance {req.instance}",
        layers=layers,
    )
    ctx.store.save(pattern)
    return {"status": "ok", "name": req.name}


@router.get("/api/patterns/{name}")
async def get_pattern(name: str) -> dict[str, Any]:
    p = _get_pattern_or_404(name)
    return {
        "name": p.name,
        "description": p.description,
        "is_sequence": p.is_sequence(),
        "base_period": p.base_period,
        "duration": p.duration,
        "loop": p.loop,
        "static_axes": p.static_axes,
        "layers": [_layer_to_dict(l) for l in p.layers],
        "steps": [
            {
                "pattern": s.pattern,
                "duration": s.duration,
                "repeat": s.repeat,
                "transition": s.transition,
            }
            for s in p.steps
        ],
    }


@router.post("/api/patterns")
async def create_pattern(req: CreatePatternRequest) -> dict[str, Any]:
    if ctx.store.exists(req.name):
        raise HTTPException(status_code=409, detail=f"Pattern '{req.name}' already exists")
    pattern = Pattern(
        name=req.name,
        description=req.description,
        base_period=req.base_period,
        duration=req.duration,
    )
    ctx.store.save(pattern)
    return {"name": pattern.name}


@router.post("/api/patterns/sequence")
async def create_sequence(req: CreateSequenceRequest) -> dict[str, Any]:
    if ctx.store.exists(req.name):
        raise HTTPException(status_code=409, detail=f"Pattern '{req.name}' already exists")
    # Create with a placeholder step that we remove, or just empty steps
    # A sequence needs at least one step to be valid on save
    # We allow empty for now and validate on play
    pattern = Pattern(
        name=req.name,
        description=req.description,
        loop=req.loop,
    )
    # Save as empty (no layers, no steps) — will be populated via steps API
    ctx.store._patterns[req.name] = pattern
    return {"name": pattern.name}


@router.patch("/api/patterns/{name}")
async def patch_pattern(name: str, req: PatchPatternRequest) -> dict[str, Any]:
    p = _get_pattern_or_404(name)
    p = copy.deepcopy(p)
    if req.description is not None:
        p.description = req.description
    if req.base_period is not None:
        p.base_period = req.base_period
    if req.duration is not None:
        p.duration = req.duration
    ctx.store.save(p)
    return {"name": p.name}


@router.delete("/api/patterns/{name}")
async def delete_pattern(name: str) -> dict[str, Any]:
    if not ctx.store.delete(name):
        raise HTTPException(status_code=404, detail=f"Pattern '{name}' not found")
    return {"status": "deleted", "name": name}


# ── Layer CRUD ────────────────────────────────────────────────────────────────

@router.get("/api/patterns/{name}/layers")
async def list_layers(name: str) -> list[dict[str, Any]]:
    p = _get_pattern_or_404(name)
    return [{"name": l.name, "blend": l.blend, "axis_count": len(l.axes)} for l in p.layers]


@router.post("/api/patterns/{name}/layers")
async def add_layer(name: str, req: AddLayerRequest) -> dict[str, Any]:
    p = _get_pattern_or_404(name)
    p = copy.deepcopy(p)

    used_names = {l.name for l in p.layers}
    layer_name = req.name
    if not layer_name:
        i = 1
        while f"layer-{i}" in used_names:
            i += 1
        layer_name = f"layer-{i}"
    elif layer_name in used_names:
        raise HTTPException(status_code=409, detail=f"Layer '{layer_name}' already exists")

    axes = {}
    if req.axes:
        from synapse.patterns.store import _osc_from_dict
        for tid, osc_data in req.axes.items():
            axes[tid] = _osc_from_dict(osc_data)

    p.layers.append(Layer(name=layer_name, blend=req.blend, axes=axes))
    ctx.store.save(p)
    return {"layer_name": layer_name}


@router.get("/api/patterns/{name}/layers/{layer_name}")
async def get_layer(name: str, layer_name: str) -> dict[str, Any]:
    p = _get_pattern_or_404(name)
    layer = _get_layer_or_404(p, layer_name)
    return _layer_to_dict(layer)


@router.patch("/api/patterns/{name}/layers/{layer_name}")
async def patch_layer(name: str, layer_name: str, req: PatchLayerRequest) -> dict[str, Any]:
    p = _get_pattern_or_404(name)
    p = copy.deepcopy(p)
    layer = _get_layer_or_404(p, layer_name)

    if req.blend is not None:
        layer.blend = req.blend
    if req.name is not None:
        # Check uniqueness
        used = {l.name for l in p.layers if l.name != layer_name}
        if req.name in used:
            raise HTTPException(status_code=409, detail=f"Layer name '{req.name}' already in use")
        layer.name = req.name

    ctx.store.save(p)
    return {"layer_name": layer.name}


@router.delete("/api/patterns/{name}/layers/{layer_name}")
async def delete_layer(name: str, layer_name: str) -> dict[str, Any]:
    p = _get_pattern_or_404(name)
    p = copy.deepcopy(p)
    before = len(p.layers)
    p.layers = [l for l in p.layers if l.name != layer_name]
    if len(p.layers) == before:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_name}' not found")
    ctx.store.save(p)
    return {"status": "deleted"}


@router.post("/api/patterns/{name}/layers/{layer_name}/move")
async def move_layer(name: str, layer_name: str, req: MoveRequest) -> dict[str, Any]:
    p = _get_pattern_or_404(name)
    p = copy.deepcopy(p)
    idx = next((i for i, l in enumerate(p.layers) if l.name == layer_name), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_name}' not found")
    layer = p.layers.pop(idx)
    new_idx = max(0, min(req.index, len(p.layers)))
    p.layers.insert(new_idx, layer)
    ctx.store.save(p)
    return {"index": new_idx}


# ── Layer Axes ────────────────────────────────────────────────────────────────

@router.get("/api/patterns/{name}/layers/{layer_name}/axes")
async def list_layer_axes(name: str, layer_name: str) -> dict[str, Any]:
    p = _get_pattern_or_404(name)
    layer = _get_layer_or_404(p, layer_name)
    return {
        tid: {
            "waveform": o.waveform,
            "frequency": o.frequency,
            "freq_multiple": o.freq_multiple,
            "amplitude": o.amplitude,
            "center": o.center,
            "offset": o.offset,
            "attack": o.attack,
            "sustain": o.sustain,
            "release": o.release,
        }
        for tid, o in layer.axes.items()
    }


@router.put("/api/patterns/{name}/layers/{layer_name}/axes/{tcode_id}")
async def set_layer_axis(name: str, layer_name: str, tcode_id: str, req: OscillatorRequest) -> dict[str, Any]:
    p = _get_pattern_or_404(name)
    p = copy.deepcopy(p)
    layer = _get_layer_or_404(p, layer_name)
    layer.axes[tcode_id] = _osc_from_request(req)
    ctx.store.save(p)
    return {"tcode_id": tcode_id}


@router.get("/api/patterns/{name}/layers/{layer_name}/axes/{tcode_id}")
async def get_layer_axis(name: str, layer_name: str, tcode_id: str) -> dict[str, Any]:
    p = _get_pattern_or_404(name)
    layer = _get_layer_or_404(p, layer_name)
    if tcode_id not in layer.axes:
        raise HTTPException(status_code=404, detail=f"Axis '{tcode_id}' not in layer")
    o = layer.axes[tcode_id]
    return {
        "waveform": o.waveform,
        "frequency": o.frequency,
        "freq_multiple": o.freq_multiple,
        "amplitude": o.amplitude,
        "center": o.center,
        "offset": o.offset,
        "attack": o.attack,
        "sustain": o.sustain,
        "release": o.release,
    }


@router.patch("/api/patterns/{name}/layers/{layer_name}/axes/{tcode_id}")
async def patch_layer_axis(name: str, layer_name: str, tcode_id: str, req: PatchOscillatorRequest) -> dict[str, Any]:
    p = _get_pattern_or_404(name)
    p = copy.deepcopy(p)
    layer = _get_layer_or_404(p, layer_name)
    if tcode_id not in layer.axes:
        raise HTTPException(status_code=404, detail=f"Axis '{tcode_id}' not in layer")
    o = layer.axes[tcode_id]
    if req.waveform is not None:
        o.waveform = req.waveform
    if req.frequency is not None:
        o.frequency = req.frequency
        o.freq_multiple = None
    if req.freq_multiple is not None:
        o.freq_multiple = req.freq_multiple
        o.frequency = None
    if req.amplitude is not None:
        o.amplitude = req.amplitude
    if req.center is not None:
        o.center = req.center
    if req.offset is not None:
        o.offset = req.offset
    if req.attack is not None:
        o.attack = req.attack
    if req.sustain is not None:
        o.sustain = req.sustain
    if req.release is not None:
        o.release = req.release
    ctx.store.save(p)
    return {"tcode_id": tcode_id}


@router.delete("/api/patterns/{name}/layers/{layer_name}/axes/{tcode_id}")
async def delete_layer_axis(name: str, layer_name: str, tcode_id: str) -> dict[str, Any]:
    p = _get_pattern_or_404(name)
    p = copy.deepcopy(p)
    layer = _get_layer_or_404(p, layer_name)
    if tcode_id not in layer.axes:
        raise HTTPException(status_code=404, detail=f"Axis '{tcode_id}' not in layer")
    del layer.axes[tcode_id]
    ctx.store.save(p)
    return {"status": "deleted"}


# ── Sequence Steps ────────────────────────────────────────────────────────────

@router.get("/api/patterns/{name}/steps")
async def list_steps(name: str) -> list[dict[str, Any]]:
    p = _get_pattern_or_404(name)
    return [
        {
            "index": i,
            "pattern": s.pattern,
            "duration": s.duration,
            "repeat": s.repeat,
            "transition": s.transition,
        }
        for i, s in enumerate(p.steps)
    ]


@router.post("/api/patterns/{name}/steps")
async def add_step(name: str, req: AddStepRequest) -> dict[str, Any]:
    p = _get_pattern_or_404(name)
    p = copy.deepcopy(p)
    if p.layers:
        raise HTTPException(status_code=400, detail="Cannot add steps to a leaf pattern")
    p.steps.append(SequenceStep(
        pattern=req.pattern,
        duration=req.duration,
        repeat=req.repeat,
        transition=req.transition,
    ))
    ctx.store.save(p)
    return {"index": len(p.steps) - 1}


@router.get("/api/patterns/{name}/steps/{index}")
async def get_step(name: str, index: int) -> dict[str, Any]:
    p = _get_pattern_or_404(name)
    if index < 0 or index >= len(p.steps):
        raise HTTPException(status_code=404, detail=f"Step {index} not found")
    s = p.steps[index]
    return {"index": index, "pattern": s.pattern, "duration": s.duration, "repeat": s.repeat, "transition": s.transition}


@router.patch("/api/patterns/{name}/steps/{index}")
async def patch_step(name: str, index: int, req: PatchStepRequest) -> dict[str, Any]:
    p = _get_pattern_or_404(name)
    p = copy.deepcopy(p)
    if index < 0 or index >= len(p.steps):
        raise HTTPException(status_code=404, detail=f"Step {index} not found")
    s = p.steps[index]
    if req.pattern is not None:
        s.pattern = req.pattern
    if req.duration is not None:
        s.duration = req.duration
    if req.repeat is not None:
        s.repeat = req.repeat
    if req.transition is not None:
        s.transition = req.transition
    ctx.store.save(p)
    return {"index": index}


@router.delete("/api/patterns/{name}/steps/{index}")
async def delete_step(name: str, index: int) -> dict[str, Any]:
    p = _get_pattern_or_404(name)
    p = copy.deepcopy(p)
    if index < 0 or index >= len(p.steps):
        raise HTTPException(status_code=404, detail=f"Step {index} not found")
    p.steps.pop(index)
    ctx.store.save(p)
    return {"status": "deleted"}


@router.post("/api/patterns/{name}/steps/{index}/move")
async def move_step(name: str, index: int, req: MoveRequest) -> dict[str, Any]:
    p = _get_pattern_or_404(name)
    p = copy.deepcopy(p)
    if index < 0 or index >= len(p.steps):
        raise HTTPException(status_code=404, detail=f"Step {index} not found")
    step = p.steps.pop(index)
    new_idx = max(0, min(req.index, len(p.steps)))
    p.steps.insert(new_idx, step)
    ctx.store.save(p)
    return {"index": new_idx}
