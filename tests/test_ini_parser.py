from __future__ import annotations

import pytest

from synapse.ini_parser import parse_ini


SAMPLE_INI = """
[POSITION_ALPHA]
tcode_axis=L0
limit_min=-1.000000
limit_max=1.000000
funscript_names=alpha
auto_load=true

[POSITION_BETA]
tcode_axis=L1
limit_min=-1.000000
limit_max=1.000000

[VOLUME]
tcode_axis=V0
limit_min=0.000000
limit_max=1.000000

[VOLUME_EXTERNAL]
tcode_axis=
limit_min=0.000000
limit_max=1.000000

[CARRIER_FREQUENCY]
tcode_axis=C0
limit_min=500.000000
limit_max=1000.000000

[PULSE_FREQUENCY]
tcode_axis=P0
limit_min=0.000000
limit_max=100.000000
"""

MINIMAL_INI = """
[POSITION_ALPHA]
tcode_axis=L0
limit_min=0
limit_max=1
"""

MISSING_FIELDS_INI = """
[POSITION_ALPHA]
tcode_axis=L0
"""

DISABLED_AXIS_INI = """
[VOLUME_EXTERNAL]
tcode_axis=
limit_min=0.0
limit_max=1.0
"""


class TestParseIni:
    def test_parse_alpha(self):
        axes = parse_ini(SAMPLE_INI)
        assert "alpha" in axes
        a = axes["alpha"]
        assert a.tcode_id == "L0"
        assert a.limit_min == -1.0
        assert a.limit_max == 1.0
        assert a.enabled is True

    def test_parse_beta(self):
        axes = parse_ini(SAMPLE_INI)
        assert "beta" in axes
        assert axes["beta"].tcode_id == "L1"

    def test_parse_volume(self):
        axes = parse_ini(SAMPLE_INI)
        assert "volume" in axes
        v = axes["volume"]
        assert v.tcode_id == "V0"
        assert v.limit_min == 0.0
        assert v.limit_max == 1.0

    def test_volume_ext_disabled(self):
        axes = parse_ini(SAMPLE_INI)
        assert "volume_ext" in axes
        ve = axes["volume_ext"]
        assert ve.tcode_id == ""
        assert ve.enabled is False

    def test_carrier_frequency(self):
        axes = parse_ini(SAMPLE_INI)
        c = axes["carrier_freq"]
        assert c.tcode_id == "C0"
        assert c.limit_min == 500.0
        assert c.limit_max == 1000.0
        assert c.value_type == "frequency"

    def test_pulse_frequency(self):
        axes = parse_ini(SAMPLE_INI)
        p = axes["pulse_freq"]
        assert p.tcode_id == "P0"
        assert p.limit_max == 100.0

    def test_minimal_ini(self):
        axes = parse_ini(MINIMAL_INI)
        assert "alpha" in axes
        assert axes["alpha"].limit_min == 0.0
        assert axes["alpha"].limit_max == 1.0

    def test_missing_limits_defaults_to_zero_one(self):
        axes = parse_ini(MISSING_FIELDS_INI)
        a = axes["alpha"]
        assert a.limit_min == 0.0
        assert a.limit_max == 1.0

    def test_disabled_axis(self):
        axes = parse_ini(DISABLED_AXIS_INI)
        ve = axes["volume_ext"]
        assert ve.tcode_id == ""
        assert ve.enabled is False

    def test_empty_ini(self):
        axes = parse_ini("")
        assert axes == {}

    def test_unknown_sections_ignored(self):
        ini = """
[UNKNOWN_SECTION]
foo=bar

[POSITION_ALPHA]
tcode_axis=L0
limit_min=0
limit_max=1
"""
        axes = parse_ini(ini)
        assert "alpha" in axes
        assert len(axes) == 1

    def test_value_type_percentage_for_position(self):
        axes = parse_ini(SAMPLE_INI)
        assert axes["alpha"].value_type == "percentage"

    def test_value_type_frequency_for_carrier(self):
        axes = parse_ini(SAMPLE_INI)
        assert axes["carrier_freq"].value_type == "frequency"
