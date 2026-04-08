import asyncio
import datetime
from typing import Optional

import aiohttp

from watchdog_logging import log
from watchdog_models import DeviceState
from watchdog_mqtt import MqttBridge, publish_status

HTTP_TIMEOUT = aiohttp.ClientTimeout(total=10)


async def _http_check(
    session: aiohttp.ClientSession,
    state: DeviceState,
    bridge: Optional[MqttBridge],
) -> None:
    cfg = state.config
    try:
        async with session.get(cfg.http_url, timeout=HTTP_TIMEOUT, ssl=False) as resp:
            if 200 <= resp.status < 300:
                now = asyncio.get_running_loop().time()
                was_online = state.ever_seen and (now - state.last_seen) < (
                    cfg.miss_threshold * cfg.ping_interval
                )
                state.last_seen = now
                state.last_seen_wall = datetime.datetime.now(datetime.timezone.utc)
                state.ever_seen = True
                if not was_online:
                    log.info("[%s] Device back online (HTTP %d)", cfg.name, resp.status)
                    if bridge:
                        publish_status(bridge, state)
                else:
                    log.debug("[%s] HTTP check OK (%d)", cfg.name, resp.status)
            else:
                log.warning(
                    "[%s] HTTP check returned %d — treating as offline",
                    cfg.name,
                    resp.status,
                )
    except Exception as exc:
        log.debug("[%s] HTTP check failed: %s", cfg.name, exc)


async def http_pollers(
    states: dict[str, DeviceState],
    bridge: Optional[MqttBridge],
) -> None:
    http_states = [s for s in states.values() if s.config.is_http_polled]
    if not http_states:
        return

    async def poll_device(state: DeviceState) -> None:
        async with aiohttp.ClientSession() as session:
            while True:
                await _http_check(session, state, bridge)
                await asyncio.sleep(state.config.ping_interval)

    for state in http_states:
        log.info(
            "Watching [%s] via HTTP poll %s every %ds",
            state.config.name,
            state.config.http_url,
            state.config.ping_interval,
        )

    await asyncio.gather(*[poll_device(s) for s in http_states])
