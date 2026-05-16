from __future__ import annotations

"""Shared tool registry — all tool functions as plain async def.

Used by both the MCP server (which wraps them with @mcp.tool()) and the
embedded agent (which calls them directly).
"""

import copy
import time
from typing import Any, Optional

from synapse.api.deps import ctx


# ── Device State ──────────────────────────────────────────────────────────────

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


async def get_sensor(name: str) -> dict[str, Any]:
    """Get a specific sensor's value and raw fields."""
    r = ctx.sensor_manager.get_by_name(name)
    if r is None:
        return {"error": f"Sensor '{name}' not found"}
    return {"name": r.name, "value": r.value, "raw": r.raw, "error": r.error, "timestamp": r.timestamp}


# ── Direct Control ────────────────────────────────────────────────────────────

async def set_axis(tcode_id: str, value: float) -> dict[str, Any]:
    """Set axis to a specific normalized value (0.0-1.0)."""
    axis = ctx.axis_map.get_by_id(tcode_id)
    if not axis:
        return {"error": f"Axis {tcode_id} not found"}
    clamped = max(0.0, min(1.0, value))
    for engine in ctx.engines.values():
        engine._current_values[tcode_id] = clamped
    return {"tcode_id": tcode_id, "value": clamped}


async def set_volume(value: float) -> dict[str, Any]:
    """Set main volume (0.0-1.0)."""
    clamped = max(0.0, min(1.0, value))
    vol_axis = ctx.axis_map.volume_axis()
    if vol_axis and vol_axis.tcode_id:
        for engine in ctx.engines.values():
            engine._current_values[vol_axis.tcode_id] = clamped
    return {"value": clamped}


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


async def start_playback() -> dict[str, Any]:
    """Start Restim playback."""
    results = {}
    for inst_id, client in ctx.restim_clients.items():
        results[inst_id] = await client.start_playback()
    return {"results": results}


async def stop_playback() -> dict[str, Any]:
    """Stop Restim playback."""
    results = {}
    for inst_id, client in ctx.restim_clients.items():
        results[inst_id] = await client.stop_playback()
    return {"results": results}


async def emergency_stop() -> dict[str, Any]:
    """Immediately zero all axes on all instances and stop all patterns."""
    for player in ctx.players.values():
        player._playing = False
        player._pattern = None
    for engine in ctx.engines.values():
        await engine.emergency_stop()
    return {"status": "ok"}


# ── Pattern Control ───────────────────────────────────────────────────────────

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


async def play_pattern(
    name: str,
    instance: str = "primary",
    duck_amount: Optional[float] = None,
    duck_ms: Optional[int] = None,
    ramp_ms: Optional[int] = None,
) -> dict[str, Any]:
    """Start a named pattern on the specified instance."""
    from synapse.patterns.player import detect_circular
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


async def stop_pattern(instance: str = "primary", duck_ms: Optional[int] = None) -> dict[str, Any]:
    """Stop current pattern on the specified instance."""
    player = ctx.players.get(instance)
    if player is None:
        return {"error": f"Instance '{instance}' not found"}
    t = ctx.config.patterns.transition
    await player.stop(duck_ms=duck_ms if duck_ms is not None else t.duck_ms)
    return {"status": "stopped", "instance": instance}


async def create_pattern(
    name: str,
    description: str = "",
    base_period: float = 1.0,
    duration: float = 0.0,
) -> dict[str, Any]:
    """Create a new empty leaf pattern."""
    from synapse.patterns.models import Pattern
    if ctx.store.exists(name):
        return {"error": f"Pattern '{name}' already exists"}
    p = Pattern(name=name, description=description, base_period=base_period, duration=duration)
    ctx.store.save(p)
    return {"name": name}


async def create_sequence(
    name: str,
    description: str = "",
    loop: bool = False,
) -> dict[str, Any]:
    """Create a new empty sequence pattern."""
    from synapse.patterns.models import Pattern
    if ctx.store.exists(name):
        return {"error": f"Pattern '{name}' already exists"}
    p = Pattern(name=name, description=description, loop=loop)
    ctx.store._patterns[name] = p
    return {"name": name}


async def describe_pattern(name: str) -> dict[str, Any]:
    """Get full pattern including layers, axes, and metadata."""
    from synapse.patterns.store import pattern_to_dict
    p = ctx.store.get(name)
    if p is None:
        return {"error": f"Pattern '{name}' not found"}
    return pattern_to_dict(p)


async def snapshot_pattern(
    name: str,
    instance: str = "primary",
    description: str = "",
) -> dict[str, Any]:
    """Save current axis state as a named pattern."""
    from synapse.patterns.models import AxisOscillator, Layer, Pattern
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


async def delete_pattern(name: str) -> dict[str, Any]:
    """Delete a saved pattern."""
    if not ctx.store.delete(name):
        return {"error": f"Pattern '{name}' not found"}
    return {"status": "deleted", "name": name}


