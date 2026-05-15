from __future__ import annotations

import math
import pytest

from synapse.patterns.models import (
    AxisOscillator,
    Layer,
    Pattern,
    SequenceStep,
    eval_waveform,
    eval_envelope,
    evaluate_pattern,
)


class TestWaveforms:
    def test_sine_zero_phase(self):
        assert eval_waveform("sine", 0.0) == pytest.approx(0.0, abs=1e-9)

    def test_sine_quarter_phase(self):
        assert eval_waveform("sine", 0.25) == pytest.approx(1.0, abs=1e-6)

    def test_sine_half_phase(self):
        assert eval_waveform("sine", 0.5) == pytest.approx(0.0, abs=1e-9)

    def test_sine_three_quarter(self):
        assert eval_waveform("sine", 0.75) == pytest.approx(-1.0, abs=1e-6)

    def test_triangle_zero(self):
        assert eval_waveform("triangle", 0.0) == pytest.approx(0.0, abs=1e-6)

    def test_triangle_peak(self):
        assert eval_waveform("triangle", 0.25) == pytest.approx(1.0, abs=1e-6)

    def test_triangle_zero_half(self):
        assert eval_waveform("triangle", 0.5) == pytest.approx(0.0, abs=1e-6)

    def test_triangle_trough(self):
        assert eval_waveform("triangle", 0.75) == pytest.approx(-1.0, abs=1e-6)

    def test_sawtooth_zero(self):
        assert eval_waveform("sawtooth", 0.0) == pytest.approx(-1.0, abs=1e-6)

    def test_sawtooth_half(self):
        assert eval_waveform("sawtooth", 0.5) == pytest.approx(0.0, abs=1e-6)

    def test_sawtooth_almost_one(self):
        assert eval_waveform("sawtooth", 0.9999) == pytest.approx(0.9998, abs=1e-3)

    def test_square_low(self):
        assert eval_waveform("square", 0.0) == 1.0

    def test_square_high(self):
        assert eval_waveform("square", 0.5) == -1.0

    def test_hold_always_one(self):
        for p in [0.0, 0.25, 0.5, 0.75, 0.99]:
            assert eval_waveform("hold", p) == 1.0

    def test_phase_wraps(self):
        # Phase > 1.0 wraps around
        assert eval_waveform("sine", 1.25) == pytest.approx(eval_waveform("sine", 0.25), abs=1e-9)


class TestEnvelope:
    def test_no_envelope_always_one(self):
        osc = AxisOscillator(attack=0.0, sustain=0.0, release=0.0)
        assert eval_envelope(osc, 0.0) == 1.0
        assert eval_envelope(osc, 10.0) == 1.0

    def test_attack_ramps_up(self):
        osc = AxisOscillator(attack=1.0, sustain=0.0, release=0.0)
        assert eval_envelope(osc, 0.0) == pytest.approx(0.0)
        assert eval_envelope(osc, 0.5) == pytest.approx(0.5)
        assert eval_envelope(osc, 1.0) == pytest.approx(1.0)

    def test_sustain_holds(self):
        osc = AxisOscillator(attack=0.0, sustain=2.0, release=0.0)
        assert eval_envelope(osc, 0.0) == pytest.approx(1.0)
        assert eval_envelope(osc, 1.0) == pytest.approx(1.0)
        assert eval_envelope(osc, 1.999) == pytest.approx(1.0)

    def test_release_ramps_down(self):
        osc = AxisOscillator(attack=0.0, sustain=0.0, release=1.0)
        assert eval_envelope(osc, 0.0) == pytest.approx(1.0)
        assert eval_envelope(osc, 0.5) == pytest.approx(0.5)
        assert eval_envelope(osc, 1.0) == pytest.approx(0.0)

    def test_after_release_is_zero(self):
        osc = AxisOscillator(attack=0.0, sustain=0.0, release=1.0)
        assert eval_envelope(osc, 2.0) == pytest.approx(0.0)

    def test_full_adsr(self):
        osc = AxisOscillator(attack=1.0, sustain=2.0, release=1.0)
        assert eval_envelope(osc, 0.5) == pytest.approx(0.5)   # attack
        assert eval_envelope(osc, 1.0) == pytest.approx(1.0)   # end of attack
        assert eval_envelope(osc, 2.0) == pytest.approx(1.0)   # sustain
        assert eval_envelope(osc, 3.5) == pytest.approx(0.5)   # release midpoint
        assert eval_envelope(osc, 4.0) == pytest.approx(0.0)   # end of release


