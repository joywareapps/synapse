from __future__ import annotations

import copy
import time
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from synapse.api.deps import ctx
from synapse.patterns.models import AxisOscillator, Layer, Pattern, SequenceStep, _auto_name_layers
from synapse.patterns.player import detect_circular
from synapse.patterns.store import pattern_to_dict

mcp = FastMCP("Synapse")


# ── Device State ──────────────────────────────────────────────────────────────

@mcp.tool()
async def get_status() -> dict[str, Any]:
    """Get Synapse and Restim status."""
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
    return {"status": "ok", "uptime_s": round(uptime, 2), "instances": instances}


@mcp.tool()
async def get_axes() -> list[dict[str, Any]]:
    """List all axes with current values and limits."""
    values: dict[str, float] = {}
    for engine in ctx.engines.values():
        values.update(engine.get_current_values())
        break
    return [
        {
            "tcode_id": a.tcode_id,
            "name": a.name,
            "value_type": a.value_type,
            "limit_min": a.limit_min,
            "limit_max": a.limit_max,
            "enabled": a.enabled,
            "current_value": values.get(a.tcode_id),
        }
        for a in ctx.axis_map.all()
    ]


@mcp.tool()
async def get_axis(tcode_id: str) -> dict[str, Any]:
    """Get single axis value and definition."""
    axis = ctx.axis_map.get_by_id(tcode_id)
    if not axis:
        return {"error": f"Axis {tcode_id} not found"}
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


@mcp.tool()
async def get_restim_state() -> dict[str, Any]:
    """Get Restim play state and volume."""
    states = []
    for inst_id, client in ctx.restim_clients.items():
        s = client.get_state()
        states.append({
            "instance": inst_id,
            "playing": s.playing,
            "volume_ui": s.volume_ui,
            "volume_device": s.volume_device,
            "error": s.error,
        })
    return {"instances": states}


# ── Sensor Readings ───────────────────────────────────────────────────────────

@mcp.tool()
async def get_sensors() -> list[dict[str, Any]]:
    """List all configured sensors with current values and status."""
    return [
        {
            "name": r.name,
            "value": r.value,
            "raw": r.raw,
            "error": r.error,
            "timestamp": r.timestamp,
        }
        for r in ctx.sensor_manager.get_all_with_restim()
    ]


@mcp.tool()
async def get_sensor(name: str) -> dict[str, Any]:
    """Get a specific sensor's value and raw fields."""
    r = ctx.sensor_manager.get_by_name(name)
    if r is None:
        return {"error": f"Sensor '{name}' not found"}
    return {"name": r.name, "value": r.value, "raw": r.raw, "error": r.error, "timestamp": r.timestamp}


# ── Direct Control ────────────────────────────────────────────────────────────

@mcp.tool()
async def set_axis(tcode_id: str, value: float) -> dict[str, Any]:
    """Set axis to a specific normalized value (0.0–1.0)."""
    axis = ctx.axis_map.get_by_id(tcode_id)
    if not axis:
        return {"error": f"Axis {tcode_id} not found"}
    clamped = max(0.0, min(1.0, value))
    for engine in ctx.engines.values():
        engine._current_values[tcode_id] = clamped
    return {"tcode_id": tcode_id, "value": clamped}


@mcp.tool()
async def set_volume(value: float) -> dict[str, Any]:
    """Set main volume (0.0–1.0)."""
    clamped = max(0.0, min(1.0, value))
    vol_axis = ctx.axis_map.volume_axis()
    if vol_axis and vol_axis.tcode_id:
        for engine in ctx.engines.values():
            engine._current_values[vol_axis.tcode_id] = clamped
    return {"value": clamped}


