from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from synapse.config import HeartRateConfig
from synapse.sensors.models import SensorReading

logger = logging.getLogger(__name__)

HR_CHARACTERISTIC_UUID = "00002a37-0000-1000-8000-00805f9b34fb"


class HeartRateSensor:
    def __init__(self, config: HeartRateConfig) -> None:
        self._config = config
        self._reading = SensorReading(name="heart_rate", value=0.0, timestamp=0.0)
        self._task: Optional[asyncio.Task] = None
        self._running = False

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
        from bleak import BleakClient, BleakScanner

        delay = 2.0
        while self._running:
            try:
                address = self._config.device_address
                if not address:
                    logger.info("Scanning for heart rate device...")
                    device = await BleakScanner.find_device_by_filter(
                        lambda d, adv: HR_CHARACTERISTIC_UUID in (adv.service_uuids or []),
                        timeout=10.0,
                    )
                    if device is None:
                        raise RuntimeError("No HR device found")
                    address = device.address

                async with BleakClient(address) as client:
                    logger.info("Heart rate sensor connected: %s", address)
                    delay = 2.0

                    def _callback(_, data: bytearray) -> None:
                        self._process(data)

                    await client.start_notify(HR_CHARACTERISTIC_UUID, _callback)
                    while self._running and client.is_connected:
                        await asyncio.sleep(1.0)
                    await client.stop_notify(HR_CHARACTERISTIC_UUID)

            except Exception as e:
                if self._running:
                    logger.warning("HR sensor error: %s — retry in %.1fs", e, delay)
                    self._reading = SensorReading(
                        name="heart_rate",
                        value=self._reading.value,
                        raw=self._reading.raw,
                        error=str(e),
                        timestamp=time.time(),
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 30.0)

    def _process(self, data: bytearray) -> None:
        # GATT 0x2A37: flags byte, then HR value (8 or 16 bit)
        flags = data[0]
        if flags & 0x01:
            bpm = int.from_bytes(data[1:3], "little")
        else:
            bpm = data[1]

        scale_min = self._config.scale_min_bpm
        scale_max = self._config.scale_max_bpm
        if scale_max > scale_min:
            normalized = (bpm - scale_min) / (scale_max - scale_min)
        else:
            normalized = 0.0
        normalized = max(0.0, min(1.0, normalized))

        self._reading = SensorReading(
            name="heart_rate",
            value=normalized,
            raw={"bpm": bpm},
            error=None,
            timestamp=time.time(),
        )

    def get_reading(self) -> SensorReading:
        return self._reading
