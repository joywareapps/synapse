from __future__ import annotations

"""Tool schema builder and dispatcher for the embedded agent."""

import inspect
import logging
from typing import Any, Optional, get_args, get_origin, get_type_hints

import synapse.tools.registry as reg

logger = logging.getLogger(__name__)

# All tool functions exported from the registry
_TOOL_FUNCTIONS: dict[str, Any] = {
    "get_status": reg.get_status,
    "get_axes": reg.get_axes,
    "get_axis": reg.get_axis,
    "get_restim_state": reg.get_restim_state,
    "get_sensors": reg.get_sensors,
    "get_sensor": reg.get_sensor,
    "set_axis": reg.set_axis,
    "set_volume": reg.set_volume,
    "spike": reg.spike,
    "start_playback": reg.start_playback,
    "stop_playback": reg.stop_playback,
    "emergency_stop": reg.emergency_stop,
    "list_patterns": reg.list_patterns,
    "play_pattern": reg.play_pattern,
    "stop_pattern": reg.stop_pattern,
    "create_pattern": reg.create_pattern,
    "create_sequence": reg.create_sequence,
    "describe_pattern": reg.describe_pattern,
    "snapshot_pattern": reg.snapshot_pattern,
    "delete_pattern": reg.delete_pattern,
    "list_layers": reg.list_layers,
    "add_layer": reg.add_layer,
    "describe_layer": reg.describe_layer,
    "modify_layer": reg.modify_layer,
    "remove_layer": reg.remove_layer,
    "move_layer": reg.move_layer,
    "set_layer_axis": reg.set_layer_axis,
    "modify_layer_axis": reg.modify_layer_axis,
    "remove_layer_axis": reg.remove_layer_axis,
    "list_steps": reg.list_steps,
    "add_step": reg.add_step,
    "modify_step": reg.modify_step,
    "remove_step": reg.remove_step,
    "move_step": reg.move_step,
    "start_session": reg.start_session,
    "stop_session": reg.stop_session,
    "list_sessions": reg.list_sessions,
    "list_profiles": reg.list_profiles,
    "get_profile": reg.get_profile,
    "update_profile": reg.update_profile,
    "start_ab_test": reg.start_ab_test,
    "record_ab_result": reg.record_ab_result,
    "get_exploration_summary": reg.get_exploration_summary,
    "remember": reg.remember,
    "recall": reg.recall,
    "note_observation": reg.note_observation,
    "forget": reg.forget,
    "set_active_profile": reg.set_active_profile,
}


def _python_type_to_json_schema(annotation: Any) -> dict:
    """Convert a Python type annotation to a JSON Schema type descriptor."""
    origin = get_origin(annotation)
    args = get_args(annotation)

    # Optional[X] → X, not required (handled by caller)
    if origin is type(None):
        return {"type": "null"}

    # Union / Optional
    if origin is not None and hasattr(origin, "__name__") is False:
        # Could be Union; check for Optional pattern
        pass

    # Handle Optional[X] == Union[X, None]
    import types as _types
    try:
        import typing
        if origin is typing.Union:
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) == 1:
                return _python_type_to_json_schema(non_none[0])
            return {"type": "string"}  # fallback for complex unions
    except Exception:
        pass

    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is dict or annotation == dict:
        return {"type": "object"}

    # list[X] or list
    if origin is list or annotation is list:
        if args:
            return {"type": "array", "items": _python_type_to_json_schema(args[0])}
        return {"type": "array"}

    # Fallback
    return {"type": "string"}


def _is_optional(annotation: Any) -> bool:
    """Return True if annotation is Optional[X] (i.e. includes None)."""
    import typing
    origin = get_origin(annotation)
    if origin is typing.Union:
        return type(None) in get_args(annotation)
    return False


def build_tool_schemas() -> list[dict]:
    """Build OpenAI-format tool schema list from the tool registry."""
    schemas = []
    for name, fn in _TOOL_FUNCTIONS.items():
        try:
            sig = inspect.signature(fn)
            hints = get_type_hints(fn)
            # Remove return annotation
            hints.pop("return", None)

            properties: dict[str, Any] = {}
            required: list[str] = []

            for param_name, param in sig.parameters.items():
                if param_name == "self":
                    continue
                annotation = hints.get(param_name, Any)
                schema = _python_type_to_json_schema(annotation)

                # Add description from param name as best-effort
                properties[param_name] = schema

                # Required if no default and not Optional
                has_default = param.default is not inspect.Parameter.empty
                optional = _is_optional(annotation)
                if not has_default and not optional:
                    required.append(param_name)

            tool_schema = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": (fn.__doc__ or "").strip(),
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }
            schemas.append(tool_schema)
        except Exception as exc:
            logger.warning("Failed to build schema for tool %s: %s", name, exc)

    return schemas


async def dispatch_tool_call(tool_name: str, tool_args: dict) -> Any:
    """Look up and call the named tool function from the registry."""
    fn = _TOOL_FUNCTIONS.get(tool_name)
    if fn is None:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        return await fn(**tool_args)
    except Exception as exc:
        logger.exception("Tool call failed: %s(%s)", tool_name, tool_args)
        return {"error": str(exc)}
