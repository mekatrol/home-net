import json
import time
import uuid

from watchdog_logging import log
from watchdog_models import DeviceState


async def send_command(state: DeviceState, command: str) -> bool:
    if not state.connected:
        log.warning(
            "[%s] Cannot send '%s' — device not connected", state.config.name, command
        )
        return False

    cmd_id = str(uuid.uuid4())
    state.pending_command_id = cmd_id
    state.pending_command_at = time.monotonic()
    try:
        await state.ws.send(
            json.dumps(
                {
                    "type": "command",
                    "command_id": cmd_id,
                    "command": command,
                }
            )
        )
        log.info("[%s] Sent command '%s' (id=%s)", state.config.name, command, cmd_id)
        return True
    except Exception as exc:
        log.warning("[%s] Failed to send '%s': %s", state.config.name, command, exc)
        state.pending_command_id = None
        state.pending_command_at = None
        return False


async def send_restart_container(
    container_state: DeviceState,
    by_device_name: dict[str, DeviceState],
) -> bool:
    host_name = container_state.config.container_device_name
    cname = container_state.config.container_name
    if not host_name or not cname:
        log.warning(
            "[%s] restart_container: container_device_name/container_name not configured",
            container_state.config.name,
        )
        return False
    host_state = by_device_name.get(host_name)
    if not host_state:
        log.warning(
            "[%s] restart_container: host device '%s' not found",
            container_state.config.name,
            host_name,
        )
        return False
    if not host_state.connected:
        log.warning(
            "[%s] restart_container: host device '%s' not connected",
            container_state.config.name,
            host_name,
        )
        return False
    return await send_command(host_state, f"restart_container:{cname}")
