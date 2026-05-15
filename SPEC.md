# Synapse — Specification v0.1

> A service that bridges Restim devices to MCP (LLM control), REST APIs, and a web UI —
> driving TCode axes, reading device state, and composing reusable patterns.

## 1. Overview

Synapse replaces the existing C# Restim-Controller with a Python service that:

1. **Drives Restim** via TCode over TCP (position, volume, frequency, pulse, vibration, electrode axes)
2. **Reads Restim state** via its REST API (`/v1/status`, `/v1/actions/*`)
3. **Exposes MCP tools** so LLMs can control devices conversationally
4. **Provides a REST API** for programmatic control
5. **Parses Restim INI** to discover axis limits for correct value mapping
6. **Composes and plays patterns** — layered oscillators with shared timing parameters

## 2. Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│   Web UI    │────▶│  REST API    │     │  MCP Server     │
│  (browser)  │◀────│  (FastAPI)   │     │  (SSE/stdio)    │
└─────────────┘     └──────┬───────┘     └────────┬────────┘
                           │                      │
                    ┌──────▼──────────────────────▼──────┐
                    │         Synapse Core               │
                    │                                    │
                    │  ┌──────────┐  ┌────────────────┐  │
                    │  │ Engine   │  │  Pattern Store │  │
                    │  │ (tcode   │  │  (save/load/   │  │
                    │  │  loop @  │  │   play/layer)  │  │
                    │  │  50Hz)   │  │                │  │
                    │  └────┬─────┘  └────────────────┘  │
                    │       │                            │
                    │  ┌────▼────────────────────────┐   │
                    │  │  Axis Map (from restim.ini)  │   │
                    │  │  tcode_id ↔ limit_min/max    │   │
                    │  └──────────────────────────────┘   │
                    └──────────┬──────────┬───────────────┘
                               │          │
                    ┌──────────▼──┐  ┌───▼──────────┐
                    │ TCode TCP   │  │ Restim HTTP   │
                    │ (outgoing)  │  │ (status/cmd)  │
                    │ :12347      │  │ :12348        │
                    └─────────────┘  └──────────────┘