@mcp.tool()
async def spike(
    intensity: float,
    on_ms: int = 200,
    off_ms: int = 100,
    repeat: int = 1,
) -> dict[str, Any]:
    """Create a brief intensity spike (delta added to current volume)."""
    from synapse.patterns.models import AxisOscillator, Layer, Pattern
    attack = on_ms / 1000.0 * 0.2
    sustain = on_ms / 1000.0 * 0.6
    release_t = on_ms / 1000.0 * 0.2
    total = (on_ms + off_ms) * repeat / 1000.0

    spike_pattern = Pattern(
        name="__spike__",
        duration=total,
        layers=[
            Layer(
                name="spike",
                blend="add",
                axes={
                    "V0": AxisOscillator(
                        waveform="hold",
                        amplitude=intensity,
                        attack=attack,
                        sustain=sustain,
                        release=release_t,
                    )
                },
            )
        ],
    )
    for player in ctx.players.values():
        await player.play(spike_pattern, duck_amount=0.0, duck_ms=0, ramp_ms=0)
    return {"status": "ok", "duration_s": total}


@mcp.tool()
async def start_playback() -> dict[str, Any]:
    """Start Restim playback."""
    results = {}
    for inst_id, client in ctx.restim_clients.items():
        results[inst_id] = await client.start_playback()
    return {"results": results}


@mcp.tool()
async def stop_playback() -> dict[str, Any]:
    """Stop Restim playback."""
    results = {}
    for inst_id, client in ctx.restim_clients.items():
        results[inst_id] = await client.stop_playback()
    return {"results": results}


@mcp.tool()
async def emergency_stop() -> dict[str, Any]:
    """Immediately zero all axes on all instances and stop all patterns."""
    for player in ctx.players.values():
        player._playing = False
        player._pattern = None
    for engine in ctx.engines.values():
        await engine.emergency_stop()
    return {"status": "ok"}


# ── Pattern Control ───────────────────────────────────────────────────────────

@mcp.tool()
async def list_patterns() -> list[dict[str, Any]]:
    """List all saved patterns."""
    result = []
    for name in ctx.store.list():
        p = ctx.store.get(name)
        if p:
            result.append({
                "name": p.name,
                "description": p.description,
                "is_sequence": p.is_sequence(),
            })
    return result


@mcp.tool()
async def play_pattern(
    name: str,
    instance: str = "primary",
    duck_amount: Optional[float] = None,
    duck_ms: Optional[int] = None,
    ramp_ms: Optional[int] = None,
) -> dict[str, Any]:
    """Start a named pattern on the specified instance."""
    pattern = ctx.store.get(name)
    if pattern is None:
        return {"error": f"Pattern '{name}' not found"}
    player = ctx.players.get(instance)
    if player is None:
        return {"error": f"Instance '{instance}' not found"}

    if pattern.is_sequence() and detect_circular(name, ctx.store.get):
        return {"error": "Circular sequence reference detected"}

    t = ctx.config.patterns.transition
    await player.play(
        pattern,
        duck_amount=duck_amount if duck_amount is not None else t.duck_amount,
        duck_ms=duck_ms if duck_ms is not None else t.duck_ms,
        ramp_ms=ramp_ms if ramp_ms is not None else t.ramp_ms,
    )
    return {"status": "playing", "pattern": name, "instance": instance}


@mcp.tool()
async def stop_pattern(instance: str = "primary", duck_ms: Optional[int] = None) -> dict[str, Any]:
    """Stop current pattern on the specified instance."""
    player = ctx.players.get(instance)
    if player is None:
        return {"error": f"Instance '{instance}' not found"}
    t = ctx.config.patterns.transition
    await player.stop(duck_ms=duck_ms if duck_ms is not None else t.duck_ms)
    return {"status": "stopped", "instance": instance}


@mcp.tool()
async def create_pattern(
    name: str,
    description: str = "",
    base_period: float = 1.0,
    duration: float = 0.0,
) -> dict[str, Any]:
    """Create a new empty leaf pattern."""
    if ctx.store.exists(name):
        return {"error": f"Pattern '{name}' already exists"}
    p = Pattern(name=name, description=description, base_period=base_period, duration=duration)
    ctx.store.save(p)
    return {"name": name}


@mcp.tool()
async def create_sequence(
    name: str,
    description: str = "",
    loop: bool = False,
) -> dict[str, Any]:
    """Create a new empty sequence pattern."""
    if ctx.store.exists(name):
        return {"error": f"Pattern '{name}' already exists"}
    p = Pattern(name=name, description=description, loop=loop)
    ctx.store._patterns[name] = p
    return {"name": name}