class TestBlendModes:
    def _set_layer(self, center=0.5, amplitude=0.5, waveform="hold") -> Layer:
        return Layer(
            name="base",
            blend="set",
            axes={"V0": AxisOscillator(waveform=waveform, amplitude=amplitude, center=center)},
        )

    def _add_layer(self, amplitude=0.2, waveform="hold") -> Layer:
        return Layer(
            name="addl",
            blend="add",
            axes={"V0": AxisOscillator(waveform=waveform, amplitude=amplitude)},
        )

    def _mul_layer(self, amplitude=0.5, waveform="hold") -> Layer:
        return Layer(
            name="mull",
            blend="mul",
            axes={"V0": AxisOscillator(waveform=waveform, amplitude=amplitude)},
        )

    def test_set_blend_hold(self):
        """set layer with hold waveform: center + amplitude * 1.0"""
        pattern = Pattern(name="test", layers=[self._set_layer(center=0.5, amplitude=0.2)])
        result = evaluate_pattern(pattern, t=0.0)
        # hold returns 1.0, no envelope → sample=1.0
        # accumulated = center + amplitude * 1.0 = 0.5 + 0.2 = 0.7
        assert result["V0"] == pytest.approx(0.7)

    def test_set_blend_center_only(self):
        """set layer with zero amplitude: just center"""
        pattern = Pattern(name="test", layers=[self._set_layer(center=0.4, amplitude=0.0)])
        result = evaluate_pattern(pattern, t=0.0)
        assert result["V0"] == pytest.approx(0.4)

    def test_add_blend_adds_delta(self):
        """add layer contributes delta on top of set layer"""
        base = self._set_layer(center=0.5, amplitude=0.0)
        add = self._add_layer(amplitude=0.2)
        pattern = Pattern(name="test", layers=[base, add])
        result = evaluate_pattern(pattern, t=0.0)
        # base: 0.5 + 0 = 0.5; add: 0.5 + 0.2 * 1.0 = 0.7
        assert result["V0"] == pytest.approx(0.7)

    def test_mul_blend_modulates(self):
        """mul layer scales the accumulated value"""
        base = self._set_layer(center=0.5, amplitude=0.0)
        mul = self._mul_layer(amplitude=0.5)
        pattern = Pattern(name="test", layers=[base, mul])
        result = evaluate_pattern(pattern, t=0.0)
        # base: 0.5; mul: 0.5 * (1 + 0.5 * 1.0) = 0.5 * 1.5 = 0.75
        assert result["V0"] == pytest.approx(0.75)

    def test_clamp_at_one(self):
        """Values exceeding 1.0 are clamped"""
        base = self._set_layer(center=0.8, amplitude=0.5)
        pattern = Pattern(name="test", layers=[base])
        result = evaluate_pattern(pattern, t=0.0)
        # 0.8 + 0.5 * 1.0 = 1.3 → clamped to 1.0
        assert result["V0"] == pytest.approx(1.0)

    def test_clamp_at_zero(self):
        """Values below 0.0 are clamped"""
        base = self._set_layer(center=0.1, amplitude=0.5)
        # center + amplitude * hold(1.0) = 0.1 + 0.5 = 0.6 (no clamp needed here)
        # Use sawtooth at phase=0 to get -1
        layer = Layer(
            name="base",
            blend="set",
            axes={"V0": AxisOscillator(waveform="sawtooth", amplitude=0.5, center=0.1, frequency=1.0)},
        )
        pattern = Pattern(name="test", layers=[layer])
        # At t=0, phase=0, sawtooth=-1 → 0.1 + 0.5*(-1) = -0.4 → clamped to 0.0
        result = evaluate_pattern(pattern, t=0.0)
        assert result["V0"] == pytest.approx(0.0)

    def test_static_axes_initialise_accumulator(self):
        """static_axes seed the accumulator before layers"""
        pattern = Pattern(
            name="test",
            static_axes={"C0": 0.8},
            layers=[],
        )
        result = evaluate_pattern(pattern, t=0.0)
        assert result["C0"] == pytest.approx(0.8)

    def test_multiple_axes_independent(self):
        """Different axes don't interfere"""
        layer = Layer(
            name="multi",
            blend="set",
            axes={
                "L0": AxisOscillator(waveform="hold", amplitude=0.0, center=0.3),
                "L1": AxisOscillator(waveform="hold", amplitude=0.0, center=0.7),
            },
        )
        pattern = Pattern(name="test", layers=[layer])
        result = evaluate_pattern(pattern, t=0.0)
        assert result["L0"] == pytest.approx(0.3)
        assert result["L1"] == pytest.approx(0.7)

    def test_freq_multiple_uses_base_period(self):
        """freq_multiple / base_period gives frequency"""
        layer = Layer(
            name="base",
            blend="set",
            axes={
                "L0": AxisOscillator(
                    waveform="sine",
                    freq_multiple=1.0,
                    amplitude=1.0,
                    center=0.5,
                )
            },
        )
        pattern = Pattern(name="test", base_period=2.0, layers=[layer])
        # freq = 1.0 / 2.0 = 0.5 Hz → at t=0.5s, phase = 0.5*0.5 = 0.25 → sin(2π*0.25) = 1.0
        result = evaluate_pattern(pattern, t=0.5)
        assert result["L0"] == pytest.approx(1.0, abs=1e-4)  # clamped at 1.0