```

## 3. Axis System

### 3.1 Axis Definitions

Every axis has:
- **tcode_id**: TCode identifier string (e.g. `L0`, `V0`, `C0`, `P0`)
- **name**: Human-readable name (e.g. "alpha", "volume", "carrier frequency")
- **limit_min**, **limit_max**: Physical range from restim.ini
- **value_type**: How the value is interpreted
  - `linear` — direct value mapping (TCode 0–1 → limit_min–limit_max)
  - `percentage` — value stored as 0.0–1.0, mapped to limit_min–limit_max on output
  - `frequency` — value in Hz, mapped to limit_min–limit_max on output

### 3.2 Known Axes (from Restim source)

All TCode IDs are read from `restim.ini` — the values below are Restim's built-in defaults, but users can reassign any axis to any TCode identifier in the Restim device wizard. Synapse always uses whatever the INI says; the table is documentation, not hardcoded mappings.

| Default TCode ID | Name | Type | Default Limits | Description |
|------------------|------|------|----------------|-------------|
| L0 | alpha | percentage | -1, 1 | Linear position axis |
| L1 | beta | percentage | -1, 1 | Linear position axis |
| V0 | volume | percentage | 0, 1 | Main volume (Synapse-controlled patterns only) |
| *(not set)* | volume_ext | percentage | 0, 1 | External volume — **preferred for volume control** (see note) |
| C0 | carrier_freq | frequency | 500, 1000 | Carrier frequency Hz |
| P0 | pulse_freq | frequency | 0, 100 | Pulse frequency Hz |
| P1 | pulse_width | linear | 4, 10 | Pulse width in cycles |
| P2 | pulse_random | percentage | 0, 1 | Pulse interval randomization |
| P3 | pulse_rise | frequency | 2, 20 | Pulse rise time in cycles |
| *(TBD)* | e1–e4 | percentage | 0, 1 | Individual electrode intensities — default TCode IDs pending confirmation from Restim developer |

> **Note**: V1–V8 (vibration axes) and L2 (gamma) are deprecated and not supported.

> **External volume (volume_ext)**: This axis acts as a master volume override in Restim — it applies even when Synapse is not playing a pattern, so the user can use Restim's own playback while Synapse still controls intensity. It has no TCode ID assigned by default; the user must configure it in Restim's device wizard (Settings → TCode axes → VOLUME_EXTERNAL). **Synapse should warn on startup if `volume_ext` has no TCode ID configured**, and fall back to `V0` (volume) in that case. When `volume_ext` is available, Synapse uses it for all volume control; `V0` is only used as fallback.

### 3.3 Restim INI Parsing

Restim stores per-axis settings in INI format under groups like `[POSITION_ALPHA]`, `[CARRIER_FREQUENCY]`, etc.
Synapse reads the INI to discover:

```ini
[POSITION_ALPHA]
tcode_axis=L0
limit_min=-1.000000
limit_max=1.000000
funscript_names=alpha
auto_load=true
allow_funscript_control=true
```

**Sources** (either or both can be used):
1. **File path** — configurable in `synapse.yaml` (`restim.ini_path`). If set, INI is parsed on startup and watched for changes (auto-reload)
2. **Upload** — REST API endpoint to upload a `.ini` file for one-time parsing (no persistent storage needed)

If no INI is available, axes fall back to hardcoded defaults (limit_min=0, limit_max=1 for percentage axes, or known defaults from Restim source).

Parsing logic:
1. For each known axis group, read `tcode_axis`, `limit_min`, `limit_max`
2. Build axis map: `tcode_id → {name, limit_min, limit_max, value_type}`
3. Axes with empty `tcode_axis` are disabled (no TCode output)
4. If file path is set, watch for changes and auto-reload

### 3.4 Value Mapping

TCode protocol uses 0.000–0.999 (3–4 digit integer, i.e. `L0000`–`L09999`).
Synapse internally stores values as **real-world units** (Hz, cycles, etc.) or **percentage 0.0–1.0**.
On output, it maps to TCode range:

```
tcode_value = (real_value - limit_min) / (limit_max - limit_min)
tcode_value = clamp(tcode_value, 0.0, 0.9999)
```

For display in UI/API, show real-world values with units.

## 4. TCode Engine

### 4.1 Command Loop

- Configurable update rate, default **50 Hz** (20ms interval)
- Connects to Restim TCP server (default `localhost:12347`)
- Reconnects automatically on disconnect
- For each tick:
  1. Evaluate all active oscillators on their axes
  2. Apply pattern layers (see §5)
  3. Build TCode command string for each changed axis
  4. Send as single TCP message (newline-delimited)

### 4.2 Command Format

TCode uses ASCII format per restim's parser:
- **Without interval**: `{ID}{VALUE:03d}` → e.g. `L0500` = L0 at 0.500
- **With interval**: `{ID}{VALUE:04d}I{INTERVAL}` → e.g. `L05000I20` = ramp to 0.500 over 20ms
- 3-digit value: `value = int / 10^len` (e.g. 500 → 0.500)
- 4-digit value: `value = int / 10^len` (e.g. 5000 → 0.5000)

Synapse should use 4-digit precision for smooth interpolation.

### 4.3 Connection Management

- Maintain persistent TCP connection
- Heartbeat: if no send for >2s, send a keepalive (re-send current state for one axis)
- On disconnect: exponential backoff retry (1s, 2s, 4s, max 30s)
- Multiple Restim instances supported (configurable list)

## 5. Pattern System

### 5.1 Design Goals

- **Composable**: Patterns are built from layers that can be combined
- **Orchestrated**: Sequences chain patterns into timed, looping programs
- **Memorizable**: Save and load patterns by name
- **Real-time**: Switch patterns without interrupting output
- **LLM-friendly**: MCP tools to create, modify, and play patterns

### 5.2 Data Model

A **Pattern** is either a **leaf** (has `layers` — oscillator-based) or a **sequence** (has `steps` — references other patterns). These are mutually exclusive; a pattern cannot have both. Both types live in the same library and are played with the same `play_pattern` command.

A **Leaf Pattern** contains an ordered list of **Layers**. Each **Layer** has a blend mode and a dict of **AxisOscillators** (one per axis). The blend mode applies to all axes in that layer.

```python
@dataclass
class AxisOscillator:
    waveform: str           # "sine" | "triangle" | "sawtooth" | "square" | "hold"
                            # "hold" outputs a constant signal (no oscillation);
                            # useful for static layers and spike envelopes

    # Frequency: exactly one must be set, not both
    frequency: Optional[float] = None      # absolute Hz
    freq_multiple: Optional[float] = None  # relative to pattern's base_period

    amplitude: float = 0.5  # "set" layer: deviation from center (fraction of axis range)
                             # "add" layer: delta contributed at peak
                             # "mul" layer: modulation depth around 1.0×
    center: float = 0.5     # "set" layer only: resting position in axis range (0.5 = middle)
                             # ignored in "add" and "mul" layers
    offset: float = 0.0     # phase offset as fraction of cycle (0.25 = 90°)

    # Optional envelope
    attack: float = 0.0     # seconds to reach full amplitude
    sustain: float = 0.0    # seconds to hold at full amplitude (0 = infinite)
    release: float = 0.0    # seconds to fade to zero


