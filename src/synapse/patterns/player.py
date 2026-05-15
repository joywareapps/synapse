from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from synapse.patterns.models import Pattern, evaluate_pattern

logger = logging.getLogger(__name__)

MAX_SEQUENCE_DEPTH = 16


class PatternPlayer:
    """
    Holds the current pattern and evaluates it each tick.
    Pattern switches use duck-and-switch transition.
    All pattern references are copy-on-write (immutable during evaluation).
    """

    def __init__(
        self,
        duck_amount: float = 1.0,
        duck_ms: int = 200,
        ramp_ms: int = 400,
    ) -> None:
        self._duck_amount = duck_amount
        self._duck_ms = duck_ms
        self._ramp_ms = ramp_ms

        self._pattern: Optional[Pattern] = None
        self._start_time: float = 0.0
        self._playing: bool = False
        self._lock = asyncio.Lock()

        # Volume override for duck-and-switch (None = not active)
        self._volume_override: Optional[float] = None

        # Sequence state
        self._seq_step_index: int = 0
        self._seq_step_start: float = 0.0
        self._seq_repeat_count: int = 0

        # Track ongoing transition task
        self._transition_task: Optional[asyncio.Task] = None

    def _cancel_transition(self) -> None:
        if self._transition_task and not self._transition_task.done():
            self._transition_task.cancel()
            self._transition_task = None

    async def play(
        self,
        pattern: Pattern,
        duck_amount: Optional[float] = None,
        duck_ms: Optional[int] = None,
        ramp_ms: Optional[int] = None,
        store: Optional[object] = None,
    ) -> None:
        da = duck_amount if duck_amount is not None else self._duck_amount
        dm = duck_ms if duck_ms is not None else self._duck_ms
        rm = ramp_ms if ramp_ms is not None else self._ramp_ms

        self._cancel_transition()
        self._transition_task = asyncio.create_task(
            self._transition(pattern, da, dm, rm)
        )

    async def _transition(
        self,
        new_pattern: Pattern,
        duck_amount: float,
        duck_ms: int,
        ramp_ms: int,
    ) -> None:
        try:
            # Duck phase
            if duck_ms > 0 and duck_amount > 0:
                current_vol = self._volume_override if self._volume_override is not None else 1.0
                target_vol = current_vol * (1.0 - duck_amount)
                await self._ramp_volume(current_vol, target_vol, duck_ms)

            # Atomic swap
            async with self._lock:
                self._pattern = new_pattern
                self._start_time = time.monotonic()
                self._playing = True
                self._seq_step_index = 0
                self._seq_step_start = self._start_time
                self._seq_repeat_count = 0

            # Ramp up
            if ramp_ms > 0:
                await self._ramp_volume(
                    self._volume_override if self._volume_override is not None else 0.0,
                    1.0,
                    ramp_ms,
                )
            self._volume_override = None
        except asyncio.CancelledError:
            pass

    async def stop(self, duck_ms: Optional[int] = None) -> None:
        dm = duck_ms if duck_ms is not None else self._duck_ms
        self._cancel_transition()
        self._transition_task = asyncio.create_task(self._stop_transition(dm))

    async def _stop_transition(self, duck_ms: int) -> None:
        try:
            current_vol = self._volume_override if self._volume_override is not None else 1.0
            if duck_ms > 0:
                await self._ramp_volume(current_vol, 0.0, duck_ms)
            async with self._lock:
                self._pattern = None
                self._playing = False
                self._volume_override = None
        except asyncio.CancelledError:
            pass

    async def _ramp_volume(self, from_vol: float, to_vol: float, duration_ms: int) -> None:
        steps = max(1, duration_ms // 20)
        dt = (duration_ms / 1000.0) / steps
        for i in range(steps + 1):
            self._volume_override = from_vol + (to_vol - from_vol) * (i / steps)
            if i < steps:
                await asyncio.sleep(dt)

    def evaluate(self, t: Optional[float] = None) -> dict[str, float]:
        """Return axis → normalized value for the current tick."""
        if not self._playing or self._pattern is None:
            return {}

        now = time.monotonic()
        if t is None:
            t = now - self._start_time

        pattern = self._pattern  # read ref atomically

        if pattern.is_sequence():
            return self._evaluate_sequence(pattern, now)
        else:
            result = self._evaluate_leaf(pattern, t)

        # Apply volume override from duck-and-switch
        if self._volume_override is not None:
            for vol_id in ("V0", "volume"):
                if vol_id in result:
                    result[vol_id] = result[vol_id] * self._volume_override
                    break

        return result

    def _evaluate_leaf(self, pattern: Pattern, t: float) -> dict[str, float]:
        # Check if duration exceeded (non-zero duration = auto-stop)
        if pattern.duration > 0 and t >= pattern.duration:
            self._playing = False
            return {}
        return evaluate_pattern(pattern, t)

    def _evaluate_sequence(self, pattern: Pattern, now: float) -> dict[str, float]:
        if not pattern.steps:
            return {}

        step = pattern.steps[self._seq_step_index]
        elapsed = now - self._seq_step_start
        step_duration = step.duration

        # Determine if we should advance to the next step
        if step_duration is not None and elapsed >= step_duration:
            self._seq_repeat_count += 1
            if step.repeat == 0 or self._seq_repeat_count < step.repeat:
                # Repeat this step
                self._seq_step_start = now
                elapsed = 0.0
            else:
                # Advance
                self._seq_repeat_count = 0
                next_index = self._seq_step_index + 1
                if next_index >= len(pattern.steps):
                    if pattern.loop:
                        next_index = 0
                    else:
                        self._playing = False
                        return {}
                self._seq_step_index = next_index
                self._seq_step_start = now
                step = pattern.steps[self._seq_step_index]
                elapsed = 0.0

        # We don't have a store reference here, so we can only return empty for sequence
        # The engine will handle store lookups
        return {}

    def current_pattern(self) -> Optional[Pattern]:
        return self._pattern

    def is_playing(self) -> bool:
        return self._playing

    def get_volume_override(self) -> Optional[float]:
        return self._volume_override


def detect_circular(
    name: str,
    store_get,
    depth: int = 0,
    visited: Optional[set] = None,
) -> bool:
    """Returns True if circular reference detected."""
    if visited is None:
        visited = set()
    if depth > MAX_SEQUENCE_DEPTH:
        return True
    if name in visited:
        return True
    visited = visited | {name}
    pattern = store_get(name)
    if pattern is None:
        return False
    for step in pattern.steps:
        if detect_circular(step.pattern, store_get, depth + 1, visited):
            return True
    return False