@mcp.tool()
async def describe_pattern(name: str) -> dict[str, Any]:
    """Get full pattern including layers, axes, and metadata."""
    p = ctx.store.get(name)
    if p is None:
        return {"error": f"Pattern '{name}' not found"}
    return pattern_to_dict(p)


@mcp.tool()
async def snapshot_pattern(
    name: str,
    instance: str = "primary",
    description: str = "",
) -> dict[str, Any]:
    """Save current axis state as a named pattern."""
    engine = ctx.engines.get(instance)
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
    p = Pattern(
        name=name,
        description=description or f"Snapshot from {instance}",
        layers=layers,
    )
    ctx.store.save(p)
    return {"name": name}


@mcp.tool()
async def delete_pattern(name: str) -> dict[str, Any]:
    """Delete a saved pattern."""
    if not ctx.store.delete(name):
        return {"error": f"Pattern '{name}' not found"}
    return {"status": "deleted", "name": name}


# ── Pattern Layer CRUD ────────────────────────────────────────────────────────

@mcp.tool()
async def list_layers(pattern_name: str) -> list[dict[str, Any]]:
    """List layers in a pattern."""
    p = ctx.store.get(pattern_name)
    if p is None:
        return [{"error": f"Pattern '{pattern_name}' not found"}]
    return [{"name": l.name, "blend": l.blend, "axis_count": len(l.axes)} for l in p.layers]


@mcp.tool()
async def add_layer(
    pattern_name: str,
    blend: str = "set",
    layer_name: Optional[str] = None,
    instance: Optional[str] = None,
) -> dict[str, Any]:
    """Add a new layer to a pattern. Returns the assigned layer name."""
    p = ctx.store.get(pattern_name)
    if p is None:
        return {"error": f"Pattern '{pattern_name}' not found"}
    p = copy.deepcopy(p)
    used = {l.name for l in p.layers}
    if not layer_name:
        i = 1
        while f"layer-{i}" in used:
            i += 1
        layer_name = f"layer-{i}"
    elif layer_name in used:
        return {"error": f"Layer '{layer_name}' already exists"}
    p.layers.append(Layer(name=layer_name, blend=blend))
    ctx.store.save(p)
    return {"layer_name": layer_name}