@dataclass
class Layer:
    name: str               # unique within the pattern; auto-assigned if not provided
    blend: str = "set"      # "set" | "add" | "mul" — see §5.3 for semantics
    axes: dict[str, AxisOscillator] = field(default_factory=dict)  # tcode_id → oscillator
```

**Shared Timing** — a pattern can define a `base_period` (in seconds):
- Any oscillator with `freq_multiple` set uses `1/base_period * freq_multiple` as its frequency
- This keeps rhythmic relationships intact when changing tempo

### 5.3 Pattern Composition

```python
@dataclass
class SequenceStep:
    pattern: str                        # name of a pattern in the library
    duration: Optional[float] = None    # override the pattern's own duration for this step;
                                        # None = use the pattern's duration (must be finite)
    repeat: int = 1                     # times to loop this step before advancing (0 = loop forever)
    transition: Optional[dict] = None   # per-step transition override (duck_amount, duck_ms, ramp_ms)


@dataclass
class Pattern:
    name: str
    description: str = ""

    # --- Leaf pattern (oscillator-based) ---
    base_period: float = 1.0            # seconds, for shared timing
    duration: float = 0.0              # 0 = infinite loop
    layers: list[Layer] = field(default_factory=list)
    static_axes: dict[str, float] = field(default_factory=dict)  # YAML shorthand only; see §5.3 note

    # --- Sequence pattern ---
    steps: list[SequenceStep] = field(default_factory=list)
    loop: bool = False                  # if True, sequence restarts after the last step

    # Exactly one of (layers, steps) must be non-empty. Validated on load and save.
```

> **`static_axes` vs hold layers**: `static_axes` is YAML shorthand only — it exists for readability when several axes need fixed values. It is exactly equivalent to a `set` layer with `hold` oscillators and `amplitude: 0.0`. Via API or MCP, achieve the same by adding a `set` layer and calling `set_layer_axis` with `waveform: hold`. `static_axes` has no dedicated REST or MCP endpoints.

> **Sequence cycles**: The player detects and rejects circular step references at play time (e.g. A → B → A). Depth is limited to prevent accidental infinite nesting.

#### Layer Evaluation (blend mode semantics)

Layers are processed in order. Each layer contributes to the accumulated value for each of its axes:

```
# initialise from static_axes, default 0.0 for unset axes
accumulated: dict[str, float] = {**pattern.static_axes}

for layer in pattern.layers:
    for tcode_id, osc in layer.axes.items():
        sample = osc.waveform(phase) * osc.envelope(t)   # normalized [-1, +1]
        prev = accumulated.get(tcode_id, 0.0)
        if layer.blend == "set":
            accumulated[tcode_id] = osc.center + osc.amplitude * sample
        elif layer.blend == "add":
            accumulated[tcode_id] = prev + osc.amplitude * sample
        elif layer.blend == "mul":
            accumulated[tcode_id] = prev * (1.0 + osc.amplitude * sample)

final[tcode_id] = clamp(accumulated[tcode_id], 0.0, 1.0)
```

> **Implementation note**: Patterns must be treated as immutable during evaluation. Modifications via API create a new `Pattern` object and atomically replace the reference held by the player. This avoids locking without risking mid-tick mutations.

| Mode | Use for | `center` | `amplitude` |
|------|---------|----------|-------------|
| `set` | Base oscillators | Resting position (0–1) | Deviation from center |
| `add` | Spikes, intensity boosts | — (ignored) | Delta added at peak |
| `mul` | Tremolo, AM modulation | — (implicitly 1.0×) | Modulation depth |

### 5.4 Pattern File Format (YAML)

Each layer has a `name` (optional, auto-assigned if omitted), a `blend` mode, and an `axes` map of `tcode_id → oscillator params`.

```yaml
name: "Circular Motion"
description: "Alpha and beta move in a circle"
base_period: 0.5
duration: 0  # infinite
static_axes:
  C0: 1000    # carrier frequency fixed at 1000 Hz
  P0: 80      # pulse frequency at 80 Hz
  P1: 3       # pulse width 3 cycles
layers:
  - name: "circle"
    blend: set
    axes:
      L0: { waveform: sine, freq_multiple: 1.0, amplitude: 0.8, center: 0.0, offset: 0.0 }
      L1: { waveform: sine, freq_multiple: 1.0, amplitude: 0.8, center: 0.0, offset: 0.25 }  # 90° shift

