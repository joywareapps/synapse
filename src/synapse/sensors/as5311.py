from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

from synapse.config import AS5311Config
from synapse.sensors.models import SensorReading

logger = logging.getLogger(__name__)


class AS5311Sensor:
    def __init__(self, config: AS5311Config) -> None:
        self._config = config
        self._reading = SensorReading(name="as5311", value=0.0, timestamp=0.0)
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_position: Optional[float] = None
        self._last_time: Optional[float] = None

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

    async def _run(self) -> None:
        import websockets

        delay = 1.0
        while self._running:
            try:
                async with websockets.connect(self._config.url) as ws:
                    logger.info("AS5311 connected to %s", self._config.url)
                    delay = 1.0
                    async for message in ws:
                        if not self._running:
                            break
                        try:
                            data = json.loads(message)
                            self._process(data)
                        except (json.JSONDecodeError, KeyError) as e:
                            logger.warning("AS5311 bad message: %s", e)
            except Exception as e:
                if self._running:
                    logger.warning("AS5311 disconnected: %s — retry in %.1fs", e, delay)
                    self._reading = SensorReading(
                        name="as5311",
                        value=self._reading.value,
                        raw=self._reading.raw,
                        error=str(e),
                        timestamp=time.time(),
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 30.0)

    def _process(self, data: dict) -> None:
        x_m = float(data["x"])
        now = time.time()

        velocity = 0.0
        if self._last_position is not None and self._last_time is not None:
            dt = now - self._last_time
            if dt > 0:
                velocity = (x_m - self._last_position) / dt
        self._last_position = x_m
        self._last_time = now

        threshold_m = self._config.threshold_mm / 1000.0
        range_m = self._config.range_mm / 1000.0
        if range_m > 0:
            normalized = (x_m - threshold_m) / range_m
        else:
            normalized = 0.0
        normalized = max(0.0, min(1.0, normalized))

        self._reading = SensorReading(
            name="as5311",
            value=normalized,
            raw={"position_m": x_m, "velocity_m_s": velocity},
            error=None,
            timestamp=now,
        )

    def get_reading(self) -> SensorReading:
        return self._reading
