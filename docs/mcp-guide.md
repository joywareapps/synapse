# Synapse MCP Operational Guide

This guide describes how to operate a Restim e-stim device through Synapse. Read it before using any tools.

## What you are controlling

Restim is an electrical stimulation device. It produces physical sensation through electrical current. The user has consented to this and is expecting you to control it. Your job is to create an engaging, comfortable, and gradually exploratory experience.

The device has several axes you can control:
- **V0 / volume** — main intensity (most important axis; treat it like a master volume)
- **V9 / volume_ext** — external master volume (preferred if configured; affects all Restim playback)
- **C0 / carrier_freq** — frequency of the carrier wave (higher = different character of sensation)
- **P0 / pulse_freq** — pulse rate (affects rhythm and texture)
- **L0 / alpha**, **L1 / beta** — spatial position axes (move sensation around)

## Safety rules — read first

**Never spike volume upward suddenly.** The device produces electrical stimulation. A sudden volume increase is uncomfortable and potentially harmful. All volume changes must be gradual. The system rate-limits volume ramps (default 10%/s) but you should still plan gradual changes.

**Use `set_volume` or `play_pattern`, not `set_axis` on V0 directly**, unless you know exactly what you're doing. The pattern system handles smooth transitions.

**When in doubt, reduce intensity.** If you are unsure whether something is working correctly, call `set_volume` with a lower value or `stop_pattern` rather than experimenting at high intensity.

**Use `emergency_stop` if anything seems wrong.** It immediately zeroes all axes and stops all patterns. Prefer this over any other action when you need to stop immediately.

**Start every session low.** Begin at volume 0.2–0.3 and ask the user before increasing further. Most users prefer to increase gradually rather than start high.

**Respect the transition system.** When switching patterns, the system automatically dips volume to zero and ramps back up. Do not set volume manually during a transition — wait for it to complete (~600ms default).

## Understanding the system

### Current state
Before doing anything, call `get_status` and `get_axes` to understand what is currently active.

### Patterns vs direct control
There are two ways to control axes:

1. **Patterns** (preferred) — named programs stored in the library. Play them with `play_pattern`. They handle oscillation, timing, and transitions automatically.
2. **Direct axis control** — `set_axis`, `set_volume`. Use for one-off adjustments, not for ongoing stimulation.

For any session longer than a few seconds, use patterns.

### Reading sensor data
Call `get_sensors` to see available inputs:
- **AS5311** position sensor — detects physical movement/engagement
- **Heart rate** — BPM indicates arousal/intensity response
- **Restim volume** — shows what the user has set in the Restim UI

Sensors are context for your decisions. A rising heart rate suggests the experience is engaging. A stationary AS5311 may mean the user is not as engaged.

## Typical session workflow

### Starting a session
1. `get_status` — verify Synapse is connected to the device
2. `get_sensors` — check what sensors are available
3. `get_axes` — understand current axis values and limits
4. `list_patterns` — see what patterns are in the library
5. `start_playback` — if Restim is not already playing
6. `set_volume` with value `0.2` — set a safe starting volume
7. `play_pattern` with a gentle introductory pattern

### Adjusting during a session
- Check sensors periodically to gauge response
- Increase volume gradually — never more than 0.1 at a time, wait a few seconds between increases
- Use `spike` for brief intensity moments — it adds a delta to current volume, not a new absolute value
- Switch patterns with `play_pattern` — the duck-and-switch transition handles the change smoothly

### Ending a session
1. `stop_pattern` — fade out the current pattern
2. Optionally `set_volume` to `0.0` to ensure device is quiet
3. `stop_playback` if appropriate

## Exploration workflow

Use this when the user wants to discover what they enjoy. The goal is systematic A/B comparison, not random changes.

### Step 1 — Establish a baseline
Play a simple, moderate pattern (e.g. `gentle-pulse`) at volume 0.3 for 60–90 seconds. This is your reference point.

### Step 2 — Vary one parameter at a time
Change only one thing between comparisons. Options:
- Different pattern (same volume)
- Different volume (same pattern, ±0.1)
- Different carrier frequency (`set_axis C0`) — try 600Hz vs 800Hz vs 1000Hz
- Different pulse frequency (`set_axis P0`) — try 30Hz vs 60Hz vs 80Hz

Ask the user after each change: "Does this feel better, worse, or about the same as the previous?"

### Step 3 — Track preferences
After each comparison, use `update_profile` to record what you learned:
```
update_profile({
  "liked_patterns": ["pattern-name"],
  "preferred_carrier_hz": 800,
  "preferred_pulse_hz": 60,
  "preferred_volume_range": [0.3, 0.6],
  "notes": "User prefers moderate pulse frequency, dislikes high carrier"
})
```

### Step 4 — Converge
Once you have 3–4 comparison data points, play what the profile suggests is optimal. Confirm with the user.

### Step 5 — Build a custom pattern if warranted
If the user has settled on specific parameters, use `create_pattern` + `add_layer` + `set_layer_axis` to build a pattern that matches those preferences, then save it for future sessions.

## A/B testing procedure

For a structured A/B test:
1. Play option A for 30–60 seconds (note: call `get_sensors` at the end for heart rate if available)
2. `stop_pattern` with default transition
3. Wait 5 seconds (the user needs a moment to reset)
4. Play option B for 30–60 seconds
5. Ask: "Which felt better — the first or the second?"
6. Record the result in the user profile

Keep A/B tests to single-variable changes. Do not change volume, pattern, AND frequency simultaneously between A and B.

## User profile

The user profile persists between sessions. It stores preferences, history, and notes. Always read it at session start:
```
get_profile
```

Update it whenever you learn something meaningful:
```
update_profile({
  "preferred_intensity": "moderate",
  "preferred_patterns": ["circular-motion", "escalating-pulse"],
  "session_count": 5,
  "notes": "Responds well to slower oscillation (base_period > 2s). Dislikes rapid pulse changes."
})
```

The profile is yours to manage as the LLM. Structure it however is most useful for future sessions. Think of it as persistent memory about this user's preferences.

## Pattern cheat sheet

| Pattern type | When to use |
|---|---|
| `hold` waveform, low amplitude | Constant gentle sensation — good for warming up |
| `sine` on V0, slow (base_period 3–5s) | Steady rhythmic pulse — most users find this comfortable |
| `triangle` on P0 | Escalating/de-escalating pulse texture |
| `sine` on L0+L1 with 90° offset | Circular spatial motion |
| `add` layer with `hold` + envelope | Spike — brief intensity burst over current pattern |
| Sequence pattern | Long programs that change automatically |

## Common mistakes to avoid

- Setting `amplitude: 1.0` on a `set` layer — this sweeps the full axis range every cycle, which can be extreme. Start with 0.2–0.3.
- Playing a sequence pattern and then also calling `set_axis` directly — the sequence will override your direct values on the next tick.
- Forgetting that `spike` intensity is a **delta** (added to current volume), not an absolute value. `spike(intensity=0.5)` at `volume=0.6` peaks at 1.0.
- Switching patterns rapidly — the duck-and-switch takes ~600ms. Wait for it to complete before the next switch.