---
name: "Escalating Pulse"
description: "Pulse frequency ramps up and down"
base_period: 4.0
duration: 0
layers:
  - name: "base"
    blend: set
    axes:
      P0: { waveform: triangle, freq_multiple: 1.0, amplitude: 0.5, center: 0.5 }
      V0: { waveform: hold, amplitude: 0.0, center: 0.3 }

---
name: "Quick Spike"
description: "Brief intensity burst — layer add on top of whatever is playing"
duration: 2.0  # auto-stop after 2 seconds
layers:
  - name: "spike"
    blend: add
    axes:
      V0: { waveform: hold, amplitude: 0.4, attack: 0.05, sustain: 0.0, release: 0.3 }

---
name: "Rhythm with Tremolo"
description: "Rhythmic volume pulse with tremolo modulation"
base_period: 2.0
layers:
  - name: "rhythm"
    blend: set
    axes:
      V0: { waveform: sine, freq_multiple: 1.0, center: 0.5, amplitude: 0.2 }
      C0: { waveform: hold, center: 0.4, amplitude: 0.0 }
  - name: "tremolo"
    blend: mul
    axes:
      V0: { waveform: sine, amplitude: 0.15, frequency: 3.0 }

---
# Sequence pattern — references leaf patterns from the library by name
name: "buildup-program"
description: "Gentle warmup → escalating rhythm → intense burst, loops forever"
loop: true
steps:
  - pattern: "gentle-pulse"
    duration: 30.0            # play for 30s regardless of pattern's own duration
  - pattern: "escalating-pulse"
    duration: 20.0
    transition: { duck_ms: 300, ramp_ms: 600 }   # slower transition into this step
  - pattern: "rhythm-with-tremolo"
    duration: 15.0
    repeat: 2                 # play twice before advancing
  - pattern: "intense-burst"
    duration: 10.0
  - pattern: "cool-down"
    duration: 20.0
    transition: { duck_amount: 1.0, duck_ms: 800, ramp_ms: 1500 }  # long fade out/in
```

### 5.5 Pattern Operations

- **play(name)** — start a named pattern, blends from current state (over ~100ms)
- **stop()** — fade out current pattern to zero over release time
- **snapshot(name)** — capture current axis values as a new pattern (all `hold` layers)
- **save(name)** — save current pattern to YAML file
- **list()** — enumerate saved patterns
- **delete(name)** — remove saved pattern
- **layer_add(...)** — add an oscillator layer to current pattern
- **layer_remove(axis)** — remove a layer from current pattern
- **layer_modify(axis, ...)** — modify an existing layer parameter

### 5.6 Pattern Transitions

Pattern switches use a **duck-and-switch** transition to avoid abrupt changes during active stimulation:

1. **Duck**: ramp V0 down by `duck_amount` (fraction of current value) over `duck_ms`
2. **Switch**: at the volume minimum, atomically stop the old pattern and start the new one — all non-volume axes change at this instant
3. **Ramp**: ramp V0 from the ducked value up to the new pattern's target V0 over `ramp_ms`

```
current V0 ──┐
              └─── duck over duck_ms ───> switch ───> ramp to new V0 over ramp_ms
```

Transition parameters (configurable globally in `synapse.yaml`, overridable per `play` call):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `duck_amount` | `1.0` | Fraction of current V0 to remove (1.0 = go to zero, 0.5 = halve) |
| `duck_ms` | `200` | Time to ramp volume down |
| `ramp_ms` | `400` | Time to ramp volume back up after switch |

If `duck_amount` is `1.0` (full duck to zero), the switch is imperceptible — the new pattern starts from silence. Lower values create a brief dip rather than a full silence gap.

**Stop behaviour**: stopping a pattern (no replacement) only performs the duck phase — V0 ramps to zero over `duck_ms`, then the pattern is removed.

## 6. Restim State Client

### 6.1 REST API Client

Polls Restim's HTTP API for state:

```
GET http://{host}:{rest_port}/v1/status
→ {"playing": true, "volume": {"ui": 0.5, "device": 0.48}}

GET http://{host}:{rest_port}/v1/actions
→ {"actions": ["start", "stop"]}

POST http://{host}:{rest_port}/v1/actions/start
POST http://{host}:{rest_port}/v1/actions/stop
```

### 6.2 Polling

- Configurable poll interval (default 200ms)
- State cached locally, available via REST API and MCP
- Can trigger actions based on state changes (play/pause detection)

## 7. Sensor Inputs

Synapse can read external sensors and expose their values to the LLM (via MCP), the REST API, and the web UI. Sensors produce a **normalized value (0.0–1.0)** alongside raw/derived metrics. All sensors are optional and disabled by default.

### 7.1 Sensor Types

#### AS5311 — Magnetic Linear Encoder
Receives position data from Restim via WebSocket (`ws://{host}:12346/sensors/as5311`, JSON `{"x": <metres>}`).