# ── Pattern Layer CRUD ────────────────────────────────────────────────────────

async def list_layers(pattern_name: str) -> list[dict[str, Any]]:
    """List layers in a pattern."""
    p = ctx.store.get(pattern_name)
    if p is None:
        return [{"error": f"Pattern '{pattern_name}' not found"}]
    return [{"name": l.name, "blend": l.blend, "axis_count": len(l.axes)} for l in p.layers]


async def add_layer(
    pattern_name: str,
    blend: str = "set",
    layer_name: Optional[str] = None,
    instance: Optional[str] = None,
) -> dict[str, Any]:
    """Add a new layer to a pattern. Returns the assigned layer name."""
    from synapse.patterns.models import Layer
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
    from synapse.patterns.models import AxisOscillator
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


async def add_step(
    pattern_name: str,
    step_pattern: str,
    duration: Optional[float] = None,
    repeat: int = 1,
    transition: Optional[dict] = None,
) -> dict[str, Any]:
    """Append a step to a sequence pattern. Returns step index."""
    from synapse.patterns.models import SequenceStep
    p = ctx.store.get(pattern_name)
    if p is None:
        return {"error": f"Pattern '{pattern_name}' not found"}
    if p.layers:
        return {"error": "Cannot add steps to a leaf pattern"}
    p = copy.deepcopy(p)
    p.steps.append(SequenceStep(pattern=step_pattern, duration=duration, repeat=repeat, transition=transition))
    ctx.store.save(p)
    return {"index": len(p.steps) - 1}


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


# ── Session Recording ─────────────────────────────────────────────────────────

async def start_session(name: str, instance: str = "primary") -> dict[str, Any]:
    """Start recording all axis outputs to funscript files."""
    from datetime import datetime, timezone
    session_name = name or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    axis_ids = [a.tcode_id for a in ctx.axis_map.all_enabled()]
    ctx.session_manager.start_session(session_name, instance, axis_ids)
    return {"status": "recording", "name": session_name, "instance": instance}


async def stop_session(instance: str = "primary") -> dict[str, Any]:
    """Stop recording and flush funscript files. Returns session metadata."""
    meta = ctx.session_manager.stop_session(instance)
    if meta is None:
        return {"error": f"No active session for instance '{instance}'"}
    return meta.to_dict()


async def list_sessions() -> list[dict[str, Any]]:
    """List all recorded sessions."""
    return [m.to_dict() for m in ctx.session_manager.list_sessions()]


# ── User Profiles ─────────────────────────────────────────────────────────────

async def list_profiles() -> list[dict[str, Any]]:
    """List all user profiles."""
    return [p.to_dict() for p in ctx.profile_store.list()]


async def get_profile(name: str) -> dict[str, Any]:
    """Get a user profile by name."""
    profile = ctx.profile_store.get(name)
    if profile is None:
        return {"error": f"Profile '{name}' not found"}
    return profile.to_dict()


async def update_profile(
    name: str,
    preferred_volume_range: Optional[list] = None,
    preferred_patterns: Optional[list] = None,
    disliked_patterns: Optional[list] = None,
    preferred_carrier_hz: Optional[float] = None,
    preferred_pulse_hz: Optional[float] = None,
    preferred_base_period_s: Optional[float] = None,
    notes: Optional[str] = None,
    tags: Optional[dict] = None,
) -> dict[str, Any]:
    """Partially update a user profile. Only provided fields are changed."""
    kwargs: dict[str, Any] = {}
    if preferred_volume_range is not None:
        kwargs["preferred_volume_range"] = preferred_volume_range
    if preferred_patterns is not None:
        kwargs["preferred_patterns"] = preferred_patterns
    if disliked_patterns is not None:
        kwargs["disliked_patterns"] = disliked_patterns
    if preferred_carrier_hz is not None:
        kwargs["preferred_carrier_hz"] = preferred_carrier_hz
    if preferred_pulse_hz is not None:
        kwargs["preferred_pulse_hz"] = preferred_pulse_hz
    if preferred_base_period_s is not None:
        kwargs["preferred_base_period_s"] = preferred_base_period_s
    if notes is not None:
        kwargs["notes"] = notes
    if tags is not None:
        kwargs["tags"] = tags

    profile = ctx.profile_store.update(name, **kwargs)
    if profile is None:
        return {"error": f"Profile '{name}' not found"}
    return profile.to_dict()


# ── Exploration & A/B Testing ─────────────────────────────────────────────────

async def start_ab_test(
    profile_name: str,
    variable: str,
    option_a: dict,
    option_b: dict,
) -> dict[str, Any]:
    """Record start of an A/B test. Returns test_id."""
    from synapse.profiles.models import ABTestResult
    profile = ctx.profile_store.get(profile_name)
    if profile is None:
        return {"error": f"Profile '{profile_name}' not found"}

    test = ABTestResult.new(variable=variable, option_a=option_a, option_b=option_b)
    if "ab_tests" not in profile.tags:
        profile.tags["ab_tests"] = []
    profile.tags["ab_tests"].append(test.to_dict())
    ctx.profile_store.save(profile)
    return {"test_id": test.test_id, "variable": variable}


