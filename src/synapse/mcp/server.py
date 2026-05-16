from __future__ import annotations

"""MCP server — thin @mcp.tool() wrappers around the shared tool registry."""

from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from synapse.api.deps import ctx
from synapse.patterns.store import pattern_to_dict
import synapse.tools.registry as reg

mcp = FastMCP("Synapse")


# ── Device State ──────────────────────────────────────────────────────────────

@mcp.tool()
async def get_status() -> dict[str, Any]:
    """Get Synapse and Restim status."""
    return await reg.get_status()


@mcp.tool()
async def get_axes() -> list[dict[str, Any]]:
    """List all axes with current values and limits."""
    return await reg.get_axes()


@mcp.tool()
async def get_axis(tcode_id: str) -> dict[str, Any]:
    """Get single axis value and definition."""
    return await reg.get_axis(tcode_id)


@mcp.tool()
async def get_restim_state() -> dict[str, Any]:
    """Get Restim play state and volume."""
    return await reg.get_restim_state()


# ── Sensor Readings ───────────────────────────────────────────────────────────

@mcp.tool()
async def get_sensors() -> list[dict[str, Any]]:
    """List all configured sensors with current values and status."""
    return await reg.get_sensors()


@mcp.tool()
async def get_sensor(name: str) -> dict[str, Any]:
    """Get a specific sensor's value and raw fields."""
    return await reg.get_sensor(name)


# ── Direct Control ────────────────────────────────────────────────────────────

@mcp.tool()
async def set_axis(tcode_id: str, value: float) -> dict[str, Any]:
    """Set axis to a specific normalized value (0.0-1.0)."""
    return await reg.set_axis(tcode_id, value)


@mcp.tool()
async def set_volume(value: float) -> dict[str, Any]:
    """Set main volume (0.0-1.0)."""
    return await reg.set_volume(value)


@mcp.tool()
async def spike(
    intensity: float,
    on_ms: int = 200,
    off_ms: int = 100,
    repeat: int = 1,
) -> dict[str, Any]:
    """Create a brief intensity spike (delta added to current volume)."""
    return await reg.spike(intensity, on_ms, off_ms, repeat)


@mcp.tool()
async def start_playback() -> dict[str, Any]:
    """Start Restim playback."""
    return await reg.start_playback()


@mcp.tool()
async def stop_playback() -> dict[str, Any]:
    """Stop Restim playback."""
    return await reg.stop_playback()


@mcp.tool()
async def emergency_stop() -> dict[str, Any]:
    """Immediately zero all axes on all instances and stop all patterns."""
    return await reg.emergency_stop()


# ── Pattern Control ───────────────────────────────────────────────────────────

@mcp.tool()
async def list_patterns() -> list[dict[str, Any]]:
    """List all saved patterns."""
    return await reg.list_patterns()


@mcp.tool()
async def play_pattern(
    name: str,
    instance: str = "primary",
    duck_amount: Optional[float] = None,
    duck_ms: Optional[int] = None,
    ramp_ms: Optional[int] = None,
) -> dict[str, Any]:
    """Start a named pattern on the specified instance."""
    return await reg.play_pattern(name, instance, duck_amount, duck_ms, ramp_ms)


@mcp.tool()
async def stop_pattern(instance: str = "primary", duck_ms: Optional[int] = None) -> dict[str, Any]:
    """Stop current pattern on the specified instance."""
    return await reg.stop_pattern(instance, duck_ms)


@mcp.tool()
async def create_pattern(
    name: str,
    description: str = "",
    base_period: float = 1.0,
    duration: float = 0.0,
) -> dict[str, Any]:
    """Create a new empty leaf pattern."""
    return await reg.create_pattern(name, description, base_period, duration)


@mcp.tool()
async def create_sequence(
    name: str,
    description: str = "",
    loop: bool = False,
) -> dict[str, Any]:
    """Create a new empty sequence pattern."""
    return await reg.create_sequence(name, description, loop)


@mcp.tool()
async def describe_pattern(name: str) -> dict[str, Any]:
    """Get full pattern including layers, axes, and metadata."""
    return await reg.describe_pattern(name)