| Field | Description |
|-------|-------------|
| `position_m` | Raw position in metres |
| `velocity_m_s` | Derived velocity (m/s), positive = extending |
| `value` | Normalized 0.0–1.0: position mapped from `[threshold_mm, threshold_mm + range_mm]` |

Config:
```yaml
sensors:
  as5311:
    enabled: false
    url: "ws://localhost:12346/sensors/as5311"
    threshold_mm: 0.0    # position (mm) that maps to 0.0
    range_mm: 2.0        # span from threshold to 1.0
```

#### Heart Rate — BLE HR Profile
Connects to a BLE heart rate sensor (chest strap, watch) via GATT characteristic 0x2A37.

| Field | Description |
|-------|-------------|
| `bpm` | Raw beats per minute |
| `value` | Normalized 0.0–1.0: BPM linearly mapped from `[scale_min_bpm, scale_max_bpm]` |

Config:
```yaml
sensors:
  heart_rate:
    enabled: false
    device_address: ""    # BLE address; leave empty to auto-discover first HR device
    device_label: ""      # human-readable label (display only)
    scale_min_bpm: 40     # BPM → 0.0
    scale_max_bpm: 180    # BPM → 1.0
```

#### Restim Volume
The current Restim playback volume, already polled by §6. Exposed here as a named sensor so the LLM and UI can treat it consistently alongside other inputs.

| Field | Description |
|-------|-------------|
| `volume_ui` | Volume as shown in Restim UI (0.0–1.0) |
| `volume_device` | Volume as reported by device (0.0–1.0) |
| `value` | Same as `volume_ui` |

No additional config — auto-enabled for each configured Restim instance.

### 7.2 Sensor Data Flow

```
AS5311 WebSocket ──┐
Heart Rate BLE ────┼──▶  Sensor Manager  ──▶  cached values
Restim /v1/status ─┘         │
                              ├──▶  REST API  GET /api/sensors
                              ├──▶  WS /ws    (included in tick updates, throttled 10Hz)
                              └──▶  MCP tools  get_sensor / get_sensors
```

Sensor values are cached at the poll/receive rate and served from cache — no blocking reads on the hot path.

### 7.3 Sensor Config Reference

All sensors share these common fields:
```yaml
sensors:
  <name>:
    enabled: bool       # false = sensor not started, not visible in API
    label: str          # override display name in UI
```

## 8. REST API (FastAPI)

### 8.1 Endpoints

#### State
- `GET /api/status` — Synapse status (connected, active pattern, uptime)
- `GET /api/axes` — All axes with current values, limits, units
- `GET /api/axes/{tcode_id}` — Single axis detail
- `GET /api/restim/state` — Mirrored Restim state (playing, volume)
- `GET /api/sensors` — All configured sensors with current values and metadata
- `GET /api/sensors/{name}` — Single sensor (value, raw fields, error state)

#### Control
- `POST /api/axes/{tcode_id}/value` — Set axis value directly `{ "value": 0.5 }`
- `POST /api/volume` — Set volume `{ "value": 0.5 }` (convenience)
- `POST /api/spike` — Spike pattern `{ "intensity": 0.3, "on_ms": 200, "off_ms": 100, "repeat": 5 }` — `intensity` is a delta added to the current volume (e.g. 0.3 at current V0=0.5 → peaks at 0.8)
- `POST /api/emergency-stop` — Immediately zero all axes on all instances and stop all patterns

#### Pattern Library
The pattern library (`./patterns/`) is **shared across all instances** — patterns are saved and loaded globally. Playback state (which pattern is currently active) is **per-instance**. Playing the same pattern on two instances is valid.

- `GET /api/patterns` — List saved patterns (names + descriptions)
- `POST /api/patterns/play` — Play pattern `{ "name": "circular", "instance": "primary", "transition"?: { "duck_amount"?, "duck_ms"?, "ramp_ms"? } }`
- `POST /api/patterns/stop` — Stop current pattern `{ "instance": "primary", "transition"?: { "duck_ms"? } }`
- `POST /api/patterns/snapshot` — Save current state as pattern `{ "name": "my-snapshot", "instance": "primary" }`
- `GET /api/patterns/{name}` — Get full pattern (layers, static_axes, metadata)
- `PATCH /api/patterns/{name}` — Update pattern metadata `{ "description"?, "base_period"?, "duration"? }`
- `DELETE /api/patterns/{name}` — Delete pattern

