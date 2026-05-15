from __future__ import annotations

import pytest

from synapse.tcode import TCodeCommand, TCodeFormatter
from synapse.axes import AxisMap, AxisDef


class TestTCodeCommand:
    def test_format_no_interval(self):
        cmd = TCodeCommand("L0", 0.5)
        assert cmd.format_cmd() == "L05000"

    def test_format_with_interval(self):
        cmd = TCodeCommand("L0", 0.5, interval_ms=20)
        assert cmd.format_cmd() == "L05000I20"

    def test_format_zero(self):
        cmd = TCodeCommand("V0", 0.0)
        assert cmd.format_cmd() == "V00000"

    def test_format_max(self):
        # 0.9999 → 9999
        cmd = TCodeCommand("V0", 1.0)
        # Clamped to 0.9999 → 9999
        assert cmd.format_cmd() == "V09999"

    def test_clamp_above_one(self):
        cmd = TCodeCommand("L0", 1.5)
        assert cmd.format_cmd() == "L09999"

    def test_clamp_below_zero(self):
        cmd = TCodeCommand("L0", -0.5)
        assert cmd.format_cmd() == "L00000"

    def test_format_precision(self):
        # 0.1234 → 1234
        cmd = TCodeCommand("C0", 0.1234)
        assert cmd.format_cmd() == "C01234"

    def test_tcode_id_preserved(self):
        cmd = TCodeCommand("P3", 0.75, interval_ms=100)
        result = cmd.format_cmd()
        assert result.startswith("P3")
        assert "I100" in result


class TestTCodeFormatter:
    def _make_axis_map(self) -> AxisMap:
        axis_map = AxisMap()
        return axis_map

    def test_format_normalized_known_axis(self):
        axis_map = self._make_axis_map()
        formatter = TCodeFormatter(axis_map)
        result = formatter.format_normalized("L0", 0.5, interval_ms=20)
        assert result == "L05000I20"

    def test_format_normalized_clamp(self):
        axis_map = self._make_axis_map()
        formatter = TCodeFormatter(axis_map)
        result = formatter.format_normalized("V0", 1.0)
        assert result == "V09999"

    def test_format_normalized_zero(self):
        axis_map = self._make_axis_map()
        formatter = TCodeFormatter(axis_map)
        result = formatter.format_normalized("V0", 0.0)
        assert result == "V00000"

    def test_format_unknown_axis_returns_none(self):
        axis_map = self._make_axis_map()
        formatter = TCodeFormatter(axis_map)
        result = formatter.format_normalized("X9", 0.5)
        assert result is None

    def test_format_real_value_with_limits(self):
        axis_map = AxisMap()
        # carrier freq: 500-1000Hz, test value at midpoint
        formatter = TCodeFormatter(axis_map)
        # 750Hz in [500, 1000] → 0.5 → 5000
        result = formatter.format("C0", 750.0, interval_ms=20)
        assert result == "C05000I20"

    def test_value_mapping_formula(self):
        """tcode_value = (real - min) / (max - min)"""
        axis_map = AxisMap()
        # alpha: -1 to 1; 0.0 → (0 - (-1)) / (1 - (-1)) = 0.5
        formatter = TCodeFormatter(axis_map)
        result = formatter.format("L0", 0.0, interval_ms=0)
        assert result == "L05000"

    def test_disabled_axis_returns_none(self):
        axis_map = AxisMap()
        # volume_ext has no tcode_id by default, so get_by_id won't find it
        formatter = TCodeFormatter(axis_map)
        result = formatter.format_normalized("", 0.5)
        assert result is None