@mcp.tool()
async def describe_layer(pattern_name: str, layer_name: str) -> dict[str, Any]:
    """Get layer details including blend mode and all axes."""
    p = ctx.store.get(pattern_name)
    if p is None:
        return {"error": f"Pattern '{pattern_name}' not found"}
    layer = next((l for l in p.layers if l.name == layer_name), None)
    if layer is None:
        return {"error": f"Layer '{layer_name}' not found"}
    return {
        "name": layer.name,
        "blend": layer.blend,
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


@mcp.tool()
async def modify_layer(
    pattern_name: str,
    layer_name: str,
    blend: Optional[str] = None,
    new_name: Optional[str] = None,
) -> dict[str, Any]:
    """Change a layer's blend mode or name."""
    p = ctx.store.get(pattern_name)
    if p is None:
        return {"error": f"Pattern '{pattern_name}' not found"}
    p = copy.deepcopy(p)
    layer = next((l for l in p.layers if l.name == layer_name), None)
    if layer is None:
        return {"error": f"Layer '{layer_name}' not found"}
    if blend is not None:
        layer.blend = blend
    if new_name is not None:
        used = {l.name for l in p.layers if l.name != layer_name}
        if new_name in used:
            return {"error": f"Layer name '{new_name}' already in use"}
        layer.name = new_name
    ctx.store.save(p)
    return {"layer_name": layer.name}


@mcp.tool()
async def remove_layer(pattern_name: str, layer_name: str) -> dict[str, Any]:
    """Remove a layer from a pattern."""
    p = ctx.store.get(pattern_name)
    if p is None:
        return {"error": f"Pattern '{pattern_name}' not found"}
    p = copy.deepcopy(p)
    before = len(p.layers)
    p.layers = [l for l in p.layers if l.name != layer_name]
    if len(p.layers) == before:
        return {"error": f"Layer '{layer_name}' not found"}
    ctx.store.save(p)
    return {"status": "removed"}


@mcp.tool()
async def move_layer(pattern_name: str, layer_name: str, index: int) -> dict[str, Any]:
    """Reorder a layer within a pattern."""
    p = ctx.store.get(pattern_name)
    if p is None:
        return {"error": f"Pattern '{pattern_name}' not found"}
    p = copy.deepcopy(p)
    idx = next((i for i, l in enumerate(p.layers) if l.name == layer_name), None)
    if idx is None:
        return {"error": f"Layer '{layer_name}' not found"}
    layer = p.layers.pop(idx)
    new_idx = max(0, min(index, len(p.layers)))
    p.layers.insert(new_idx, layer)
    ctx.store.save(p)
    return {"index": new_idx}


# ── Layer Axis CRUD ───────────────────────────────────────────────────────────

@mcp.tool()
async def set_layer_axis(
    pattern_name: str,
    layer_name: str,
    tcode_id: str,
    waveform: str = "sine",
    amplitude: float = 0.5,
    center: float = 0.5,
    offset: float = 0.0,
    frequency: Optional[float] = None,
    freq_multiple: Optional[float] = None,
    attack: float = 0.0,
    sustain: float = 0.0,
    release: float = 0.0,
) -> dict[str, Any]:
    """Add or fully replace an axis oscillator in a layer."""
    if frequency is not None and freq_multiple is not None:
        return {"error": "frequency and freq_multiple are mutually exclusive"}
    p = ctx.store.get(pattern_name)
    if p is None:
        return {"error": f"Pattern '{pattern_name}' not found"}
    p = copy.deepcopy(p)
    layer = next((l for l in p.layers if l.name == layer_name), None)
    if layer is None:
        return {"error": f"Layer '{layer_name}' not found"}
    layer.axes[tcode_id] = AxisOscillator(
        waveform=waveform,
        frequency=frequency,
        freq_multiple=freq_multiple,
        amplitude=amplitude,
        center=center,
        offset=offset,
        attack=attack,
        sustain=sustain,
        release=release,
    )
    ctx.store.save(p)
    return {"tcode_id": tcode_id}


@mcp.tool()
async def modify_layer_axis(
    pattern_name: str,
    layer_name: str,
    tcode_id: str,
    waveform: Optional[str] = None,
    amplitude: Optional[float] = None,
    center: Optional[float] = None,
    offset: Optional[float] = None,
    frequency: Optional[float] = None,
    freq_multiple: Optional[float] = None,
    attack: Optional[float] = None,
    sustain: Optional[float] = None,
    release: Optional[float] = None,
) -> dict[str, Any]:
    """Partial update of an axis oscillator."""
    p = ctx.store.get(pattern_name)
    if p is None:
        return {"error": f"Pattern '{pattern_name}' not found"}
    p = copy.deepcopy(p)
    layer = next((l for l in p.layers if l.name == layer_name), None)
    if layer is None:
        return {"error": f"Layer '{layer_name}' not found"}
    if tcode_id not in layer.axes:
        return {"error": f"Axis '{tcode_id}' not in layer"}
    o = layer.axes[tcode_id]
    if waveform is not None:
        o.waveform = waveform
    if frequency is not None:
        o.frequency = frequency
        o.freq_multiple = None
    if freq_multiple is not None:
        o.freq_multiple = freq_multiple
        o.frequency = None
    if amplitude is not None:
        o.amplitude = amplitude
    if center is not None:
        o.center = center
    if offset is not None:
        o.offset = offset
    if attack is not None:
        o.attack = attack
    if sustain is not None:
        o.sustain = sustain
    if release is not None:
        o.release = release
    ctx.store.save(p)
    return {"tcode_id": tcode_id}


@mcp.tool()
async def remove_layer_axis(pattern_name: str, layer_name: str, tcode_id: str) -> dict[str, Any]:
    """Remove an axis from a layer."""
    p = ctx.store.get(pattern_name)
    if p is None:
        return {"error": f"Pattern '{pattern_name}' not found"}
    p = copy.deepcopy(p)
    layer = next((l for l in p.layers if l.name == layer_name), None)
    if layer is None:
        return {"error": f"Layer '{layer_name}' not found"}
    if tcode_id not in layer.axes:
        return {"error": f"Axis '{tcode_id}' not in layer"}
    del layer.axes[tcode_id]
    ctx.store.save(p)
    return {"status": "removed"}


# ── Sequence Step CRUD ────────────────────────────────────────────────────────

@mcp.tool()
async def list_steps(pattern_name: str) -> list[dict[str, Any]]:
    """List steps in a sequence pattern."""
    p = ctx.store.get(pattern_name)
    if p is None:
        return [{"error": f"Pattern '{pattern_name}' not found"}]
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


@mcp.tool()
async def add_step(
    pattern_name: str,
    step_pattern: str,
    duration: Optional[float] = None,
    repeat: int = 1,
    transition: Optional[dict] = None,
) -> dict[str, Any]:
    """Append a step to a sequence pattern. Returns step index."""
    p = ctx.store.get(pattern_name)
    if p is None:
        return {"error": f"Pattern '{pattern_name}' not found"}
    if p.layers:
        return {"error": "Cannot add steps to a leaf pattern"}
    p = copy.deepcopy(p)
    p.steps.append(SequenceStep(pattern=step_pattern, duration=duration, repeat=repeat, transition=transition))
    ctx.store.save(p)
    return {"index": len(p.steps) - 1}


@mcp.tool()
async def modify_step(
    pattern_name: str,
    step_index: int,
    step_pattern: Optional[str] = None,
    duration: Optional[float] = None,
    repeat: Optional[int] = None,
    transition: Optional[dict] = None,
) -> dict[str, Any]:
    """Update a sequence step."""
    p = ctx.store.get(pattern_name)
    if p is None:
        return {"error": f"Pattern '{pattern_name}' not found"}
    if step_index < 0 or step_index >= len(p.steps):
        return {"error": f"Step {step_index} not found"}
    p = copy.deepcopy(p)
    s = p.steps[step_index]
    if step_pattern is not None:
        s.pattern = step_pattern
    if duration is not None:
        s.duration = duration
    if repeat is not None:
        s.repeat = repeat
    if transition is not None:
        s.transition = transition
    ctx.store.save(p)
    return {"index": step_index}


@mcp.tool()
async def remove_step(pattern_name: str, step_index: int) -> dict[str, Any]:
    """Remove a step by index from a sequence pattern."""
    p = ctx.store.get(pattern_name)
    if p is None:
        return {"error": f"Pattern '{pattern_name}' not found"}
    if step_index < 0 or step_index >= len(p.steps):
        return {"error": f"Step {step_index} not found"}
    p = copy.deepcopy(p)
    p.steps.pop(step_index)
    ctx.store.save(p)
    return {"status": "removed"}


@mcp.tool()
async def move_step(pattern_name: str, step_index: int, new_index: int) -> dict[str, Any]:
    """Reorder a step in a sequence pattern."""
    p = ctx.store.get(pattern_name)
    if p is None:
        return {"error": f"Pattern '{pattern_name}' not found"}
    if step_index < 0 or step_index >= len(p.steps):
        return {"error": f"Step {step_index} not found"}
    p = copy.deepcopy(p)
    step = p.steps.pop(step_index)
    new_idx = max(0, min(new_index, len(p.steps)))
    p.steps.insert(new_idx, step)
    ctx.store.save(p)
    return {"index": new_idx}


# ── MCP Resources ─────────────────────────────────────────────────────────────

@mcp.resource("synapse://status")
async def resource_status() -> str:
    import json
    result = await get_status()
    return json.dumps(result, indent=2)


@mcp.resource("synapse://axes")
async def resource_axes() -> str:
    import json
    result = await get_axes()
    return json.dumps(result, indent=2)


@mcp.resource("synapse://patterns")
async def resource_patterns() -> str:
    import json
    result = await list_patterns()
    return json.dumps(result, indent=2)


@mcp.resource("synapse://pattern/{name}")
async def resource_pattern(name: str) -> str:
    import json
    p = ctx.store.get(name)
    if p is None:
        return json.dumps({"error": f"Pattern '{name}' not found"})
    return json.dumps(pattern_to_dict(p), indent=2)
