from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp

from synapse.config import RestimInstanceConfig

logger = logging.getLogger(__name__)


class RestimState:
    __slots__ = ("playing", "volume_ui", "volume_device", "error")

    def __init__(
        self,
        playing: bool = False,
        volume_ui: float = 0.0,
        volume_device: float = 0.0,
        error: Optional[str] = None,
    ) -> None:
        self.playing = playing
        self.volume_ui = volume_ui
        self.volume_device = volume_device
        self.error = error


class RestimClient:
    def __init__(self, config: RestimInstanceConfig, poll_interval: float = 0.2) -> None:
        self._config = config
        self._poll_interval = poll_interval
        self._state = RestimState()
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def base_url(self) -> str:
        return f"http://{self._config.host}:{self._config.rest_port}"

    async def start(self) -> None:
        self._running = True
        self._session = aiohttp.ClientSession()
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._session:
            await self._session.close()

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                async with self._session.get(
                    f"{self.base_url}/v1/status", timeout=aiohttp.ClientTimeout(total=2.0)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        vol = data.get("volume", {})
                        self._state = RestimState(
                            playing=bool(data.get("playing", False)),
                            volume_ui=float(vol.get("ui", 0.0)),
                            volume_device=float(vol.get("device", 0.0)),
                            error=None,
                        )
            except Exception as e:
                self._state = RestimState(
                    playing=self._state.playing,
                    volume_ui=self._state.volume_ui,
                    volume_device=self._state.volume_device,
                    error=str(e),
                )
            await asyncio.sleep(self._poll_interval)

    def get_state(self) -> RestimState:
        return self._state

    async def start_playback(self) -> bool:
        return await self._post_action("start")

    async def stop_playback(self) -> bool:
        return await self._post_action("stop")

    async def _post_action(self, action: str) -> bool:
        if self._session is None:
            return False
        try:
            async with self._session.post(
                f"{self.base_url}/v1/actions/{action}",
                timeout=aiohttp.ClientTimeout(total=5.0),
            ) as resp:
                return resp.status < 300
        except Exception as e:
            logger.warning("Restim action '%s' failed: %s", action, e)
            return False
