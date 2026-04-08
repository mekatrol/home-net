import asyncio
import datetime
import time

from watchdog_commands import send_command, send_restart_container
from watchdog_logging import log
from watchdog_models import COMMAND_TIMEOUT, DeviceState


async def watchdog_loop(states: dict[str, DeviceState]) -> None:
    while True:
        await asyncio.sleep(10)
        now = time.monotonic()

        for state in states.values():
            cfg = state.config

            if state.disabled:
                continue

            if state.pending_command_id and state.pending_command_at:
                if now - state.pending_command_at > COMMAND_TIMEOUT:
                    log.warning("[%s] Command timed out — no result received", cfg.name)
                    state.pending_command_id = None
                    state.pending_command_at = None

            if state.rebooting:
                elapsed = now - state.reboot_at
                if elapsed < cfg.reboot_cooldown:
                    log.debug(
                        "[%s] Cooldown — %ds remaining",
                        cfg.name,
                        cfg.reboot_cooldown - elapsed,
                    )
                    continue
                log.info("[%s] Cooldown elapsed, resuming monitoring", cfg.name)
                state.rebooting = False
                state.last_seen = now
                continue

            silence = now - state.last_seen
            threshold = cfg.miss_threshold * cfg.ping_interval

            if silence >= threshold:
                if cfg.is_mqtt_only or cfg.is_http_polled:
                    log.warning(
                        "[%s] Silent for %.0fs (threshold %dx%ds=%ds) — no reboot capability",
                        cfg.name,
                        silence,
                        cfg.miss_threshold,
                        cfg.ping_interval,
                        threshold,
                    )
                elif state.connected:
                    log.warning(
                        "[%s] Silent for %.0fs (threshold %dx%ds=%ds) — sending reboot",
                        cfg.name,
                        silence,
                        cfg.miss_threshold,
                        cfg.ping_interval,
                        threshold,
                    )
                    state.rebooting = True
                    state.reboot_at = now
                    asyncio.create_task(send_command(state, "reboot"))
                else:
                    log.warning(
                        "[%s] Silent for %.0fs and disconnected — cannot reboot",
                        cfg.name,
                        silence,
                    )
            elif silence > cfg.ping_interval:
                log.info(
                    "[%s] Overdue by %.0fs (last seen %.0fs ago)",
                    cfg.name,
                    silence - cfg.ping_interval,
                    silence,
                )


async def upgrade_scheduler(states: dict[str, DeviceState]) -> None:
    scheduled = [
        s
        for s in states.values()
        if s.config.upgrade_time and not s.config.is_mqtt_only
    ]
    if not scheduled:
        return

    for state in scheduled:
        log.info(
            "[%s] Daily upgrade scheduled at %s",
            state.config.name,
            state.config.upgrade_time,
        )

    while True:
        now = datetime.datetime.now()
        for state in scheduled:
            try:
                h, m = map(int, state.config.upgrade_time.split(":"))
            except ValueError:
                log.error(
                    "[%s] Invalid upgrade_time '%s'",
                    state.config.name,
                    state.config.upgrade_time,
                )
                continue

            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if target <= now:
                target += datetime.timedelta(days=1)

            if (target - now).total_seconds() <= 60:
                log.info("[%s] Triggering scheduled upgrade", state.config.name)
                if state.config.container_device_name and state.config.container_name:
                    by_device_name = {
                        s.config.device_name: s
                        for s in states.values()
                        if not s.config.is_mqtt_only and not s.config.is_http_polled
                    }

                    async def _restart_after_upgrade(
                        success: bool,
                        _state=state,
                        _bdn=by_device_name,
                    ) -> None:
                        if success:
                            log.info(
                                "[%s] Upgrade succeeded — restarting container",
                                _state.config.name,
                            )
                            await send_restart_container(_state, _bdn)
                        else:
                            log.warning(
                                "[%s] Upgrade failed — skipping container restart",
                                _state.config.name,
                            )

                    state.pending_command_callback = _restart_after_upgrade
                asyncio.create_task(send_command(state, "upgrade"))

        await asyncio.sleep(60)


async def upgrade_reboot_scheduler(states: dict[str, DeviceState]) -> None:
    scheduled = [
        s
        for s in states.values()
        if s.config.upgrade_reboot_time and not s.config.is_mqtt_only
    ]
    if not scheduled:
        return

    for state in scheduled:
        log.info(
            "[%s] Daily upgrade+reboot scheduled at %s",
            state.config.name,
            state.config.upgrade_reboot_time,
        )

    while True:
        now = datetime.datetime.now()
        for state in scheduled:
            try:
                h, m = map(int, state.config.upgrade_reboot_time.split(":"))
            except ValueError:
                log.error(
                    "[%s] Invalid upgrade_reboot_time '%s'",
                    state.config.name,
                    state.config.upgrade_reboot_time,
                )
                continue

            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if target <= now:
                target += datetime.timedelta(days=1)

            if (target - now).total_seconds() <= 60:
                log.info("[%s] Triggering scheduled upgrade_reboot", state.config.name)
                asyncio.create_task(send_command(state, "upgrade_reboot"))

        await asyncio.sleep(60)
