from __future__ import annotations

import logging
from typing import Optional

from synapse.config import SensorsConfig
from synapse.sensors.as5311 import AS5311Sensor
from synapse.sensors.heart_rate import HeartRateSensor
from synapse.sensors.models import SensorReading

logger = logging.getLogger(__name__)


class SensorManager:
    def __init__(self, config: SensorsConfig) -> None:
        self._config = config
        self._as5311: Optional[AS5311Sensor] = None
        self._heart_rate: Optional[HeartRateSensor] = None

        if config.as5311.enabled:
            self._as5311 = AS5311Sensor(config.as5311)
        if config.heart_rate.enabled:
            self._heart_rate = HeartRateSensor(config.heart_rate)

    async def start(self) -> None:
        if self._as5311:
            await self._as5311.start()
        if self._heart_rate:
            await self._heart_rate.start()

    async def stop(self) -> None:
        if self._as5311:
            await self._as5311.stop()
        if self._heart_rate:
            await self._heart_rate.stop()

    def get_all(self) -> list[SensorReading]:
        readings = []
        if self._as5311:
            readings.append(self._as5311.get_reading())
        if self._heart_rate:
            readings.append(self._heart_rate.get_reading())
        return readings

    def get(self, name: str) -> Optional[SensorReading]:
        if name == "as5311" and self._as5311:
            return self._as5311.get_reading()
        if name == "heart_rate" and self._heart_rate:
            return self._heart_rate.get_reading()
        return None

    def add_restim_volume(self, volume_ui: float, volume_device: float) -> None:
        """Update restim volume sensor reading (called by restim client)."""
        self._restim_volume = SensorReading(
            name="restim_volume",
            value=volume_ui,
            raw={"volume_ui": volume_ui, "volume_device": volume_device},
        )

    def get_restim_volume(self) -> Optional[SensorReading]:
        return getattr(self, "_restim_volume", None)

    def get_all_with_restim(self) -> list[SensorReading]:
        readings = self.get_all()
        rv = self.get_restim_volume()
        if rv:
            readings.append(rv)
        return readings

    def get_by_name(self, name: str) -> Optional[SensorReading]:
        if name == "restim_volume":
            return self.get_restim_volume()
        return self.get(name)