async def record_ab_result(
    profile_name: str,
    test_id: str,
    winner: str,
    notes: str = "",
) -> dict[str, Any]:
    """Record winner of an A/B test and save to profile."""
    profile = ctx.profile_store.get(profile_name)
    if profile is None:
        return {"error": f"Profile '{profile_name}' not found"}

    ab_tests = profile.tags.get("ab_tests", [])
    for test_dict in ab_tests:
        if test_dict.get("test_id") == test_id:
            test_dict["winner"] = winner
            test_dict["notes"] = notes
            profile.tags["ab_tests"] = ab_tests
            ctx.profile_store.save(profile)
            return {"status": "recorded", "test_id": test_id, "winner": winner}
    return {"error": f"Test '{test_id}' not found in profile '{profile_name}'"}


_EXPLORATION_ORDER = [
    "volume_range",
    "carrier_freq",
    "pulse_freq",
    "base_period",
    "spatial_motion",
    "pattern_complexity",
]


async def get_exploration_summary(profile_name: str) -> dict[str, Any]:
    """Return discovered preferences and recommended next A/B test variable."""
    profile = ctx.profile_store.get(profile_name)
    if profile is None:
        return {"error": f"Profile '{profile_name}' not found"}

    ab_tests = profile.tags.get("ab_tests", [])

    tested: dict[str, list[dict]] = {}
    for test in ab_tests:
        var = test.get("variable", "unknown")
        tested.setdefault(var, []).append(test)

    summary: dict[str, Any] = {}
    for var, results in tested.items():
        winners = [r["winner"] for r in results if r.get("winner")]
        a_wins = winners.count("a")
        b_wins = winners.count("b")
        preferred_option = None
        if a_wins > b_wins:
            preferred_option = results[-1].get("option_a") if results else None
        elif b_wins > a_wins:
            preferred_option = results[-1].get("option_b") if results else None
        summary[var] = {
            "test_count": len(results),
            "a_wins": a_wins,
            "b_wins": b_wins,
            "preferred_option": preferred_option,
        }

    next_variable = None
    for var in _EXPLORATION_ORDER:
        if var not in tested:
            next_variable = var
            break

    return {
        "profile": profile_name,
        "tested_variables": summary,
        "next_recommended_variable": next_variable,
        "exploration_complete": next_variable is None,
    }


# ── Memory Tools ──────────────────────────────────────────────────────────────

async def remember(
    text: str,
    category: str = "general",
    session_name: Optional[str] = None,
) -> dict[str, Any]:
    """Save a memory to the active profile. Use for anything worth knowing in future sessions: preferences, reactions, things to try."""
    profile_name = getattr(ctx, "active_profile_name", None)
    if not profile_name:
        return {"error": "No active profile set. Set a profile first."}
    memory = ctx.profile_store.add_memory(profile_name, text, category, session_name)
    return {"id": memory.id, "text": memory.text, "category": memory.category}


async def recall(query: str = "") -> list[dict[str, Any]]:
    """List memories from the active profile. Pass query to filter by text."""
    profile_name = getattr(ctx, "active_profile_name", None)
    if not profile_name:
        return []
    memories = ctx.profile_store.get_memories(profile_name, query)
    return [
        {
            "id": m.id,
            "text": m.text,
            "category": m.category,
            "created_at": m.created_at,
            "session_name": m.session_name,
        }
        for m in memories
    ]


async def note_observation(text: str) -> dict[str, Any]:
    """Save a session-scoped observation to the current session metadata."""
    # Stored as an in-memory list on ctx for the current session
    if not hasattr(ctx, "_session_observations"):
        ctx._session_observations = []
    from datetime import datetime, timezone
    obs = {
        "text": text,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    ctx._session_observations.append(obs)
    return {"status": "noted", "text": text}


async def forget(memory_id: str) -> dict[str, Any]:
    """Remove a memory by ID from the active profile."""
    profile_name = getattr(ctx, "active_profile_name", None)
    if not profile_name:
        return {"error": "No active profile set."}
    deleted = ctx.profile_store.delete_memory(profile_name, memory_id)
    if not deleted:
        return {"error": f"Memory '{memory_id}' not found"}
    return {"status": "deleted", "id": memory_id}


async def set_active_profile(name: str) -> dict[str, Any]:
    """Set the active profile for memory operations."""
    profile = ctx.profile_store.get(name)
    if profile is None:
        return {"error": f"Profile '{name}' not found"}
    ctx.active_profile_name = name
    return {"status": "ok", "active_profile": name}
