from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AxisDef:
    tcode_id: str
    name: str
    value_type: str  # "linear" | "percentage" | "frequency"
    limit_min: float
    limit_max: float
    enabled: bool = True


# Restim built-in defaults; actual values come from INI
KNOWN_AXES: dict[str, AxisDef] = {
    "alpha": AxisDef("L0", "alpha", "percentage", -1.0, 1.0),
    "beta": AxisDef("L1", "beta", "percentage", -1.0, 1.0),
    "volume": AxisDef("V0", "volume", "percentage", 0.0, 1.0),
    "volume_ext": AxisDef("", "volume_ext", "percentage", 0.0, 1.0, enabled=False),
    "carrier_freq": AxisDef("C0", "carrier_freq", "frequency", 500.0, 1000.0),
    "pulse_freq": AxisDef("P0", "pulse_freq", "frequency", 0.0, 100.0),
    "pulse_width": AxisDef("P1", "pulse_width", "linear", 4.0, 10.0),
    "pulse_random": AxisDef("P2", "pulse_random", "percentage", 0.0, 1.0),
    "pulse_rise": AxisDef("P3", "pulse_rise", "frequency", 2.0, 20.0),
    "e1": AxisDef("", "e1", "percentage", 0.0, 1.0, enabled=False),
    "e2": AxisDef("", "e2", "percentage", 0.0, 1.0, enabled=False),
    "e3": AxisDef("", "e3", "percentage", 0.0, 1.0, enabled=False),
    "e4": AxisDef("", "e4", "percentage", 0.0, 1.0, enabled=False),
}


class AxisMap:
    """Live mapping of tcode_id → AxisDef, built from INI + defaults."""

    def __init__(self) -> None:
        # Build default map: tcode_id → AxisDef (skip disabled/empty tcode_id)
        self._by_id: dict[str, AxisDef] = {}
        self._by_name: dict[str, AxisDef] = {}
        for name, axis in KNOWN_AXES.items():
            self._by_name[name] = axis
            if axis.tcode_id:
                self._by_id[axis.tcode_id] = axis

    def apply_ini(self, ini_axes: dict[str, AxisDef]) -> None:
        """Replace/update axis defs from INI-parsed data."""
        # Remove old entries for axes being replaced
        for name, new_def in ini_axes.items():
            old = self._by_name.get(name)
            if old and old.tcode_id and old.tcode_id in self._by_id:
                del self._by_id[old.tcode_id]
            self._by_name[name] = new_def
            if new_def.tcode_id and new_def.enabled:
                self._by_id[new_def.tcode_id] = new_def

    def get_by_id(self, tcode_id: str) -> Optional[AxisDef]:
        return self._by_id.get(tcode_id)

    def get_by_name(self, name: str) -> Optional[AxisDef]:
        return self._by_name.get(name)

    def all_enabled(self) -> list[AxisDef]:
        return [a for a in self._by_id.values() if a.enabled]

    def all(self) -> list[AxisDef]:
        return list(self._by_name.values())

    def volume_axis(self) -> Optional[AxisDef]:
        """Return volume_ext if configured, else V0."""
        ext = self._by_name.get("volume_ext")
        if ext and ext.tcode_id and ext.enabled:
            return ext
        return self._by_name.get("volume")
