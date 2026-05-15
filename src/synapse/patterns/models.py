from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AxisOscillator:
    waveform: str = "sine"          # sine | triangle | sawtooth | square | hold
    frequency: Optional[float] = None
    freq_multiple: Optional[float] = None
    amplitude: float = 0.5
    center: float = 0.5
    offset: float = 0.0
    attack: float = 0.0
    sustain: float = 0.0
    release: float = 0.0


@dataclass
class Layer:
    name: str = ""
    blend: str = "set"              # set | add | mul
    axes: dict[str, AxisOscillator] = field(default_factory=dict)


@dataclass
class SequenceStep:
    pattern: str = ""
    duration: Optional[float] = None
    repeat: int = 1
    transition: Optional[dict] = None


@dataclass
class Pattern:
    name: str = ""
    description: str = ""
    base_period: float = 1.0
    duration: float = 0.0
    layers: list[Layer] = field(default_factory=list)
    static_axes: dict[str, float] = field(default_factory=dict)
    steps: list[SequenceStep] = field(default_factory=list)
    loop: bool = False

    def is_sequence(self) -> bool:
        return bool(self.steps)

    def is_leaf(self) -> bool:
        return not bool(self.steps)

    def validate(self) -> None:
        if self.layers and self.steps:
            raise ValueError(f"Pattern '{self.name}': cannot have both layers and steps")
        if not self.layers and not self.steps:
            # Empty pattern — allowed, it's just a leaf with no layers
            pass

        names_seen: set[str] = set()
        for layer in self.layers:
            if not layer.name:
                raise ValueError("Layer has empty name")
            if layer.name in names_seen:
                raise ValueError(f"Duplicate layer name '{layer.name}' in pattern '{self.name}'")
            names_seen.add(layer.name)
            if layer.blend not in ("set", "add", "mul"):
                raise ValueError(f"Invalid blend mode '{layer.blend}'")
            for tcode_id, osc in layer.axes.items():
                if osc.frequency is not None and osc.freq_multiple is not None:
                    raise ValueError(
                        f"Axis '{tcode_id}' in layer '{layer.name}': "
                        "frequency and freq_multiple are mutually exclusive"
                    )
                if osc.waveform not in ("sine", "triangle", "sawtooth", "square", "hold"):
                    raise ValueError(f"Unknown waveform '{osc.waveform}'")


def _auto_name_layers(layers: list[Layer]) -> None:
    used: set[str] = {l.name for l in layers if l.name}
    counter = 1
    for layer in layers:
        if not layer.name:
            while f"layer-{counter}" in used:
                counter += 1
            layer.name = f"layer-{counter}"
            used.add(layer.name)
            counter += 1


def eval_waveform(waveform: str, phase: float) -> float:
    """Evaluate waveform at phase (0–1), returns [-1, +1]."""
    p = phase % 1.0
    if waveform == "sine":
        return math.sin(2.0 * math.pi * p)
    elif waveform == "triangle":
        if p < 0.25:
            return 4.0 * p
        elif p < 0.75:
            return 2.0 - 4.0 * p
        else:
            return 4.0 * p - 4.0
    elif waveform == "sawtooth":
        return 2.0 * p - 1.0
    elif waveform == "square":
        return 1.0 if p < 0.5 else -1.0
    elif waveform == "hold":
        return 1.0
    return 0.0


def eval_envelope(osc: AxisOscillator, t: float) -> float:
    """Evaluate ADSR envelope at time t (seconds since start). Returns [0, 1]."""
    attack = osc.attack
    sustain_dur = osc.sustain
    release = osc.release

    if attack > 0 and t < attack:
        return t / attack
    t_after_attack = t - attack
    if sustain_dur > 0 and t_after_attack < sustain_dur:
        return 1.0
    if sustain_dur == 0 and attack > 0 and t_after_attack == 0:
        return 1.0

    t_after_sustain = t_after_attack - sustain_dur
    if release > 0:
        if t_after_sustain < release:
            return 1.0 - (t_after_sustain / release)
        return 0.0
    return 1.0


def evaluate_pattern(
    pattern: Pattern,
    t: float,
    base_period: Optional[float] = None,
) -> dict[str, float]:
    """
    Evaluate all layers of a leaf pattern at time t.
    Returns axis_id → normalized value [0, 1].
    """
    bp = base_period if base_period is not None else pattern.base_period

    accumulated: dict[str, float] = dict(pattern.static_axes)

    for layer in pattern.layers:
        for tcode_id, osc in layer.axes.items():
            # Determine frequency
            if osc.frequency is not None:
                freq = osc.frequency
            elif osc.freq_multiple is not None and bp > 0:
                freq = osc.freq_multiple / bp
            else:
                freq = 0.0

            phase = (t * freq + osc.offset) % 1.0
            sample = eval_waveform(osc.waveform, phase) * eval_envelope(osc, t)

            prev = accumulated.get(tcode_id, 0.0)
            if layer.blend == "set":
                accumulated[tcode_id] = osc.center + osc.amplitude * sample
            elif layer.blend == "add":
                accumulated[tcode_id] = prev + osc.amplitude * sample
            elif layer.blend == "mul":
                accumulated[tcode_id] = prev * (1.0 + osc.amplitude * sample)

    return {k: max(0.0, min(1.0, v)) for k, v in accumulated.items()}
