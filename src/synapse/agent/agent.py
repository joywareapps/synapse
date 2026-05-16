from __future__ import annotations

"""Embedded agent — LLM chat with tool use and persistent memory."""

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Optional

from synapse.agent.llm_client import LLMClient
from synapse.agent.tool_dispatch import build_tool_schemas, dispatch_tool_call
from synapse.api.deps import ctx

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 10

# Shared asyncio queue for broadcasting agent messages to WebSocket clients
agent_broadcast_queue: asyncio.Queue = asyncio.Queue()


class SynapseAgent:
    def __init__(
        self,
        llm_client: LLMClient,
        profile_name: Optional[str] = None,
    ) -> None:
        self.llm_client = llm_client
        self.profile_name = profile_name
        self._history: list[dict] = []

    def build_system_prompt(self) -> str:
        """Freshly build system prompt from guide + active profile + memories + current state."""
        parts: list[str] = []

        # Operational guide
        guide = _load_guide()
        if guide:
            parts.append(f"[Operational Guide]\n{guide}")

        # Profile block
        if self.profile_name:
            try:
                profile = ctx.profile_store.get(self.profile_name)
                if profile:
                    pvr = profile.preferred_volume_range
                    lines = [
                        f"[Active Profile: {profile.name}]",
                        f"Preferred volume range: {pvr[0]}–{pvr[1]}",
                    ]
                    if profile.preferred_patterns:
                        lines.append(f"Preferred patterns: {', '.join(profile.preferred_patterns)}")
                    if profile.notes:
                        lines.append(f"Notes: {profile.notes}")
                    parts.append("\n".join(lines))

                # Memories block
                memories = ctx.profile_store.get_memories(self.profile_name)
                if memories:
                    mem_lines = ["[Memories]"]
                    for m in memories:
                        date_part = m.created_at[:10] if m.created_at else "?"
                        mem_lines.append(f"• [{date_part}, {m.category}] {m.text}")
                    parts.append("\n".join(mem_lines))
            except Exception as exc:
                logger.warning("Failed to load profile/memories for system prompt: %s", exc)

        # Current state block
        try:
            state_lines = ["[Current State]"]
            for inst_id, engine in ctx.engines.items():
                player = ctx.players.get(inst_id)
                connected = engine.is_connected()
                pattern = player.current_pattern().name if player and player.current_pattern() else "none"
                state_lines.append(
                    f"Instance: {inst_id} | Connected: {'yes' if connected else 'no'} | Active pattern: {pattern}"
                )
            # Sensors
            try:
                sensors = ctx.sensor_manager.get_all_with_restim()
                if sensors:
                    sensor_str = " | ".join(
                        f"{r.name}={r.value:.2f}" for r in sensors if r.value is not None
                    )
                    if sensor_str:
                        state_lines.append(f"Sensors: {sensor_str}")
            except Exception:
                pass
            parts.append("\n".join(state_lines))
        except Exception as exc:
            logger.debug("Failed to build state block: %s", exc)

        # Extra prompt from config
        try:
            extra = ctx.config.agent.system_prompt_extra
            if extra:
                parts.append(extra)
        except Exception:
            pass

        return "\n\n".join(parts)

    async def chat(self, user_message: str) -> str:
        """Add user message to history, call LLM, handle tool calls, return response text."""
        self._history.append({"role": "user", "content": user_message})

        tools = build_tool_schemas()
        response_text = ""

        for iteration in range(MAX_TOOL_ITERATIONS):
            system_prompt = self.build_system_prompt()
            messages = [{"role": "system", "content": system_prompt}] + self._history

            try:
                response = await self.llm_client.chat(messages, tools=tools)
            except Exception as exc:
                error_msg = f"LLM error: {exc}"
                logger.exception("LLM chat failed")
                self._history.append({"role": "assistant", "content": error_msg})
                await _broadcast({"type": "error", "text": error_msg})
                return error_msg

            choice = response.get("choices", [{}])[0]
            message = choice.get("message", {})
            tool_calls = message.get("tool_calls") or []

            if tool_calls:
                # Add assistant message with tool calls to history
                self._history.append(message)
                await _broadcast({"type": "tool_calls", "tool_calls": tool_calls})

                # Execute all tool calls
                for tc in tool_calls:
                    tc_id = tc.get("id", "")
                    fn = tc.get("function", {})
                    tool_name = fn.get("name", "")
                    try:
                        tool_args = json.loads(fn.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        tool_args = {}

                    result = await dispatch_tool_call(tool_name, tool_args)
                    result_str = json.dumps(result) if not isinstance(result, str) else result

                    tool_result_msg = {
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": result_str,
                    }
                    self._history.append(tool_result_msg)
                    await _broadcast({
                        "type": "tool_result",
                        "tool_name": tool_name,
                        "result": result,
                    })
                # Continue loop to get next LLM response
            else:
                # Final text response
                response_text = message.get("content", "") or ""
                self._history.append({"role": "assistant", "content": response_text})
                await _broadcast({"type": "message", "text": response_text, "role": "assistant"})
                break

        return response_text

    def get_history(self) -> list[dict]:
        """Return conversation history."""
        return list(self._history)

    def clear_history(self) -> None:
        self._history.clear()


def _load_guide() -> str:
    import pathlib
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "docs" / "mcp-guide.md"
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    return ""


async def _broadcast(msg: dict) -> None:
    """Put a message on the broadcast queue for WebSocket consumers."""
    try:
        agent_broadcast_queue.put_nowait(msg)
    except asyncio.QueueFull:
        pass
