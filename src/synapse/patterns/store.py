from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

from synapse.patterns.models import AxisOscillator, Layer, Pattern, SequenceStep, _auto_name_layers

logger = logging.getLogger(__name__)


def _osc_to_dict(osc: AxisOscillator) -> dict:
    d: dict = {"waveform": osc.waveform}
    if osc.frequency is not None:
        d["frequency"] = osc.frequency
    if osc.freq_multiple is not None:
        d["freq_multiple"] = osc.freq_multiple
    d["amplitude"] = osc.amplitude
    d["center"] = osc.center
    if osc.offset != 0.0:
        d["offset"] = osc.offset
    if osc.attack != 0.0:
        d["attack"] = osc.attack
    if osc.sustain != 0.0:
        d["sustain"] = osc.sustain
    if osc.release != 0.0:
        d["release"] = osc.release
    return d


def _layer_to_dict(layer: Layer) -> dict:
    return {
        "name": layer.name,
        "blend": layer.blend,
        "axes": {tid: _osc_to_dict(osc) for tid, osc in layer.axes.items()},
    }


def _step_to_dict(step: SequenceStep) -> dict:
    d: dict = {"pattern": step.pattern}
    if step.duration is not None:
        d["duration"] = step.duration
    if step.repeat != 1:
        d["repeat"] = step.repeat
    if step.transition is not None:
        d["transition"] = step.transition
    return d


def pattern_to_dict(pattern: Pattern) -> dict:
    d: dict = {
        "name": pattern.name,
    }
    if pattern.description:
        d["description"] = pattern.description
    if pattern.is_leaf():
        if pattern.base_period != 1.0:
            d["base_period"] = pattern.base_period
        if pattern.duration != 0.0:
            d["duration"] = pattern.duration
        if pattern.static_axes:
            d["static_axes"] = pattern.static_axes
        d["layers"] = [_layer_to_dict(l) for l in pattern.layers]
    else:
        if pattern.loop:
            d["loop"] = pattern.loop
        d["steps"] = [_step_to_dict(s) for s in pattern.steps]
    return d


def _osc_from_dict(d: dict | float | int) -> AxisOscillator:
    # Support shorthand: just a float value means static (hold, amplitude=0, center=value)
    if isinstance(d, (int, float)):
        return AxisOscillator(waveform="hold", amplitude=0.0, center=float(d))
    return AxisOscillator(
        waveform=d.get("waveform", "sine"),
        frequency=d.get("frequency"),
        freq_multiple=d.get("freq_multiple"),
        amplitude=float(d.get("amplitude", 0.5)),
        center=float(d.get("center", 0.5)),
        offset=float(d.get("offset", 0.0)),
        attack=float(d.get("attack", 0.0)),
        sustain=float(d.get("sustain", 0.0)),
        release=float(d.get("release", 0.0)),
    )


def _layer_from_dict(d: dict) -> Layer:
    axes = {tid: _osc_from_dict(v) for tid, v in d.get("axes", {}).items()}
    return Layer(
        name=d.get("name", ""),
        blend=d.get("blend", "set"),
        axes=axes,
    )


def _step_from_dict(d: dict) -> SequenceStep:
    return SequenceStep(
        pattern=d.get("pattern", ""),
        duration=d.get("duration"),
        repeat=int(d.get("repeat", 1)),
        transition=d.get("transition"),
    )


def pattern_from_dict(d: dict) -> Pattern:
    layers = [_layer_from_dict(l) for l in d.get("layers", [])]
    _auto_name_layers(layers)
    steps = [_step_from_dict(s) for s in d.get("steps", [])]
    return Pattern(
        name=d.get("name", ""),
        description=d.get("description", ""),
        base_period=float(d.get("base_period", 1.0)),
        duration=float(d.get("duration", 0.0)),
        layers=layers,
        static_axes={k: float(v) for k, v in d.get("static_axes", {}).items()},
        steps=steps,
        loop=bool(d.get("loop", False)),
    )


class PatternStore:
    def __init__(self, directory: str) -> None:
        self._dir = Path(directory)
        self._patterns: dict[str, Pattern] = {}

    def load_all(self) -> None:
        if not self._dir.exists():
            self._dir.mkdir(parents=True, exist_ok=True)
            return
        for yaml_file in self._dir.glob("*.yaml"):
            self._load_file(yaml_file)

    def _load_file(self, path: Path) -> None:
        try:
            content = path.read_text()
            docs = list(yaml.safe_load_all(content))
            for doc in docs:
                if not doc or not isinstance(doc, dict):
                    continue
                pattern = pattern_from_dict(doc)
                if not pattern.name:
                    pattern.name = path.stem
                try:
                    pattern.validate()
                    self._patterns[pattern.name] = pattern
                except ValueError as e:
                    logger.warning("Invalid pattern in %s: %s", path, e)
        except Exception as e:
            logger.error("Failed to load pattern file %s: %s", path, e)

    def list(self) -> list[str]:
        return sorted(self._patterns.keys())

    def get(self, name: str) -> Optional[Pattern]:
        return self._patterns.get(name)

    def save(self, pattern: Pattern) -> None:
        pattern.validate()
        _auto_name_layers(pattern.layers)
        self._patterns[pattern.name] = pattern
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{pattern.name}.yaml"
        data = pattern_to_dict(pattern)
        with open(path, "w") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)

    def delete(self, name: str) -> bool:
        if name not in self._patterns:
            return False
        del self._patterns[name]
        path = self._dir / f"{name}.yaml"
        if path.exists():
            path.unlink()
        return True

    def exists(self, name: str) -> bool:
        return name in self._patterns