#### Pattern Layers
- `GET /api/patterns/{name}/layers` — List layers (name, blend, axis count)
- `POST /api/patterns/{name}/layers` — Add layer `{ "name"?, "blend"?, "axes"?: {...} }`  → returns layer name
- `GET /api/patterns/{name}/layers/{layer_name}` — Get layer (blend + all axes)
- `PATCH /api/patterns/{name}/layers/{layer_name}` — Update layer properties `{ "blend"?, "name"? }`
- `DELETE /api/patterns/{name}/layers/{layer_name}` — Remove layer
- `POST /api/patterns/{name}/layers/{layer_name}/move` — Reorder `{ "index": 0 }`

#### Layer Axes
- `GET /api/patterns/{name}/layers/{layer_name}/axes` — List axes in layer
- `PUT /api/patterns/{name}/layers/{layer_name}/axes/{tcode_id}` — Set axis oscillator (full replace)
- `GET /api/patterns/{name}/layers/{layer_name}/axes/{tcode_id}` — Get axis oscillator
- `PATCH /api/patterns/{name}/layers/{layer_name}/axes/{tcode_id}` — Partial update `{ "amplitude"?, "center"?, ... }`
- `DELETE /api/patterns/{name}/layers/{layer_name}/axes/{tcode_id}` — Remove axis from layer

#### Sequence Steps (sequence patterns only)
Steps are addressed by zero-based index (order matters).

- `GET /api/patterns/{name}/steps` — List steps with index, referenced pattern, duration, repeat
- `POST /api/patterns/{name}/steps` — Append step `{ "pattern": "name", "duration"?, "repeat"?, "transition"? }` → returns index
- `GET /api/patterns/{name}/steps/{index}` — Get step details
- `PATCH /api/patterns/{name}/steps/{index}` — Update step `{ "pattern"?, "duration"?, "repeat"?, "transition"? }`
- `DELETE /api/patterns/{name}/steps/{index}` — Remove step (subsequent steps shift down)
- `POST /api/patterns/{name}/steps/{index}/move` — Reorder `{ "index": 2 }`

#### Configuration
- `GET /api/config` — Current configuration (sanitized, no secrets)
- `POST /api/config/reload` — Reload from config file + re-parse INI
- `POST /api/config/reload-ini` — Re-parse restim.ini only

### 8.2 INI Upload
- `POST /api/config/upload-ini` — Upload restim.ini file for parsing `{ "file": multipart }` → returns parsed axis map

### 8.3 WebSocket

- `WS /ws` — Real-time axis state updates (JSON on each tick, throttled to 10Hz for UI)

## 9. MCP Interface

### 9.1 Transport

- **SSE** (default for network access): HTTP SSE endpoint at `/mcp`
- **Stdio** (for local CLI/LLM tools): stdin/stdout JSON-RPC

### 9.2 MCP Tools

#### Device State
| Tool | Description | Parameters |
|------|-------------|------------|
| `get_status` | Get Synapse + Restim status | — |
| `get_axes` | List all axes with current values and limits | — |
| `get_axis` | Get single axis value | `tcode_id: str` |
| `get_restim_state` | Get Restim play state and volume | — |

#### Sensor Readings
| Tool | Description | Parameters |
|------|-------------|------------|
| `get_sensors` | List all configured sensors with current values and status | — |
| `get_sensor` | Get a specific sensor's value and raw fields | `name: str` |

#### Direct Control
| Tool | Description | Parameters |
|------|-------------|------------|
| `set_axis` | Set axis to a specific value | `tcode_id, value: float` |
| `set_volume` | Set main volume | `value: float (0-1)` |
| `spike` | Create a brief intensity spike | `intensity: float (delta added to current volume), on_ms, off_ms, repeat` |
| `start_playback` | Start Restim playback | — |
| `stop_playback` | Stop Restim playback | — |
| `emergency_stop` | Immediately zero all axes on all instances and stop all patterns | — |

#### Pattern Control (per-instance)
| Tool | Description | Parameters |
|------|-------------|------------|
| `list_patterns` | List all saved patterns (shared library) | — |
| `play_pattern` | Start a named pattern | `name: str, instance: str, duck_amount?: float, duck_ms?: int, ramp_ms?: int` |
| `stop_pattern` | Stop current pattern | `instance: str, duck_ms?: int` |
| `create_pattern` | Create a new empty leaf pattern | `name, description?, base_period?, duration?` |
| `create_sequence` | Create a new empty sequence pattern | `name, description?, loop?: bool` |
| `describe_pattern` | Get full pattern (layers, axes, metadata) | `name: str` |
| `snapshot_pattern` | Save current axis state as a pattern | `name: str, instance: str, description?: str` |
| `delete_pattern` | Delete a saved pattern | `name: str` |

