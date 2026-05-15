from __future__ import annotations

import asyncio
import configparser
import logging
from pathlib import Path
from typing import Optional

from watchdog.events import FileSystemEventHandler, FileSystemEvent
from watchdog.observers import Observer

from synapse.axes import AxisDef

logger = logging.getLogger(__name__)

# Map INI section names → axis names
INI_SECTION_MAP: dict[str, str] = {
    "POSITION_ALPHA": "alpha",
    "POSITION_BETA": "beta",
    "VOLUME": "volume",
    "VOLUME_EXTERNAL": "volume_ext",
    "CARRIER_FREQUENCY": "carrier_freq",
    "PULSE_FREQUENCY": "pulse_freq",
    "PULSE_WIDTH": "pulse_width",
    "PULSE_RANDOM": "pulse_random",
    "PULSE_RISE": "pulse_rise",
    "ELECTRODE_1": "e1",
    "ELECTRODE_2": "e2",
    "ELECTRODE_3": "e3",
    "ELECTRODE_4": "e4",
}

AXIS_VALUE_TYPES: dict[str, str] = {
    "alpha": "percentage",
    "beta": "percentage",
    "volume": "percentage",
    "volume_ext": "percentage",
    "carrier_freq": "frequency",
    "pulse_freq": "frequency",
    "pulse_width": "linear",
    "pulse_random": "percentage",
    "pulse_rise": "frequency",
    "e1": "percentage",
    "e2": "percentage",
    "e3": "percentage",
    "e4": "percentage",
}


def parse_ini(content: str) -> dict[str, AxisDef]:
    parser = configparser.ConfigParser(strict=False)
    parser.read_string(content)

    result: dict[str, AxisDef] = {}
    for section, axis_name in INI_SECTION_MAP.items():
        if not parser.has_section(section):
            continue
        tcode_id = parser.get(section, "tcode_axis", fallback="").strip()
        enabled = bool(tcode_id)
        try:
            limit_min = float(parser.get(section, "limit_min", fallback="0"))
            limit_max = float(parser.get(section, "limit_max", fallback="1"))
        except ValueError:
            limit_min, limit_max = 0.0, 1.0

        value_type = AXIS_VALUE_TYPES.get(axis_name, "percentage")
        result[axis_name] = AxisDef(
            tcode_id=tcode_id,
            name=axis_name,
            value_type=value_type,
            limit_min=limit_min,
            limit_max=limit_max,
            enabled=enabled,
        )
    return result


def parse_ini_file(path: str | Path) -> dict[str, AxisDef]:
    p = Path(path)
    if not p.exists():
        logger.warning("INI file not found: %s", path)
        return {}
    return parse_ini(p.read_text())


class _ChangeHandler(FileSystemEventHandler):
    def __init__(self, path: Path, queue: asyncio.Queue) -> None:
        self._path = path.resolve()
        self._queue = queue

    def on_modified(self, event: FileSystemEvent) -> None:
        if Path(event.src_path).resolve() == self._path:
            try:
                self._queue.put_nowait("reload")
            except asyncio.QueueFull:
                pass


class IniWatcher:
    """Watch INI file for changes and trigger reload via asyncio queue."""

    def __init__(self, path: str | Path, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self._path = Path(path)
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._observer: Optional[Observer] = None
        self._loop = loop

    def start(self) -> None:
        if not self._path.exists():
            return
        self._observer = Observer()
        handler = _ChangeHandler(self._path, self._queue)
        self._observer.schedule(handler, str(self._path.parent), recursive=False)
        self._observer.start()

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join()

    async def wait_for_change(self) -> None:
        await self._queue.get()

    def has_pending(self) -> bool:
        return not self._queue.empty()
