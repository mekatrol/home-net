import asyncio
import datetime
import json
import logging
import time
from typing import Optional

from watchdog_commands import send_command, send_restart_container
from watchdog_logging import get_device_logger, log
from watchdog_models import DeviceState
from watchdog_mqtt import MqttBridge, publish_status


class WatchdogServer:
    def __init__(
        self,
        states: dict[str, DeviceState],
        token: str,
        bridge: Optional[MqttBridge] = None,
    ):
        self._states = states
        self._token = token
        self._bridge = bridge
        self._by_device_name: dict[str, DeviceState] = {
            s.config.device_name: s
            for s in states.values()
            if not s.config.is_mqtt_only and not s.config.is_http_polled
        }

    async def handle(self, ws) -> None:
        state: Optional[DeviceState] = None
        try:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=15)
            except asyncio.TimeoutError:
                log.warning("Client %s timed out during auth", ws.remote_address)
                return

            msg = json.loads(raw)

            if msg.get("type") == "admin_auth":
                if msg.get("token") != self._token:
                    await ws.send(
                        json.dumps({"type": "auth_fail", "reason": "invalid token"})
                    )
                    log.warning(
                        "Admin auth failed from %s — bad token", ws.remote_address
                    )
                    return
                await ws.send(json.dumps({"type": "auth_ok"}))
                log.info("Admin client connected from %s", ws.remote_address)
                await self._handle_admin(ws)
                return

            if msg.get("type") != "auth":
                await ws.send(
                    json.dumps({"type": "auth_fail", "reason": "expected auth message"})
                )
                return

            if msg.get("token") != self._token:
                await ws.send(
                    json.dumps({"type": "auth_fail", "reason": "invalid token"})
                )
                log.warning("Auth failed from %s — bad token", ws.remote_address)
                return

            device_name = msg.get("device_name", "").strip()
            state = self._by_device_name.get(device_name)
            if not state:
                await ws.send(
                    json.dumps(
                        {
                            "type": "auth_fail",
                            "reason": f"unknown device: {device_name}",
                        }
                    )
                )
                log.warning(
                    "Auth failed — unknown device '%s' from %s",
                    device_name,
                    ws.remote_address,
                )
                return

            state.ws = ws
            state.last_seen = time.monotonic()
            state.last_seen_wall = datetime.datetime.now(datetime.timezone.utc)
            state.ever_seen = True
            await ws.send(json.dumps({"type": "auth_ok"}))
            log.info("[%s] Connected from %s", state.config.name, ws.remote_address)
            if self._bridge:
                publish_status(self._bridge, state)

            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                self._handle_message(state, msg)

        except Exception as exc:
            name = state.config.name if state else "?"
            log.warning("[%s] WebSocket error: %s", name, exc)
        finally:
            if state:
                state.ws = None
                log.info("[%s] Disconnected", state.config.name)
                if self._bridge:
                    publish_status(self._bridge, state)

    def _handle_message(self, state: DeviceState, msg: dict) -> None:
        mtype = msg.get("type")

        if mtype == "heartbeat":
            state.last_seen = time.monotonic()
            state.last_seen_wall = datetime.datetime.now(datetime.timezone.utc)
            state.ever_seen = True
            log.debug("[%s] Heartbeat", state.config.name)

        elif mtype == "log":
            device_log = get_device_logger(state.config.device_name)
            level_name = msg.get("level", "info").upper()
            level = logging.getLevelName(level_name)
            if not isinstance(level, int):
                level = logging.INFO
            device_log.log(level, msg.get("message", ""))

        elif mtype == "command_result":
            cmd_id = msg.get("command_id")
            success = msg.get("success", False)
            output = msg.get("output", "")
            error = msg.get("error", "")
            log.info(
                "[%s] Command result (id=%s) success=%s output=%r error=%r",
                state.config.name,
                cmd_id,
                success,
                (output or "")[:200],
                (error or "")[:200],
            )
            if state.pending_command_id == cmd_id:
                cb = state.pending_command_callback
                state.pending_command_id = None
                state.pending_command_at = None
                state.pending_command_callback = None
                if cb:
                    asyncio.create_task(cb(success))

        else:
            log.debug("[%s] Unknown message type: %s", state.config.name, mtype)

    async def _handle_admin(self, ws) -> None:
        allowed_commands = {"reboot", "upgrade", "upgrade_reboot", "restart_container"}
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                mtype = msg.get("type")

                if mtype == "admin_list":
                    devices = [
                        {
                            "name": s.config.name,
                            "device_name": s.config.device_name,
                            "type": (
                                "mqtt"
                                if s.config.is_mqtt_only
                                else "http"
                                if s.config.is_http_polled
                                else "websocket"
                            ),
                            "connected": s.connected,
                            "ever_seen": s.ever_seen,
                            "disabled": s.disabled,
                        }
                        for s in self._states.values()
                    ]
                    await ws.send(
                        json.dumps({"type": "device_list", "devices": devices})
                    )

                elif mtype == "admin_command":
                    device_name = msg.get("device_name", "")
                    command = msg.get("command", "")

                    if command not in allowed_commands:
                        await ws.send(
                            json.dumps(
                                {
                                    "type": "error",
                                    "reason": (
                                        f"unknown command '{command}' — allowed: "
                                        f"{', '.join(allowed_commands)}"
                                    ),
                                }
                            )
                        )
                        continue

                    state = self._by_device_name.get(device_name)
                    if not state:
                        await ws.send(
                            json.dumps(
                                {
                                    "type": "error",
                                    "reason": f"unknown device '{device_name}'",
                                }
                            )
                        )
                        continue

                    if command == "restart_container":
                        if not state.config.container_device_name:
                            await ws.send(
                                json.dumps(
                                    {
                                        "type": "error",
                                        "reason": (
                                            f"'{device_name}' has no "
                                            "container_device_name configured"
                                        ),
                                    }
                                )
                            )
                            continue
                        sent = await send_restart_container(state, self._by_device_name)
                        if sent:
                            await ws.send(
                                json.dumps(
                                    {
                                        "type": "ok",
                                        "message": (
                                            "restart_container sent for "
                                            f"{state.config.name} via "
                                            f"{state.config.container_device_name}"
                                        ),
                                    }
                                )
                            )
                            log.info(
                                "Admin sent 'restart_container' for [%s] via [%s]",
                                state.config.name,
                                state.config.container_device_name,
                            )
                        else:
                            await ws.send(
                                json.dumps(
                                    {
                                        "type": "error",
                                        "reason": "failed to send restart_container",
                                    }
                                )
                            )
                        continue

                    if not state.connected:
                        await ws.send(
                            json.dumps(
                                {
                                    "type": "error",
                                    "reason": f"'{device_name}' is not connected",
                                }
                            )
                        )
                        continue

                    sent = await send_command(state, command)
                    if sent:
                        await ws.send(
                            json.dumps(
                                {
                                    "type": "ok",
                                    "message": f"Command '{command}' sent to {state.config.name}",
                                }
                            )
                        )
                        log.info("Admin sent '%s' to [%s]", command, state.config.name)
                    else:
                        await ws.send(
                            json.dumps(
                                {"type": "error", "reason": "failed to send command"}
                            )
                        )

                else:
                    await ws.send(
                        json.dumps(
                            {
                                "type": "error",
                                "reason": f"unknown admin message type '{mtype}'",
                            }
                        )
                    )

        except Exception as exc:
            log.warning("Admin client error: %s", exc)
        finally:
            log.info("Admin client disconnected")
