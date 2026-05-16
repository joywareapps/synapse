from __future__ import annotations

"""Autonomous agent loop — background task that periodically queries the LLM."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from synapse.agent.agent import SynapseAgent, _broadcast
from synapse.agent.tool_dispatch import dispatch_tool_call, build_tool_schemas
from synapse.api.deps import ctx

logger = logging.getLogger(__name__)

# Read-only tool whitelist for observe mode
_OBSERVE_WHITELIST = frozenset({
    "get_status",
    "get_axes",
    "get_axis",
    "get_sensors",
    "get_sensor",
    "get_restim_state",
    "recall",
    "note_observation",
    "list_patterns",
    "describe_pattern",
    "list_sessions",
    "get_profile",
    "list_profiles",
})


class AgentLoop:
    def __init__(
        self,
        agent: SynapseAgent,
        interval_s: float = 30.0,
        mode: str = "observe",
        max_tool_calls: int = 2,
    ) -> None:
        self.agent = agent
        self.interval_s = interval_s
        self.mode = mode
        self.max_tool_calls = max_tool_calls

        self._running = False
        self._tick_count = 0
        self._last_tick_at: Optional[str] = None
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the autonomous loop as a background asyncio task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Stop the loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def status(self) -> dict:
        return {
            "running": self._running,
            "mode": self.mode,
            "interval_s": self.interval_s,
            "tick_count": self._tick_count,
            "last_tick_at": self._last_tick_at,
        }

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Agent loop tick failed: %s", exc)
            await asyncio.sleep(self.interval_s)

    async def _tick(self) -> None:
        """One autonomous iteration."""
        self._tick_count += 1
        self._last_tick_at = datetime.now(timezone.utc).isoformat()

        # Build context message
        context_parts = ["[Autonomous tick — react only if something meaningful requires attention]"]

        try:
            instances = []
            for inst_id, engine in ctx.engines.items():
                player = ctx.players.get(inst_id)
                connected = engine.is_connected()
                pattern = (
                    player.current_pattern().name
                    if player and player.current_pattern()
                    else "none"
                )
                instances.append(
                    f"Instance: {inst_id} | Connected: {'yes' if connected else 'no'} | Active pattern: {pattern}"
                )
            context_parts.append("\n".join(instances))
        except Exception:
            pass

        try:
            sensors = ctx.sensor_manager.get_all_with_restim()
            sensor_str = " | ".join(
                f"{r.name}={r.value:.2f}" for r in sensors if r.value is not None
            )
            if sensor_str:
                context_parts.append(f"Sensors: {sensor_str}")
        except Exception:
            pass

        tick_message = "\n".join(context_parts)

        # Build tool list (filtered by mode)
        tools = build_tool_schemas()
        if self.mode == "observe":
            tools = [t for t in tools if t["function"]["name"] in _OBSERVE_WHITELIST]

        system_prompt = self.agent.build_system_prompt()
        messages = (
            [{"role": "system", "content": system_prompt}]
            + self.agent.get_history()
            + [{"role": "user", "content": tick_message}]
        )

        tool_calls_made = 0

        try:
            response = await self.agent.llm_client.chat(messages, tools=tools)
        except Exception as exc:
            logger.warning("Agent loop LLM call failed: %s", exc)
            return

        choice = response.get("choices", [{}])[0]
        message = choice.get("message", {})
        tool_calls = message.get("tool_calls") or []

        if tool_calls:
            await _broadcast({"type": "tool_calls", "tool_calls": tool_calls, "source": "loop"})

            for tc in tool_calls:
                if tool_calls_made >= self.max_tool_calls:
                    break

                fn = tc.get("function", {})
                tool_name = fn.get("name", "")

                # In observe mode, skip non-whitelisted tools
                if self.mode == "observe" and tool_name not in _OBSERVE_WHITELIST:
                    logger.debug("Loop: skipping non-read tool %s in observe mode", tool_name)
                    continue

                try:
                    tool_args = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    tool_args = {}

                result = await dispatch_tool_call(tool_name, tool_args)
                tool_calls_made += 1
                await _broadcast({
                    "type": "tool_result",
                    "tool_name": tool_name,
                    "result": result,
                    "source": "loop",
                })

        # If there's a text response, add to history and broadcast
        text = message.get("content") or ""
        if text:
            self.agent._history.append({"role": "assistant", "content": text})
            await _broadcast({"type": "message", "text": text, "role": "assistant", "source": "loop"})