#### Pattern Layer CRUD
| Tool | Description | Parameters |
|------|-------------|------------|
| `list_layers` | List layers in a pattern | `pattern_name: str` |
| `add_layer` | Add a new layer | `pattern_name, blend?, layer_name?, instance?` → returns `layer_name` |
| `describe_layer` | Get layer details (blend + all axes) | `pattern_name, layer_name` |
| `modify_layer` | Change layer blend or name | `pattern_name, layer_name, blend?, new_name?` |
| `remove_layer` | Remove a layer | `pattern_name, layer_name` |
| `move_layer` | Reorder a layer | `pattern_name, layer_name, index: int` |

#### Layer Axis CRUD
| Tool | Description | Parameters |
|------|-------------|------------|
| `set_layer_axis` | Add or fully replace an axis oscillator in a layer | `pattern_name, layer_name, tcode_id, waveform, amplitude, center?, offset?, frequency?, freq_multiple?, attack?, sustain?, release?` |
| `modify_layer_axis` | Partial update of an axis oscillator | `pattern_name, layer_name, tcode_id, amplitude?, center?, offset?, waveform?, frequency?, freq_multiple?, attack?, sustain?, release?` |
| `remove_layer_axis` | Remove an axis from a layer | `pattern_name, layer_name, tcode_id` |

#### Sequence Step CRUD
| Tool | Description | Parameters |
|------|-------------|------------|
| `list_steps` | List steps in a sequence pattern | `pattern_name: str` |
| `add_step` | Append a step to a sequence | `pattern_name, step_pattern: str, duration?: float, repeat?: int, transition?: dict` → returns index |
| `modify_step` | Update a step | `pattern_name, step_index: int, step_pattern?: str, duration?: float, repeat?: int, transition?: dict` |
| `remove_step` | Remove a step by index | `pattern_name, step_index: int` |
| `move_step` | Reorder a step | `pattern_name, step_index: int, new_index: int` |

### 9.3 MCP Resources

| Resource | Description |
|----------|-------------|
| `synapse://status` | Current system status |
| `synapse://axes` | Axis definitions and values |
| `synapse://patterns` | Saved pattern list |
| `synapse://pattern/{name}` | Full pattern YAML |

## 10. Configuration

### 10.1 Config File (`synapse.yaml`)

```yaml
# Synapse configuration
restim:
  ini_path: "./restim.ini"           # Path to restim.ini for axis limits
  instances:
    - id: "primary"
      host: "localhost"
      tcode_port: 12347              # TCode TCP port
      rest_port: 12348               # REST API port
      enabled: true

engine:
  update_rate_hz: 50                 # TCode command rate
  reconnect_delay_ms: 1000          # Initial reconnect delay
  max_reconnect_delay_ms: 30000     # Max reconnect delay (exponential backoff)

api:
  host: "0.0.0.0"
  port: 8080
  auth_key: ""                       # Optional API key

mcp:
  enabled: true
  transport: "sse"                   # "sse" or "stdio"
  port: 8081                         # SSE port (if sse)
  localhost_only: true               # When true, MCP SSE binds to 127.0.0.1 only (recommended)
  bearer_token: ""                   # If set, SSE clients must supply Authorization: Bearer <token>
                                     # Ignored when localhost_only is true (no need for auth on loopback)

patterns:
  directory: "./patterns"            # Where to store pattern YAML files
  transition:
    duck_amount: 1.0                 # Fraction of current V0 to remove on switch (1.0 = full silence)
    duck_ms: 200                     # Time to ramp volume down
    ramp_ms: 400                     # Time to ramp volume back up after switch

logging:
  level: "INFO"
```

### 10.2 Environment Variables

All config values overridable via env vars:
- `SYNAPSE_RESTIM_INI_PATH`
- `SYNAPSE_API_PORT`
- `SYNAPSE_MCP_TRANSPORT`
- etc. (dotted config path → `SYNAPSE_` prefix + uppercase + underscores)

## 11. Web UI

### 11.1 Pages/Views

- **Dashboard**: Connection status, current pattern, quick volume control
- **Axes**: Grid of all axes with sliders/inputs showing real-world values
- **Patterns**: List, play, stop, create new patterns
- **Pattern Editor**: Visual oscillator editor (waveform selection, frequency, amplitude)
- **Sensors**: Live readout of all configured sensors (value, raw fields, connection status)
- **Settings**: Connection config, INI path, update rate, sensor configuration

