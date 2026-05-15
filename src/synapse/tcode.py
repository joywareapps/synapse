from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from synapse.axes import AxisDef, AxisMap


@dataclass
class TCodeCommand:
    axis_id: str
    value: float       # real-world or percentage value (0.0–1.0 for percentage axes)
    interval_ms: int = 0

    def format_cmd(self) -> str:
        clamped = max(0.0, min(0.9999, self.value))
        int_val = int(clamped * 10000)
        if self.interval_ms > 0:
            return f"{self.axis_id}{int_val:04d}I{self.interval_ms}"
        return f"{self.axis_id}{int_val:04d}"


class TCodeFormatter:
    """Converts real-world axis values to TCode command strings."""

    def __init__(self, axis_map: AxisMap) -> None:
        self._axis_map = axis_map

    def format(self, tcode_id: str, real_value: float, interval_ms: int = 0) -> Optional[str]:
        axis = self._axis_map.get_by_id(tcode_id)
        if axis is None or not axis.enabled:
            return None
        tcode_value = self._map_value(real_value, axis)
        cmd = TCodeCommand(tcode_id, tcode_value, interval_ms)
        return cmd.format_cmd()

    def format_normalized(self, tcode_id: str, normalized: float, interval_ms: int = 0) -> Optional[str]:
        """Format a value that is already normalized to [0, 1]."""
        axis = self._axis_map.get_by_id(tcode_id)
        if axis is None or not axis.enabled:
            return None
        clamped = max(0.0, min(0.9999, normalized))
        cmd = TCodeCommand(tcode_id, clamped, interval_ms)
        return cmd.format_cmd()

    @staticmethod
    def _map_value(real_value: float, axis: AxisDef) -> float:
        span = axis.limit_max - axis.limit_min
        if span == 0:
            return 0.0
        return (real_value - axis.limit_min) / span
