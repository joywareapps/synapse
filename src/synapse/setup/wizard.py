from __future__ import annotations

"""Interactive setup wizard — `synapse init`."""

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

import httpx
import yaml


# Common locations where Restim stores restim.ini
def _ini_candidates() -> list[Path]:
    candidates = [Path("./restim.ini")]
    home = Path.home()
    candidates += [
        home / ".config" / "Restim" / "restim.ini",
        home / ".local" / "share" / "Restim" / "restim.ini",
        home / "Library" / "Application Support" / "Restim" / "restim.ini",
    ]
    if appdata := os.environ.get("APPDATA"):
        candidates.insert(0, Path(appdata) / "Restim" / "restim.ini")
    return candidates


def _find_restim_ini() -> Optional[Path]:
    for c in _ini_candidates():
        if c.exists():
            return c
    return None


def _p(msg: str = "") -> None:
    print(msg, flush=True)


def _ask(prompt: str, default: str = "") -> str:
    display = f"  {prompt} [{default}]: " if default else f"  {prompt}: "
    try:
        answer = input(display).strip()
    except (KeyboardInterrupt, EOFError):
        _p("\nAborted.")
        sys.exit(1)
    return answer if answer else default


def _ask_bool(prompt: str, default: bool = False) -> bool:
    tag = "Y/n" if default else "y/N"
    answer = _ask(f"{prompt} [{tag}]", "").lower()
    if not answer:
        return default
    return answer in ("y", "yes", "1", "true")


async def _probe_restim(host: str, tcode_port: int, rest_port: int) -> dict[str, bool]:
    result = {"tcode": False, "rest": False}
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, tcode_port), timeout=2.0
        )
        writer.close()
        await writer.wait_closed()
        result["tcode"] = True
    except Exception:
        pass
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"http://{host}:{rest_port}/v1/status")
            result["rest"] = resp.status_code == 200
    except Exception:
        pass
    return result


async def _scan_ble() -> list[dict]:
    try:
        from bleak import BleakScanner
        devices = await BleakScanner.discover(timeout=5.0)
        return sorted(
            [{"name": d.name or "Unknown", "address": d.address} for d in devices],
            key=lambda d: d["name"].lower(),
        )
    except ImportError:
        return []
    except Exception:
        return []