@mcp.tool()
async def snapshot_pattern(
    name: str,
    instance: str = "primary",
    description: str = "",
) -> dict[str, Any]:
    """Save current axis state as a named pattern."""
    return await reg.snapshot_pattern(name, instance, description)


@mcp.tool()
async def delete_pattern(name: str) -> dict[str, Any]:
    """Delete a saved pattern."""
    return await reg.delete_pattern(name)


# ── Pattern Layer CRUD ────────────────────────────────────────────────────────

@mcp.tool()
async def list_layers(pattern_name: str) -> list[dict[str, Any]]:
    """List layers in a pattern."""
    return await reg.list_layers(pattern_name)


@mcp.tool()
async def add_layer(
    pattern_name: str,
    blend: str = "set",
    layer_name: Optional[str] = None,
    instance: Optional[str] = None,
) -> dict[str, Any]:
    """Add a new layer to a pattern. Returns the assigned layer name."""
    return await reg.add_layer(pattern_name, blend, layer_name, instance)


@mcp.tool()
async def describe_layer(pattern_name: str, layer_name: str) -> dict[str, Any]:
    """Get layer details including blend mode and all axes."""
    return await reg.describe_layer(pattern_name, layer_name)


@mcp.tool()
async def modify_layer(
    pattern_name: str,
    layer_name: str,
    blend: Optional[str] = None,
    new_name: Optional[str] = None,
) -> dict[str, Any]:
    """Change a layer's blend mode or name."""
    return await reg.modify_layer(pattern_name, layer_name, blend, new_name)


@mcp.tool()
async def remove_layer(pattern_name: str, layer_name: str) -> dict[str, Any]:
    """Remove a layer from a pattern."""
    return await reg.remove_layer(pattern_name, layer_name)


@mcp.tool()
async def move_layer(pattern_name: str, layer_name: str, index: int) -> dict[str, Any]:
    """Reorder a layer within a pattern."""
    return await reg.move_layer(pattern_name, layer_name, index)


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
    return await reg.set_layer_axis(
        pattern_name, layer_name, tcode_id, waveform, amplitude, center, offset,
        frequency, freq_multiple, attack, sustain, release,
    )


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
    return await reg.modify_layer_axis(
        pattern_name, layer_name, tcode_id, waveform, amplitude, center, offset,
        frequency, freq_multiple, attack, sustain, release,
    )


@mcp.tool()
async def remove_layer_axis(pattern_name: str, layer_name: str, tcode_id: str) -> dict[str, Any]:
    """Remove an axis from a layer."""
    return await reg.remove_layer_axis(pattern_name, layer_name, tcode_id)


# ── Sequence Step CRUD ────────────────────────────────────────────────────────

@mcp.tool()
async def list_steps(pattern_name: str) -> list[dict[str, Any]]:
    """List steps in a sequence pattern."""
    return await reg.list_steps(pattern_name)


@mcp.tool()
async def add_step(
    pattern_name: str,
    step_pattern: str,
    duration: Optional[float] = None,
    repeat: int = 1,
    transition: Optional[dict] = None,
) -> dict[str, Any]:
    """Append a step to a sequence pattern. Returns step index."""
    return await reg.add_step(pattern_name, step_pattern, duration, repeat, transition)


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
    return await reg.modify_step(pattern_name, step_index, step_pattern, duration, repeat, transition)


@mcp.tool()
async def remove_step(pattern_name: str, step_index: int) -> dict[str, Any]:
    """Remove a step by index from a sequence pattern."""
    return await reg.remove_step(pattern_name, step_index)


@mcp.tool()
async def move_step(pattern_name: str, step_index: int, new_index: int) -> dict[str, Any]:
    """Reorder a step in a sequence pattern."""
    return await reg.move_step(pattern_name, step_index, new_index)


# ── Session Recording ─────────────────────────────────────────────────────────

@mcp.tool()
async def start_session(name: str, instance: str = "primary") -> dict[str, Any]:
    """Start recording all axis outputs to funscript files."""
    return await reg.start_session(name, instance)


@mcp.tool()
async def stop_session(instance: str = "primary") -> dict[str, Any]:
    """Stop recording and flush funscript files. Returns session metadata."""
    return await reg.stop_session(instance)


@mcp.tool()
async def list_sessions() -> list[dict[str, Any]]:
    """List all recorded sessions."""
    return await reg.list_sessions()