### 11.2 Tech

- Single-page app, served from FastAPI static files
- Framework: **Preact** (lightweight, well-documented, good LLM code generation via JSX, small bundle)
- WebSocket for live axis updates
- Responsive, works on mobile
- All components should be self-documenting with JSDoc comments for LLM readability

## 12. Tech Stack

- **Language**: Python 3.11+
- **Async**: asyncio throughout
- **Web Framework**: FastAPI (REST + WebSocket + static files)
- **MCP**: `mcp` Python SDK (fastmcp)
- **Config**: PyYAML
- **BLE**: `bleak` (cross-platform BLE, for heart rate sensor)
- **Testing**: pytest + pytest-asyncio
- **Packaging**: PyInstaller for standalone binary, or Docker

## 13. Project Structure

```
synapse/
├── pyproject.toml
├── synapse.yaml              # Default config
├── patterns/                 # Saved pattern YAML files
│   ├── circular-motion.yaml
│   └── escalating-pulse.yaml
├── src/
│   └── synapse/
│       ├── __init__.py
│       ├── main.py           # Entry point
│       ├── config.py         # Config loading
│       ├── ini_parser.py     # Restim INI parser
│       ├── axes.py           # Axis definitions + mapping
│       ├── engine.py         # TCode command loop
│       ├── tcode.py          # TCode protocol (format/parse)
│       ├── restim_client.py  # Restim HTTP client
│       ├── sensors/
│       │   ├── __init__.py
│       │   ├── manager.py    # Sensor lifecycle + value cache
│       │   ├── as5311.py     # AS5311 WebSocket reader
│       │   ├── heart_rate.py # BLE HR reader (bleak)
│       │   └── models.py     # SensorReading dataclass
│       ├── patterns/
│       │   ├── __init__.py
│       │   ├── models.py     # AxisOscillator, Layer, Pattern dataclasses
│       │   ├── store.py      # Save/load YAML patterns
│       │   └── player.py     # Pattern evaluation + layering
│       ├── api/
│       │   ├── __init__.py
│       │   ├── app.py        # FastAPI app setup
│       │   ├── routes_state.py
│       │   ├── routes_control.py
│       │   ├── routes_patterns.py
│       │   └── websocket.py  # Live axis updates
│       └── mcp/
│           ├── __init__.py
│           └── server.py     # MCP tool definitions
├── web/                      # Frontend assets
│   └── ...
└── tests/
    ├── test_tcode.py
    ├── test_ini_parser.py
    ├── test_patterns.py
    └── test_api.py
```

## 14. Safety & Limits

- **Emergency stop**: Any API call with `/api/emergency-stop` immediately sends all axes to 0
- **Max values enforced**: Never exceed `limit_max`, never go below `limit_min`
- **Rate limiting**: Axis value changes capped per second (configurable, prevents jerky motion)
- **Volume ramp**: Volume changes ramp at max 10%/s by default (configurable per-instance)
- **Auth**: Optional API key for REST endpoints

## 15. Spike as a Pattern Layer

Spikes are not a separate feature — they're a pattern with a single `add`-blend layer. The `add` blend means the spike intensity is a **delta relative to the current volume** — it adds on top of whatever V0 is at that moment, whether from a running pattern, a static value, or zero.

```yaml
name: "spike-medium"
duration: 0.45  # attack + sustain + release = auto-stop
layers:
  - name: "spike"
    blend: add          # delta relative to current V0 — if V0=0.5, peaks at 0.8
    axes:
      V0:
        waveform: hold
        amplitude: 0.3  # adds +0.3 at peak (clamped to 1.0)
        attack: 0.1     # 100ms ramp up
        sustain: 0.2    # hold for 200ms
        release: 0.15   # 150ms ramp down
```

To trigger via API/MCP:
- `play_pattern` with a spike pattern → its `add` layer stacks on top of any currently playing pattern
- Once the envelope completes, the pattern auto-stops (via `duration`) and the running pattern resumes unaffected
- Multiple spikes can overlap — their contributions are summed before clamping

This replaces the old dedicated spike mechanism with a more flexible composable system.

## 16. Future Scope

- **Funscript playback** — Load `.funscript` files and drive axes from them. Will integrate routines from [funscript-tools](https://github.com/edger477/funscript-tools) in a future iteration.
- **Pattern import/export** — Share patterns between setups (already supported via YAML files in the patterns directory).
- **Funscript-to-pattern conversion** — Convert a funscript into a pattern (timed axis values → hold layers).