class TestPatternValidation:
    def test_valid_leaf_pattern(self):
        p = Pattern(
            name="valid",
            layers=[
                Layer(name="l1", blend="set", axes={
                    "L0": AxisOscillator(waveform="sine", frequency=1.0)
                })
            ],
        )
        p.validate()  # Should not raise

    def test_valid_sequence_pattern(self):
        p = Pattern(
            name="seq",
            steps=[SequenceStep(pattern="other", duration=10.0)],
        )
        p.validate()  # Should not raise

    def test_both_layers_and_steps_raises(self):
        p = Pattern(
            name="bad",
            layers=[Layer(name="l1", blend="set")],
            steps=[SequenceStep(pattern="other")],
        )
        with pytest.raises(ValueError, match="cannot have both"):
            p.validate()

    def test_duplicate_layer_names_raises(self):
        p = Pattern(
            name="bad",
            layers=[
                Layer(name="same", blend="set"),
                Layer(name="same", blend="add"),
            ],
        )
        with pytest.raises(ValueError, match="Duplicate layer name"):
            p.validate()

    def test_invalid_blend_raises(self):
        p = Pattern(
            name="bad",
            layers=[Layer(name="l1", blend="invalid")],
        )
        with pytest.raises(ValueError, match="Invalid blend mode"):
            p.validate()

    def test_frequency_and_freq_multiple_raises(self):
        p = Pattern(
            name="bad",
            layers=[
                Layer(
                    name="l1",
                    blend="set",
                    axes={
                        "L0": AxisOscillator(
                            waveform="sine",
                            frequency=1.0,
                            freq_multiple=2.0,
                        )
                    },
                )
            ],
        )
        with pytest.raises(ValueError, match="mutually exclusive"):
            p.validate()

    def test_invalid_waveform_raises(self):
        p = Pattern(
            name="bad",
            layers=[
                Layer(
                    name="l1",
                    blend="set",
                    axes={"L0": AxisOscillator(waveform="unknown")},
                )
            ],
        )
        with pytest.raises(ValueError, match="Unknown waveform"):
            p.validate()

    def test_empty_pattern_valid(self):
        p = Pattern(name="empty")
        p.validate()  # No layers, no steps — valid (empty leaf)
