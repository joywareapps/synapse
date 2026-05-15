from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Optional

from synapse.axes import AxisMap
from synapse.config import EngineConfig, RestimInstanceConfig
from synapse.patterns.player import PatternPlayer
from synapse.tcode import TCodeFormatter

if TYPE_CHECKING:
    from synapse.sessions.manager import SessionManager

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 2.0


class TCodeEngine:
    def __init__(
        self,
        instance_config: RestimInstanceConfig,
        engine_config: EngineConfig,
        axis_map: AxisMap,
        player: PatternPlayer,
        session_manager: Optional["SessionManager"] = None,
    ) -> None:
        self._inst = instance_config
        self._config = engine_config
        self._axis_map = axis_map
        self._player = player
        self._formatter = TCodeFormatter(axis_map)
        self._session_manager = session_manager
        self._session_start_wall: float = time.monotonic()

        self._task: Optional[asyncio.Task] = None
        self._running = False

        # Thread-safe current axis values
        self._current_values: dict[str, float] = {}
        self._last_send_time: float = 0.0

        # TCP connection state
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._disconnect()

    async def emergency_stop(self) -> None:
        """Zero all axes immediately."""
        self._player._playing = False
        self._player._pattern = None
        for axis in self._axis_map.all_enabled():
            self._current_values[axis.tcode_id] = 0.0
        await self._send_all_zero()

    async def _send_all_zero(self) -> None:
        parts = []
        for axis in self._axis_map.all_enabled():
            parts.append(f"{axis.tcode_id}0000I20")
        if parts and self._writer:
            msg = " ".join(parts) + "\n"
            try:
                self._writer.write(msg.encode())
                await self._writer.drain()
            except Exception:
                pass

    async def _run(self) -> None:
        interval = 1.0 / self._config.update_rate_hz
        reconnect_delay = self._config.reconnect_delay_ms / 1000.0
        max_delay = self._config.max_reconnect_delay_ms / 1000.0

        while self._running:
            if not self._connected:
                try:
                    await self._connect()
                    reconnect_delay = self._config.reconnect_delay_ms / 1000.0
                except Exception as e:
                    logger.warning(
                        "[%s] TCP connect failed: %s — retry in %.1fs",
                        self._inst.id,
                        e,
                        reconnect_delay,
                    )
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, max_delay)
                    continue

            tick_start = time.monotonic()
            try:
                await self._tick()
            except Exception as e:
                logger.warning("[%s] Tick error: %s", self._inst.id, e)
                await self._disconnect()

            elapsed = time.monotonic() - tick_start
            sleep_time = max(0.0, interval - elapsed)
            await asyncio.sleep(sleep_time)

    async def _connect(self) -> None:
        reader, writer = await asyncio.open_connection(
            self._inst.host, self._inst.tcode_port
        )
        self._writer = writer
        self._connected = True
        logger.info("[%s] Connected to %s:%d", self._inst.id, self._inst.host, self._inst.tcode_port)

    async def _disconnect(self) -> None:
        self._connected = False
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None

    async def _tick(self) -> None:
        now = time.monotonic()
        t = now

        # Evaluate player
        values = self._player.evaluate(t)
        self._current_values = dict(values)

        # Session recording — only do work if a recorder is active for this instance
        if self._session_manager is not None and self._session_manager.is_recording(self._inst.id):
            elapsed_ms = int((now - self._session_start_wall) * 1000)
            self._session_manager.record_tick(self._inst.id, self._current_values, elapsed_ms)

        # Heartbeat: resend one axis if idle
        if not values and (now - self._last_send_time) > HEARTBEAT_INTERVAL:
            axes = self._axis_map.all_enabled()
            if axes:
                axis = axes[0]
                val = self._current_values.get(axis.tcode_id, 0.0)
                cmd = self._formatter.format_normalized(axis.tcode_id, val, interval_ms=20)
                if cmd:
                    await self._send_line(cmd)
            return

        if not values:
            return

        parts = []
        for tcode_id, norm_val in values.items():
            cmd = self._formatter.format_normalized(tcode_id, norm_val, interval_ms=20)
            if cmd:
                parts.append(cmd)

        if parts:
            await self._send_line(" ".join(parts))

    async def _send_line(self, line: str) -> None:
        if not self._writer:
            raise RuntimeError("Not connected")
        self._writer.write((line + "\n").encode())
        await self._writer.drain()
        self._last_send_time = time.monotonic()

    def get_current_values(self) -> dict[str, float]:
        return dict(self._current_values)

    def is_connected(self) -> bool:
        return self._connected