# ── User Profiles ─────────────────────────────────────────────────────────────

@mcp.tool()
async def list_profiles() -> list[dict[str, Any]]:
    """List all user profiles."""
    return await reg.list_profiles()


@mcp.tool()
async def get_profile(name: str) -> dict[str, Any]:
    """Get a user profile by name."""
    return await reg.get_profile(name)


@mcp.tool()
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
    return await reg.update_profile(
        name, preferred_volume_range, preferred_patterns, disliked_patterns,
        preferred_carrier_hz, preferred_pulse_hz, preferred_base_period_s, notes, tags,
    )


# ── Exploration & A/B Testing ─────────────────────────────────────────────────

@mcp.tool()
async def start_ab_test(
    profile_name: str,
    variable: str,
    option_a: dict,
    option_b: dict,
) -> dict[str, Any]:
    """Record start of an A/B test. Returns test_id."""
    return await reg.start_ab_test(profile_name, variable, option_a, option_b)


@mcp.tool()
async def record_ab_result(
    profile_name: str,
    test_id: str,
    winner: str,
    notes: str = "",
) -> dict[str, Any]:
    """Record winner of an A/B test and save to profile."""
    return await reg.record_ab_result(profile_name, test_id, winner, notes)


@mcp.tool()
async def get_exploration_summary(profile_name: str) -> dict[str, Any]:
    """Return discovered preferences and recommended next A/B test variable."""
    return await reg.get_exploration_summary(profile_name)


# ── Memory Tools ──────────────────────────────────────────────────────────────

@mcp.tool()
async def remember(
    text: str,
    category: str = "general",
    session_name: Optional[str] = None,
) -> dict[str, Any]:
    """Save a memory to the active profile. Use for anything worth knowing in future sessions: preferences, reactions, things to try."""
    return await reg.remember(text, category, session_name)


@mcp.tool()
async def recall(query: str = "") -> list[dict[str, Any]]:
    """List memories from the active profile. Pass query to filter by text."""
    return await reg.recall(query)


@mcp.tool()
async def note_observation(text: str) -> dict[str, Any]:
    """Save a session-scoped observation to the current session metadata."""
    return await reg.note_observation(text)


@mcp.tool()
async def forget(memory_id: str) -> dict[str, Any]:
    """Remove a memory by ID from the active profile."""
    return await reg.forget(memory_id)


@mcp.tool()
async def set_active_profile(name: str) -> dict[str, Any]:
    """Set the active profile for memory operations."""
    return await reg.set_active_profile(name)


# ── MCP Resources ─────────────────────────────────────────────────────────────

@mcp.resource("synapse://status")
async def resource_status() -> str:
    import json
    result = await reg.get_status()
    return json.dumps(result, indent=2)


@mcp.resource("synapse://axes")
async def resource_axes() -> str:
    import json
    result = await reg.get_axes()
    return json.dumps(result, indent=2)


@mcp.resource("synapse://patterns")
async def resource_patterns() -> str:
    import json
    result = await reg.list_patterns()
    return json.dumps(result, indent=2)


@mcp.resource("synapse://pattern/{name}")
async def resource_pattern(name: str) -> str:
    import json
    p = ctx.store.get(name)
    if p is None:
        return json.dumps({"error": f"Pattern '{name}' not found"})
    return json.dumps(pattern_to_dict(p), indent=2)


@mcp.resource("synapse://guide")
async def get_guide() -> str:
    """Operational guide for LLM. Read this before any session."""
    import pathlib
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "docs" / "mcp-guide.md"
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    return "Guide not found. Proceed with caution and follow safety rules."


@mcp.resource("synapse://profile/{name}")
async def get_profile_resource(name: str) -> str:
    """User profile as YAML."""
    import yaml
    profile = ctx.profile_store.get(name)
    if profile is None:
        return f"Profile '{name}' not found."
    return yaml.dump(profile.to_dict(), default_flow_style=False, allow_unicode=True)


@mcp.resource("synapse://sessions")
async def get_sessions_resource() -> str:
    """Session list as JSON."""
    import json
    sessions = ctx.session_manager.list_sessions()
    return json.dumps([s.to_dict() for s in sessions], indent=2)
