from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import time
from pathlib import Path
from typing import Optional

import uvicorn

from synapse.api.deps import ctx
from synapse.axes import AxisMap
from synapse.config import load_config
from synapse.engine import TCodeEngine
from synapse.ini_parser import IniWatcher, parse_ini_file
from synapse.patterns.player import PatternPlayer
from synapse.patterns.store import PatternStore
from synapse.restim_client import RestimClient
from synapse.sensors.manager import SensorManager


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


async def _run(config_path: Optional[str] = None) -> None:
    config = load_config(config_path)
    _setup_logging(config.logging.level)
    logger = logging.getLogger(__name__)

    # Axis map
    axis_map = AxisMap()
    ini_path = config.restim.ini_path
    if Path(ini_path).exists():
        ini_axes = parse_ini_file(ini_path)
        axis_map.apply_ini(ini_axes)
    else:
        logger.info("INI file not found at %s — using defaults", ini_path)

    # Warn about volume_ext
    vol = axis_map.volume_axis()
    if vol and vol.name == "volume":
        logger.warning(
            "volume_ext has no TCode ID configured — falling back to V0 for volume control. "
            "Configure it in Restim: Settings → TCode axes → VOLUME_EXTERNAL"
        )

    # Pattern store
    store = PatternStore(config.patterns.directory)
    store.load_all()

    # Build per-instance players, engines, restim clients
    players: dict[str, PatternPlayer] = {}
    engines: dict[str, TCodeEngine] = {}
    restim_clients: dict[str, RestimClient] = {}

    t = config.patterns.transition
    for inst in config.restim.instances:
        if not inst.enabled:
            continue
        player = PatternPlayer(
            duck_amount=t.duck_amount,
            duck_ms=t.duck_ms,
            ramp_ms=t.ramp_ms,
        )
        engine = TCodeEngine(inst, config.engine, axis_map, player)
        client = RestimClient(inst)
        players[inst.id] = player
        engines[inst.id] = engine
        restim_clients[inst.id] = client

    sensor_manager = SensorManager(config.sensors)

    # Populate shared context
    ctx.config = config
    ctx.axis_map = axis_map
    ctx.engines = engines
    ctx.players = players
    ctx.store = store
    ctx.restim_clients = restim_clients
    ctx.sensor_manager = sensor_manager
    ctx.start_time = time.monotonic()

    # Start background tasks
    tasks = []
    for engine in engines.values():
        tasks.append(asyncio.create_task(engine.start()))
    for client in restim_clients.values():
        tasks.append(asyncio.create_task(client.start()))
    tasks.append(asyncio.create_task(sensor_manager.start()))

    # INI watcher
    ini_watcher = IniWatcher(ini_path)
    ini_watcher.start()

    async def _ini_reload_loop() -> None:
        while True:
            await ini_watcher.wait_for_change()
            logger.info("INI file changed — reloading")
            new_axes = parse_ini_file(ini_path)
            axis_map.apply_ini(new_axes)

    tasks.append(asyncio.create_task(_ini_reload_loop()))

    # FastAPI
    from synapse.api.app import create_app
    web_dir = "web" if Path("web").exists() else None
    app = create_app(auth_key=config.api.auth_key, web_dir=web_dir)

    uvicorn_config = uvicorn.Config(
        app,
        host=config.api.host,
        port=config.api.port,
        log_level=config.logging.level.lower(),
        loop="asyncio",
    )
    server = uvicorn.Server(uvicorn_config)

    # MCP server
    mcp_task = None
    if config.mcp.enabled:
        from synapse.mcp.server import mcp
        if config.mcp.transport == "stdio":
            mcp_task = asyncio.create_task(mcp.run_async())
        else:
            # SSE — run on separate port
            mcp_host = "127.0.0.1" if config.mcp.localhost_only else "0.0.0.0"
            mcp_task = asyncio.create_task(
                mcp.run_async(transport="sse", host=mcp_host, port=config.mcp.port)
            )

    # Graceful shutdown
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _handle_signal() -> None:
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass  # Windows

    logger.info("Synapse starting — API at %s:%d", config.api.host, config.api.port)

    server_task = asyncio.create_task(server.serve())

    try:
        await shutdown_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        logger.info("Shutting down...")
        server.should_exit = True
        for engine in engines.values():
            await engine.stop()
        for client in restim_clients.values():
            await client.stop()
        await sensor_manager.stop()
        ini_watcher.stop()
        for task in tasks:
            task.cancel()
        if mcp_task:
            mcp_task.cancel()
        await asyncio.gather(*tasks, server_task, return_exceptions=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Synapse — Restim bridge service")
    parser.add_argument("--config", default=None, help="Path to synapse.yaml")
    args = parser.parse_args()
    asyncio.run(_run(args.config))


if __name__ == "__main__":
    main()