async def _wizard(output_path: str) -> None:
    _p()
    _p("Synapse setup wizard")
    _p("=" * 42)
    _p()

    # ── Restim ────────────────────────────────────────────────────────────────
    _p("Restim connection")
    _p("-" * 20)
    host = "localhost"
    tcode_port = 12347
    rest_port = 12348

    status = await _probe_restim(host, tcode_port, rest_port)
    if status["tcode"] or status["rest"]:
        bits = []
        if status["tcode"]:
            bits.append(f"TCode :{tcode_port}")
        if status["rest"]:
            bits.append(f"REST :{rest_port}")
        _p(f"  ✓ Restim found ({', '.join(bits)})")
    else:
        _p(f"  ✗ Restim not reachable at {host}:{tcode_port}")
        _p("    Synapse will retry on startup — make sure Restim is running.")
    _p()

    # ── Restim INI ────────────────────────────────────────────────────────────
    _p("Axis configuration (restim.ini)")
    _p("-" * 20)
    found_ini = _find_restim_ini()
    if found_ini:
        _p(f"  Found: {found_ini}")
        use_it = _ask_bool("Use this path?", default=True)
        ini_path = str(found_ini) if use_it else _ask("Path to restim.ini", default="./restim.ini")
    else:
        _p("  Not found in common locations.")
        _p("  Export from Restim: File → Export settings → restim.ini")
        ini_path = _ask("Path to restim.ini (blank = use defaults)", default="./restim.ini")
    _p()

    # ── LLM provider ─────────────────────────────────────────────────────────
    _p("Embedded agent (LLM)")
    _p("-" * 20)
    ollama_url = "http://localhost:11434"
    lm_studio_url = "http://localhost:1234"
    chosen_model = ""

    try:
        from synapse.agent.llm_client import detect_providers
        providers = await detect_providers(ollama_url, lm_studio_url)
    except Exception:
        providers = []

    tool_capable: list[str] = []
    for p in providers:
        _p(f"  ✓ {p.name} at {p.base_url}")
        model_preview = ", ".join(p.models[:4]) + (" …" if len(p.models) > 4 else "")
        _p(f"      Models: {model_preview or '(none loaded)'}")
        if p.tool_capable_models:
            _p(f"      Tool-capable: {', '.join(p.tool_capable_models[:3])}")
            tool_capable.extend(p.tool_capable_models)
        elif p.models:
            tool_capable.extend(p.models)

    if not providers:
        _p("  ✗ No providers found (Ollama / LM Studio not running)")
        _p("    Install Ollama or LM Studio and pull a model, then re-run.")

    if providers:
        _p()
        chosen_model = _ask("Default model for agent", default=tool_capable[0] if tool_capable else "")
    _p()

    # ── Sensors ───────────────────────────────────────────────────────────────
    _p("Sensors (optional)")
    _p("-" * 20)

    enable_hr = _ask_bool("Enable heart rate sensor (BLE)?", default=False)
    hr_address = ""
    if enable_hr:
        _p("  Scanning for BLE devices (5 s) …")
        ble_devices = await _scan_ble()
        if ble_devices:
            for i, d in enumerate(ble_devices):
                _p(f"    [{i}] {d['name']}  {d['address']}")
            choice = _ask("Select number, or enter address directly", default="")
            try:
                hr_address = ble_devices[int(choice)]["address"]
            except (ValueError, IndexError):
                hr_address = choice
        else:
            _p("  No BLE devices found (Bluetooth may need root / capabilities).")
            hr_address = _ask("Device address (leave blank to set later)", default="")
    _p()

    enable_as5311 = _ask_bool("Enable AS5311 position sensor?", default=False)
    as5311_url = "ws://localhost:12346/sensors/as5311"
    if enable_as5311:
        as5311_url = _ask("AS5311 WebSocket URL", default=as5311_url)
    _p()

    # ── Write config ──────────────────────────────────────────────────────────
    out = _ask("Write config to", default=output_path)

    config: dict = {
        "restim": {
            "ini_path": ini_path,
            "instances": [
                {
                    "id": "primary",
                    "host": host,
                    "tcode_port": tcode_port,
                    "rest_port": rest_port,
                    "enabled": True,
                }
            ],
        },
        "engine": {"update_rate_hz": 50, "reconnect_delay_ms": 1000, "max_reconnect_delay_ms": 30000},
        "api": {"host": "0.0.0.0", "port": 8080, "auth_key": ""},
        "mcp": {
            "enabled": True,
            "transport": "sse",
            "port": 8081,
            "localhost_only": True,
            "bearer_token": "",
        },
        "patterns": {
            "directory": "./patterns",
            "transition": {"duck_amount": 1.0, "duck_ms": 200, "ramp_ms": 400},
        },
        "sensors": {
            "as5311": {
                "enabled": enable_as5311,
                "url": as5311_url,
                "threshold_mm": 0.0,
                "range_mm": 2.0,
            },
            "heart_rate": {
                "enabled": enable_hr,
                "device_address": hr_address,
                "device_label": "",
                "scale_min_bpm": 40,
                "scale_max_bpm": 180,
            },
        },
        "sessions": {"directory": "./sessions", "auto_name": True},
        "profiles": {"directory": "./profiles"},
        "agent": {
            "provider": "auto",
            "ollama_url": ollama_url,
            "lm_studio_url": lm_studio_url,
            "model": chosen_model,
            "loop_interval_s": 30,
            "loop_mode": "observe",
            "max_tool_calls_per_tick": 2,
            "system_prompt_extra": "",
        },
        "logging": {"level": "INFO"},
    }

    Path(out).write_text(
        yaml.dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    _p()
    _p(f"✓ Config written to {out}")
    _p(f"  Run: synapse --config {out}")
    _p()


def run_wizard(output_path: str = "synapse.yaml") -> None:
    asyncio.run(_wizard(output_path))
