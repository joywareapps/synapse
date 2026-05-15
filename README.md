# Synapse

A Python service that bridges Restim e-stim devices to LLMs via MCP, REST APIs, and a web UI — driving TCode axes, reading device state, composing reusable patterns, and reading sensors.

## Overview

```
LLM (Claude, etc.)
    │  MCP tools
    ▼
┌─────────────────────────────────────────────┐
│                  Synapse                    │
│                                             │
│  Pattern System   Sensor Inputs   REST API  │
│  (oscillators,    (AS5311, HR,    (FastAPI) │
│   sequences)       Restim vol)             │
│                                             │
│         TCode Engine @ 50Hz                │
└──────────┬──────────────────┬──────────────┘
           │ TCP TCode        │ HTTP
           ▼                  ▼
      Restim device      Restim app
      (port 12347)       (port 12348)
```

## Quick Start

```bash
# Install
pip install -e .

# Configure (copy and edit)
cp synapse.yaml my-synapse.yaml
# Set restim.ini_path if you want axis limits from your device config

# Run
synapse --config my-synapse.yaml
```

Web UI: http://localhost:8080  
MCP SSE endpoint: http://localhost:8081/mcp  

## Configuration

`synapse.yaml` controls all behaviour. Key settings:

```yaml
restim:
  ini_path: "./restim.ini"        # path to Restim's exported axis config
  instances:
    - id: "primary"
      host: "localhost"
      tcode_port: 12347
      rest_port: 12348

engine:
  update_rate_hz: 50              # TCode output rate

api:
  port: 8080
  auth_key: ""                    # optional REST API key

mcp:
  transport: "sse"                # "sse" or "stdio"
  port: 8081
  localhost_only: true            # recommended; set false + bearer_token for network access
  bearer_token: ""

sensors:
  as5311:
    enabled: false
    url: "ws://localhost:12346/sensors/as5311"
    threshold_mm: 0.0
    range_mm: 2.0
  heart_rate:
    enabled: false
    device_address: ""
    scale_min_bpm: 40
    scale_max_bpm: 180

patterns:
  directory: "./patterns"
  transition:
    duck_amount: 1.0              # 1.0 = silence gap between patterns
    duck_ms: 200
    ramp_ms: 400
```

All values can be overridden with environment variables:
```
SYNAPSE_API_PORT=9090
SYNAPSE_ENGINE_UPDATE_RATE_HZ=100
SYNAPSE_MCP_BEARER_TOKEN=secret
```

### Restim INI

Synapse reads your Restim device config to get the exact axis limits your hardware is calibrated for. In Restim: **File → Export settings → restim.ini**, then set `restim.ini_path` in `synapse.yaml`. Without it, Synapse falls back to Restim's built-in defaults.

> **External volume**: For best results, configure the `VOLUME_EXTERNAL` TCode axis in Restim's device wizard. This lets Synapse control volume even during non-Synapse Restim playback.

## Pattern System

Patterns are YAML files in `./patterns/`. Two types:

**Leaf patterns** — layered oscillators:
```yaml
name: "gentle-pulse"
base_period: 3.0
layers:
  - name: "base"
    blend: set
    axes:
      V0: { waveform: sine, freq_multiple: 1.0, center: 0.4, amplitude: 0.2 }
      C0: { waveform: hold, center: 0.5, amplitude: 0.0 }
```

**Sequence patterns** — ordered steps referencing other patterns:
```yaml
name: "exploration-program"
loop: true
steps:
  - pattern: "gentle-pulse"
    duration: 60.0
  - pattern: "escalating-pulse"
    duration: 30.0
```

Layer blend modes:
- `set` — base oscillator; defines the axis value
- `add` — adds a delta on top (spikes, intensity overlays)
- `mul` — multiplies the accumulated value (tremolo, AM)

See [SPEC.md](SPEC.md) §5 for the full pattern system documentation.

## MCP Integration

Add to your Claude config (`~/.claude.json` or project config):

```json
{
  "mcpServers": {
    "synapse": {
      "type": "sse",
      "url": "http://localhost:8081/mcp"
    }
  }
}
```

Or for stdio (local only):
```json
{
  "mcpServers": {
    "synapse": {
      "command": "synapse",
      "args": ["--mcp-stdio"]
    }
  }
}
```

See [docs/mcp-guide.md](docs/mcp-guide.md) for the operational guide the LLM uses when controlling the device.

## Safety

- **Emergency stop**: `POST /api/emergency-stop` — zeroes all axes immediately
- **Volume ramp**: Volume changes are rate-limited to 10%/s by default — never jumps
- **Axis limits**: Values are clamped to `[limit_min, limit_max]` from the INI; never exceed hardware limits
- **Pattern transitions**: Duck-and-switch — volume dips to zero before switching patterns, so axis changes are imperceptible
- **MCP localhost-only**: Default config binds MCP to 127.0.0.1 only

## Sensors

| Sensor | Source | What it provides |
|--------|--------|-----------------|
| AS5311 | Restim WebSocket | Position (mm), velocity (m/s), normalized 0–1 |
| Heart rate | BLE (GATT 0x2A37) | BPM, normalized 0–1 |
| Restim volume | Restim REST API | UI volume, device volume |

Enable sensors in `synapse.yaml` and they appear in `/api/sensors` and MCP `get_sensors`.

## Session Recording

Record a session to funscript files for sharing or replay:

```bash
# Via API
curl -X POST /api/sessions/start -d '{"name": "my-session", "instance": "primary"}'
# ... play patterns, interact ...
curl -X POST /api/sessions/stop -d '{"instance": "primary"}'
```

Produces files in `./sessions/`:
```
my-session.V0.funscript
my-session.L0.funscript
my-session.C0.funscript
```

Compatible with Restim's funscript format — load directly in Restim or share with funscript-tools.

## Development

```bash
# Install with dev deps
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Run with auto-reload
uvicorn synapse.api.app:create_app --reload --factory
```

### Project Structure

```
src/synapse/
├── main.py           # entry point
├── config.py         # config loading + env overrides
├── axes.py           # axis definitions + INI-based mapping
├── ini_parser.py     # Restim INI parser + file watcher
├── tcode.py          # TCode protocol formatting
├── engine.py         # 50Hz TCode output loop
├── restim_client.py  # Restim HTTP API client
├── patterns/
│   ├── models.py     # AxisOscillator, Layer, Pattern, SequenceStep
│   ├── store.py      # YAML pattern library
│   └── player.py     # pattern evaluation + transitions
├── sensors/
│   ├── models.py     # SensorReading, configs
│   ├── manager.py    # sensor lifecycle
│   ├── as5311.py     # AS5311 WebSocket reader
│   └── heart_rate.py # BLE HR reader
├── api/
│   ├── app.py        # FastAPI app factory
│   ├── routes_state.py
│   ├── routes_control.py
│   ├── routes_patterns.py
│   └── websocket.py  # live axis + sensor push
└── mcp/
    └── server.py     # MCP tool definitions
```
