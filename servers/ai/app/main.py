#!/usr/bin/env python3
"""Home monitoring watchdog — WebSocket server + MQTT subscriber.

Two device types are supported:

  WebSocket devices — Raspberry Pis running the watchdog client (remote/main.py).
    They connect via wss://, authenticate with a shared token, send heartbeats,
    forward their logs, and await commands (reboot, upgrade, upgrade_reboot).
    Identified by device_name in the config.

  MQTT-only devices — microcontrollers or embedded devices that cannot run the
    WebSocket client (e.g. Lego Train / ESP32). They publish heartbeats to an
    MQTT topic. The server subscribes and updates last_seen; rebooting is not
    possible for these devices.
    Identified by mqtt_topic in the config.

If a device goes silent for miss_threshold × ping_interval seconds the server
sends a reboot command (WebSocket devices) or logs a warning (MQTT-only).
"""

import asyncio
import datetime
import json
import logging
import ssl
import time
import uuid
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Coroutine, Optional

import email as email_lib
import functools
import poplib
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiohttp
import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties
import websockets
import yaml

LOG_FILE = Path("/var/log/home-monitor/watchdog.log")
DEVICE_LOG_FILE = Path("/var/log/home-monitor/devices.log")
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

CERT_DIR = Path("/var/lib/watchdog-server")
CERT_FILE = CERT_DIR / "server.crt"
KEY_FILE = CERT_DIR / "server.key"


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("watchdog")
    logger.setLevel(logging.DEBUG)

    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    logger.addHandler(stream)

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    rotating = RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    rotating.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    logger.addHandler(rotating)

    return logger


log = setup_logging()

_device_log_rotating: Optional[RotatingFileHandler] = None


def get_device_logger(device_name: str) -> logging.Logger:
    global _device_log_rotating
    logger = logging.getLogger(f"device.{device_name}")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if _device_log_rotating is None:
        DEVICE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _device_log_rotating = RotatingFileHandler(
            DEVICE_LOG_FILE, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
        )
        _device_log_rotating.setFormatter(
            logging.Formatter("%(asctime)s [%(name)s] %(levelname)-8s %(message)s", LOG_DATE_FORMAT)
        )
    logger.addHandler(_device_log_rotating)
    return logger


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class DeviceConfig:
    name: str
    # WebSocket device fields
    device_name: str = ""           # slug for WS auth; must match client config
    # MQTT-only device fields
    mqtt_topic: str = ""            # if set, device is monitored via MQTT subscription
    mqtt_device_name: str = ""      # slug for MQTT status publishing; defaults to device_name
    status_retain_ttl: Optional[int] = None  # MQTTv5 message expiry for retained status
    # HTTP-polled device fields
    http_url: str = ""              # if set, device is polled via HTTP GET; 2xx = online
    # Common fields
    ping_interval: int = 60
    miss_threshold: int = 3
    reboot_cooldown: int = 300
    upgrade_reboot_time: Optional[str] = None  # "HH:MM" daily upgrade+reboot (WS devices only)
    upgrade_time: Optional[str] = None         # "HH:MM" daily upgrade, no reboot (WS devices only)
    container_device_name: Optional[str] = None  # device_name of docker host; enables restart_container
    container_name: Optional[str] = None          # docker container name to restart

    def __post_init__(self):
        if not self.device_name:
            self.device_name = self.name
        if not self.mqtt_device_name:
            self.mqtt_device_name = self.device_name

    @property
    def is_mqtt_only(self) -> bool:
        return bool(self.mqtt_topic)

    @property
    def is_http_polled(self) -> bool:
        return bool(self.http_url)


@dataclass
class EmailConfig:
    host: str
    username: str
    password: str
    pop3_port: int = 995
    smtp_port: int = 587
    poll_interval: int = 60
    store_dir: str = "/var/lib/emails"
    sent_retention_days: int = 10  # delete sent/ files older than this many days (0 = keep forever)
    catchall: dict = field(default_factory=dict)  # {domain: catchall_address}


def normalize_email_path(address: str) -> str:
    """Return a filesystem-safe directory name derived from an email address.

    The domain part has dots replaced with underscores; the local part is
    appended unchanged, separated by an underscore:

      user.name@wojcik.com.au  →  wojcik_com_au_user.name
      test@test.com            →  test_com_test
    """
    if "@" not in address:
        return address.replace(".", "_")
    local, domain = address.rsplit("@", 1)
    return f"{domain.replace('.', '_')}_{local}"


COMMAND_TIMEOUT = 660


@dataclass
class DeviceState:
    config: DeviceConfig
    last_seen: float = field(default_factory=time.monotonic)
    last_seen_wall: Optional[datetime.datetime] = None
    last_online_wall: Optional[datetime.datetime] = None
    ever_seen: bool = False
    rebooting: bool = False
    reboot_at: Optional[float] = None
    disabled: bool = False
    pending_command_id: Optional[str] = None
    pending_command_at: Optional[float] = None
    pending_command_callback: Optional[Callable[[bool], Coroutine[Any, Any, None]]] = None
    ws: Optional[object] = None

    @property
    def connected(self) -> bool:
        return self.ws is not None


def load_config(path: Path) -> tuple[dict, Optional[dict], list[DeviceConfig], int, int, Optional[EmailConfig]]:
    with open(path) as f:
        raw = yaml.safe_load(f)
    server_cfg = raw["server"]
    mqtt_cfg = raw.get("mqtt")   # optional — only needed for MQTT devices or status publishing
    devices = [DeviceConfig(**d) for d in raw["devices"]]
    log_level = logging.getLevelName(raw.get("log_level", "INFO").upper())
    status_interval = int(raw.get("status_interval", 10))
    email_cfg: Optional[EmailConfig] = None
    if "email" in raw:
        email_cfg = EmailConfig(**raw["email"])
    return server_cfg, mqtt_cfg, devices, log_level, status_interval, email_cfg


# ---------------------------------------------------------------------------
# TLS
# ---------------------------------------------------------------------------

def ensure_tls_cert() -> ssl.SSLContext:
    if not CERT_FILE.exists() or not KEY_FILE.exists():
        raise FileNotFoundError(
            f"TLS certificate not found at {CERT_FILE} — "
            "it should have been generated by start.sh at container startup"
        )
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT_FILE, KEY_FILE)
    return ctx


# ---------------------------------------------------------------------------
# MQTT bridge (paho callbacks → asyncio Queue)
# ---------------------------------------------------------------------------

class MqttBridge:
    def __init__(
        self,
        broker: str,
        port: int,
        loop: asyncio.AbstractEventLoop,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self._loop = loop
        self._queue: asyncio.Queue = asyncio.Queue()
        self._subscriptions: list[str] = []
        self._broker = broker
        self._port = port

        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
        if username:
            self._client.username_pw_set(username, password)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

    def subscribe(self, topic: str) -> None:
        self._subscriptions.append(topic)

    def _on_connect(self, client, userdata, connect_flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("MQTT connect failed: %s", reason_code)
            return
        log.info("MQTT connected to %s:%s", self._broker, self._port)
        for topic in self._subscriptions:
            client.subscribe(topic)
            log.info("MQTT subscribed to %s", topic)

    def _on_message(self, client, userdata, msg):
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (msg.topic, msg.payload))

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        log.warning("MQTT disconnected (reason: %s) — paho will reconnect", reason_code)

    async def messages(self):
        while True:
            yield await self._queue.get()

    def publish(self, topic: str, payload: str, retain: bool = False, ttl: Optional[int] = None) -> None:
        props = None
        if ttl is not None:
            props = Properties(PacketTypes.PUBLISH)
            props.MessageExpiryInterval = ttl
        self._client.publish(topic, payload, retain=retain, properties=props)

    def start(self) -> None:
        self._client.connect_async(self._broker, self._port)
        self._client.loop_start()

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()


# ---------------------------------------------------------------------------
# MQTT status publishing
# ---------------------------------------------------------------------------

def publish_status(bridge: MqttBridge, state: DeviceState) -> None:
    cfg = state.config
    now = time.monotonic()
    silence = now - state.last_seen
    threshold = cfg.miss_threshold * cfg.ping_interval

    if state.disabled or state.rebooting or silence >= threshold:
        status = "Offline"
    elif not state.ever_seen:
        status = "Unknown"
    else:
        status = "Online"

    now_wall = datetime.datetime.now(datetime.timezone.utc)
    if status == "Online":
        state.last_online_wall = now_wall

    def _iso(dt: Optional[datetime.datetime]) -> Optional[str]:
        return dt.isoformat() if dt is not None else None

    payload = json.dumps({
        "lastStatus": status,
        "lastStatusTimestamp": _iso(state.last_seen_wall),
        "lastOnlineTimestamp": _iso(state.last_online_wall),
    })

    bridge.publish(
        f"status/{cfg.mqtt_device_name}",
        payload,
        retain=True,
        ttl=cfg.status_retain_ttl,
    )
    log.debug("[%s] Status → status/%s = %s", cfg.name, cfg.mqtt_device_name, status)


async def status_publisher(bridge: MqttBridge, states: dict[str, DeviceState], interval: int) -> None:
    """Publishes status for all devices to MQTT every `interval` seconds."""
    while True:
        await asyncio.sleep(interval)
        for state in states.values():
            publish_status(bridge, state)


# ---------------------------------------------------------------------------
# MQTT listener (for MQTT-only devices)
# ---------------------------------------------------------------------------

async def mqtt_listener(bridge: MqttBridge, states: dict[str, DeviceState]) -> None:
    topic_map = {
        s.config.mqtt_topic: s
        for s in states.values()
        if s.config.is_mqtt_only
    }
    async for topic, payload in bridge.messages():
        state = topic_map.get(topic)
        if state:
            if state.disabled:
                log.debug("[%s] MQTT message received but device is disabled — ignoring", state.config.name)
                continue
            now = time.monotonic()
            was_online = state.ever_seen and (now - state.last_seen) < (state.config.miss_threshold * state.config.ping_interval)
            state.last_seen = now
            state.last_seen_wall = datetime.datetime.now(datetime.timezone.utc)
            state.ever_seen = True
            if not was_online:
                log.info("[%s] Device back online (MQTT)", state.config.name)
                publish_status(bridge, state)
            else:
                log.debug("[%s] MQTT heartbeat on '%s'", state.config.name, topic)
        else:
            log.debug("Untracked MQTT topic: %s", topic)


# ---------------------------------------------------------------------------
# HTTP poller (for HTTP-polled devices)
# ---------------------------------------------------------------------------

HTTP_TIMEOUT = aiohttp.ClientTimeout(total=10)


async def _http_check(session: aiohttp.ClientSession, state: DeviceState, bridge: Optional[MqttBridge]) -> None:
    cfg = state.config
    try:
        async with session.get(cfg.http_url, timeout=HTTP_TIMEOUT, ssl=False) as resp:
            if 200 <= resp.status < 300:
                now = time.monotonic()
                was_online = state.ever_seen and (now - state.last_seen) < (cfg.miss_threshold * cfg.ping_interval)
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
                log.warning("[%s] HTTP check returned %d — treating as offline", cfg.name, resp.status)
    except Exception as exc:
        log.debug("[%s] HTTP check failed: %s", cfg.name, exc)


async def http_pollers(states: dict[str, DeviceState], bridge: Optional[MqttBridge]) -> None:
    """Runs one polling loop per HTTP-polled device."""
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
            state.config.name, state.config.http_url, state.config.ping_interval,
        )

    await asyncio.gather(*[poll_device(s) for s in http_states])


# ---------------------------------------------------------------------------
# WebSocket handler (for WebSocket devices)
# ---------------------------------------------------------------------------

class WatchdogServer:
    def __init__(self, states: dict[str, DeviceState], token: str, bridge: Optional[MqttBridge] = None):
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

            # Admin CLI connection
            if msg.get("type") == "admin_auth":
                if msg.get("token") != self._token:
                    await ws.send(json.dumps({"type": "auth_fail", "reason": "invalid token"}))
                    log.warning("Admin auth failed from %s — bad token", ws.remote_address)
                    return
                await ws.send(json.dumps({"type": "auth_ok"}))
                log.info("Admin client connected from %s", ws.remote_address)
                await self._handle_admin(ws)
                return

            if msg.get("type") != "auth":
                await ws.send(json.dumps({"type": "auth_fail", "reason": "expected auth message"}))
                return

            if msg.get("token") != self._token:
                await ws.send(json.dumps({"type": "auth_fail", "reason": "invalid token"}))
                log.warning("Auth failed from %s — bad token", ws.remote_address)
                return

            device_name = msg.get("device_name", "").strip()
            state = self._by_device_name.get(device_name)
            if not state:
                await ws.send(json.dumps({"type": "auth_fail", "reason": f"unknown device: {device_name}"}))
                log.warning("Auth failed — unknown device '%s' from %s", device_name, ws.remote_address)
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
                state.config.name, cmd_id, success,
                (output or "")[:200], (error or "")[:200],
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
        ALLOWED_COMMANDS = {"reboot", "upgrade", "upgrade_reboot", "restart_container"}
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
                                "mqtt" if s.config.is_mqtt_only else
                                "http" if s.config.is_http_polled else
                                "websocket"
                            ),
                            "connected": s.connected,
                            "ever_seen": s.ever_seen,
                            "disabled": s.disabled,
                        }
                        for s in self._states.values()
                    ]
                    await ws.send(json.dumps({"type": "device_list", "devices": devices}))

                elif mtype == "admin_command":
                    device_name = msg.get("device_name", "")
                    command = msg.get("command", "")

                    if command not in ALLOWED_COMMANDS:
                        await ws.send(json.dumps({"type": "error", "reason": f"unknown command '{command}' — allowed: {', '.join(ALLOWED_COMMANDS)}"}))
                        continue

                    state = self._by_device_name.get(device_name)
                    if not state:
                        await ws.send(json.dumps({"type": "error", "reason": f"unknown device '{device_name}'"}))
                        continue

                    if command == "restart_container":
                        if not state.config.container_device_name:
                            await ws.send(json.dumps({"type": "error", "reason": f"'{device_name}' has no container_device_name configured"}))
                            continue
                        sent = await send_restart_container(state, self._by_device_name)
                        if sent:
                            await ws.send(json.dumps({"type": "ok", "message": f"restart_container sent for {state.config.name} via {state.config.container_device_name}"}))
                            log.info("Admin sent 'restart_container' for [%s] via [%s]", state.config.name, state.config.container_device_name)
                        else:
                            await ws.send(json.dumps({"type": "error", "reason": "failed to send restart_container"}))
                        continue

                    if not state.connected:
                        await ws.send(json.dumps({"type": "error", "reason": f"'{device_name}' is not connected"}))
                        continue

                    sent = await send_command(state, command)
                    if sent:
                        await ws.send(json.dumps({"type": "ok", "message": f"Command '{command}' sent to {state.config.name}"}))
                        log.info("Admin sent '%s' to [%s]", command, state.config.name)
                    else:
                        await ws.send(json.dumps({"type": "error", "reason": "failed to send command"}))

                else:
                    await ws.send(json.dumps({"type": "error", "reason": f"unknown admin message type '{mtype}'"}))

        except Exception as exc:
            log.warning("Admin client error: %s", exc)
        finally:
            log.info("Admin client disconnected")


# ---------------------------------------------------------------------------
# Command sending
# ---------------------------------------------------------------------------

async def send_command(state: DeviceState, command: str) -> bool:
    if not state.connected:
        log.warning("[%s] Cannot send '%s' — device not connected", state.config.name, command)
        return False

    cmd_id = str(uuid.uuid4())
    state.pending_command_id = cmd_id
    state.pending_command_at = time.monotonic()
    try:
        await state.ws.send(json.dumps({
            "type": "command",
            "command_id": cmd_id,
            "command": command,
        }))
        log.info("[%s] Sent command '%s' (id=%s)", state.config.name, command, cmd_id)
        return True
    except Exception as exc:
        log.warning("[%s] Failed to send '%s': %s", state.config.name, command, exc)
        state.pending_command_id = None
        state.pending_command_at = None
        return False


async def send_restart_container(container_state: DeviceState, by_device_name: dict[str, "DeviceState"]) -> bool:
    """Route a restart_container command to the docker host device."""
    host_name = container_state.config.container_device_name
    cname = container_state.config.container_name
    if not host_name or not cname:
        log.warning("[%s] restart_container: container_device_name/container_name not configured", container_state.config.name)
        return False
    host_state = by_device_name.get(host_name)
    if not host_state:
        log.warning("[%s] restart_container: host device '%s' not found", container_state.config.name, host_name)
        return False
    if not host_state.connected:
        log.warning("[%s] restart_container: host device '%s' not connected", container_state.config.name, host_name)
        return False
    return await send_command(host_state, f"restart_container:{cname}")


# ---------------------------------------------------------------------------
# Email (POP3 receive + SMTP send)
# ---------------------------------------------------------------------------

def _fetch_emails_sync(cfg: EmailConfig) -> list[tuple[email_lib.message.Message, bytes]]:
    """Fetch and delete all messages from POP3 server (synchronous — run in executor)."""
    results: list[tuple[email_lib.message.Message, bytes]] = []
    conn = poplib.POP3_SSL(cfg.host, cfg.pop3_port)
    try:
        conn.user(cfg.username)
        conn.pass_(cfg.password)
        count, _ = conn.stat()
        for i in range(1, count + 1):
            raw_lines = conn.retr(i)[1]
            raw = b"\r\n".join(raw_lines)
            results.append((email_lib.message_from_bytes(raw), raw))
            conn.dele(i)
    finally:
        conn.quit()
    return results


def _forward_email_sync(cfg: EmailConfig, to: str, raw: bytes) -> None:
    """Forward a raw email to `to` via SMTP STARTTLS (synchronous — run in executor)."""
    with smtplib.SMTP(cfg.host, cfg.smtp_port) as smtp:
        smtp.starttls()
        smtp.login(cfg.username, cfg.password)
        smtp.sendmail(cfg.username, to, raw)


async def email_poller(cfg: EmailConfig) -> None:
    """Poll the POP3 mailbox every cfg.poll_interval seconds.

    Each message is written atomically to inbox/ via a .tmp-then-rename so
    inbox_processor only ever sees fully written files.
    """
    loop = asyncio.get_running_loop()
    inbox_dir = Path(cfg.store_dir) / normalize_email_path(cfg.username) / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    log.info(
        "Email poller started — polling %s:%d every %ds, inbox: %s",
        cfg.host, cfg.pop3_port, cfg.poll_interval, inbox_dir,
    )
    while True:
        try:
            results = await loop.run_in_executor(None, functools.partial(_fetch_emails_sync, cfg))
            for msg, raw in results:
                subject = msg.get("Subject", "(no subject)")
                sender = msg.get("From", "(unknown)")
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                tmp_path = inbox_dir / f"{timestamp}.eml.tmp"
                eml_path = inbox_dir / f"{timestamp}.eml"
                tmp_path.write_bytes(raw)
                tmp_path.rename(eml_path)
                log.info("Email received from %s: %s → inbox/%s", sender, subject, eml_path.name)
        except Exception as exc:
            log.warning("Email poll error: %s", exc)
        await asyncio.sleep(cfg.poll_interval)


INBOX_SCAN_INTERVAL = 10  # seconds between inbox scans


async def inbox_processor(cfg: EmailConfig) -> None:
    """Scan inbox/ every INBOX_SCAN_INTERVAL seconds and forward any .eml files.

    Handles both emails written by email_poller and any files placed manually.
    Successfully forwarded files are moved to sent/; failures stay in inbox/
    and are retried on the next scan.
    """
    loop = asyncio.get_running_loop()
    base_dir = Path(cfg.store_dir) / normalize_email_path(cfg.username)
    inbox_dir = base_dir / "inbox"
    sent_dir = base_dir / "sent"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    sent_dir.mkdir(parents=True, exist_ok=True)

    domain = cfg.username.split("@")[1] if "@" in cfg.username else ""
    catchall_to: Optional[str] = cfg.catchall.get(domain) if cfg.catchall else None

    if catchall_to:
        log.info("Inbox processor started — forwarding %s → %s, scanning every %ds", domain, catchall_to, INBOX_SCAN_INTERVAL)
    else:
        log.info("Inbox processor: no catchall for '%s' — inbox scanning disabled", domain)
        return

    while True:
        try:
            for eml_path in sorted(inbox_dir.glob("*.eml")):
                raw = eml_path.read_bytes()
                try:
                    await loop.run_in_executor(
                        None, functools.partial(_forward_email_sync, cfg, catchall_to, raw)
                    )
                    eml_path.rename(sent_dir / eml_path.name)
                    log.info("Inbox processor: forwarded to %s → sent/%s", catchall_to, eml_path.name)
                except Exception as fwd_exc:
                    log.warning(
                        "Inbox processor: forward to %s failed — %s will retry: %s",
                        catchall_to, eml_path.name, fwd_exc,
                    )
        except Exception as exc:
            log.warning("Inbox processor error: %s", exc)
        await asyncio.sleep(INBOX_SCAN_INTERVAL)


SENT_CLEAN_INTERVAL = 3600  # seconds between sent/ cleanup scans


async def sent_cleaner(cfg: EmailConfig) -> None:
    """Delete files from sent/ that are older than cfg.sent_retention_days days.

    Runs once per hour. If sent_retention_days is 0, does nothing.
    """
    if cfg.sent_retention_days <= 0:
        log.info("Sent cleaner: retention disabled (sent_retention_days=0)")
        return

    sent_dir = Path(cfg.store_dir) / normalize_email_path(cfg.username) / "sent"
    sent_dir.mkdir(parents=True, exist_ok=True)
    log.info("Sent cleaner started — deleting sent/ files older than %d days, checking every %ds",
             cfg.sent_retention_days, SENT_CLEAN_INTERVAL)

    while True:
        try:
            cutoff = datetime.datetime.now().timestamp() - cfg.sent_retention_days * 86400
            for eml_path in sent_dir.glob("*.eml"):
                if eml_path.stat().st_mtime < cutoff:
                    eml_path.unlink()
                    log.info("Sent cleaner: deleted %s (older than %d days)", eml_path.name, cfg.sent_retention_days)
        except Exception as exc:
            log.warning("Sent cleaner error: %s", exc)
        await asyncio.sleep(SENT_CLEAN_INTERVAL)


def _send_email_sync(cfg: EmailConfig, to: str, subject: str, body: str) -> None:
    """Send an email via SMTP with STARTTLS (synchronous — run in executor)."""
    msg = MIMEMultipart()
    msg["From"] = cfg.username
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    with smtplib.SMTP(cfg.host, cfg.smtp_port) as smtp:
        smtp.starttls()
        smtp.login(cfg.username, cfg.password)
        smtp.send_message(msg)


async def send_email(cfg: EmailConfig, to: str, subject: str, body: str) -> bool:
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, functools.partial(_send_email_sync, cfg, to, subject, body))
        log.info("Email sent to %s: %s", to, subject)
        return True
    except Exception as exc:
        log.warning("Failed to send email to %s: %s", to, exc)
        return False


# ---------------------------------------------------------------------------
# Watchdog loop
# ---------------------------------------------------------------------------

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
                    log.debug("[%s] Cooldown — %ds remaining", cfg.name, cfg.reboot_cooldown - elapsed)
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
                        cfg.name, silence, cfg.miss_threshold, cfg.ping_interval, threshold,
                    )
                elif state.connected:
                    log.warning(
                        "[%s] Silent for %.0fs (threshold %dx%ds=%ds) — sending reboot",
                        cfg.name, silence, cfg.miss_threshold, cfg.ping_interval, threshold,
                    )
                    state.rebooting = True
                    state.reboot_at = now
                    asyncio.create_task(send_command(state, "reboot"))
                else:
                    log.warning(
                        "[%s] Silent for %.0fs and disconnected — cannot reboot",
                        cfg.name, silence,
                    )
            elif silence > cfg.ping_interval:
                log.info(
                    "[%s] Overdue by %.0fs (last seen %.0fs ago)",
                    cfg.name, silence - cfg.ping_interval, silence,
                )


# ---------------------------------------------------------------------------
# Scheduled upgrade (no reboot)
# ---------------------------------------------------------------------------

async def upgrade_scheduler(states: dict[str, DeviceState]) -> None:
    scheduled = [
        s for s in states.values()
        if s.config.upgrade_time and not s.config.is_mqtt_only
    ]
    if not scheduled:
        return

    for state in scheduled:
        log.info("[%s] Daily upgrade scheduled at %s", state.config.name, state.config.upgrade_time)

    while True:
        now = datetime.datetime.now()
        for state in scheduled:
            try:
                h, m = map(int, state.config.upgrade_time.split(":"))
            except ValueError:
                log.error("[%s] Invalid upgrade_time '%s'", state.config.name, state.config.upgrade_time)
                continue

            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if target <= now:
                target += datetime.timedelta(days=1)

            if (target - now).total_seconds() <= 60:
                log.info("[%s] Triggering scheduled upgrade", state.config.name)
                if state.config.container_device_name and state.config.container_name:
                    by_device_name = {
                        s.config.device_name: s for s in states.values()
                        if not s.config.is_mqtt_only and not s.config.is_http_polled
                    }

                    async def _restart_after_upgrade(success: bool, _state=state, _bdn=by_device_name) -> None:
                        if success:
                            log.info("[%s] Upgrade succeeded — restarting container", _state.config.name)
                            await send_restart_container(_state, _bdn)
                        else:
                            log.warning("[%s] Upgrade failed — skipping container restart", _state.config.name)

                    state.pending_command_callback = _restart_after_upgrade
                asyncio.create_task(send_command(state, "upgrade"))

        await asyncio.sleep(60)


# ---------------------------------------------------------------------------
# Scheduled upgrade + reboot
# ---------------------------------------------------------------------------

async def upgrade_reboot_scheduler(states: dict[str, DeviceState]) -> None:
    scheduled = [
        s for s in states.values()
        if s.config.upgrade_reboot_time and not s.config.is_mqtt_only
    ]
    if not scheduled:
        return

    for state in scheduled:
        log.info("[%s] Daily upgrade+reboot scheduled at %s", state.config.name, state.config.upgrade_reboot_time)

    while True:
        now = datetime.datetime.now()
        for state in scheduled:
            try:
                h, m = map(int, state.config.upgrade_reboot_time.split(":"))
            except ValueError:
                log.error("[%s] Invalid upgrade_reboot_time '%s'", state.config.name, state.config.upgrade_reboot_time)
                continue

            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if target <= now:
                target += datetime.timedelta(days=1)

            if (target - now).total_seconds() <= 60:
                log.info("[%s] Triggering scheduled upgrade_reboot", state.config.name)
                asyncio.create_task(send_command(state, "upgrade_reboot"))

        await asyncio.sleep(60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    config_path = Path("/run/secrets/config.yaml")
    if not config_path.exists():
        config_path = Path(__file__).parent / "config.yaml"

    log.info("Loading config from %s", config_path)
    server_cfg, mqtt_cfg, devices, log_level, status_interval, email_cfg = load_config(config_path)
    log.setLevel(log_level)
    log.info("Log level set to %s", logging.getLevelName(log_level))

    states: dict[str, DeviceState] = {d.name: DeviceState(config=d) for d in devices}

    for dev in devices:
        if dev.is_mqtt_only:
            log.info(
                "Watching [%s] via MQTT topic '%s' (alert after %dx%ds silence)",
                dev.name, dev.mqtt_topic, dev.miss_threshold, dev.ping_interval,
            )
        elif dev.is_http_polled:
            pass  # logged by http_pollers() at startup
        else:
            log.info(
                "Watching [%s] via WebSocket (device_name=%s, reboot after %dx%ds silence)",
                dev.name, dev.device_name, dev.miss_threshold, dev.ping_interval,
            )

    token: str = server_cfg["token"]
    host: str = server_cfg.get("host", "0.0.0.0")
    port: int = int(server_cfg.get("port", 8765))

    tasks: list = [
        watchdog_loop(states),
        upgrade_scheduler(states),
        upgrade_reboot_scheduler(states),
    ]

    bridge: Optional[MqttBridge] = None
    if mqtt_cfg:
        loop = asyncio.get_running_loop()
        bridge = MqttBridge(
            broker=mqtt_cfg["broker"],
            port=int(mqtt_cfg.get("port", 1883)),
            loop=loop,
            username=mqtt_cfg.get("username"),
            password=mqtt_cfg.get("password"),
        )
        mqtt_devices = [d for d in devices if d.is_mqtt_only]
        for dev in mqtt_devices:
            bridge.subscribe(dev.mqtt_topic)
        bridge.start()
        if mqtt_devices:
            tasks.append(mqtt_listener(bridge, states))
        tasks.append(status_publisher(bridge, states, status_interval))
        log.info("MQTT bridge started — status publishing every %ds", status_interval)
        # Publish initial state for all devices
        for state in states.values():
            bridge.publish(
                f"status/{state.config.mqtt_device_name}",
                json.dumps({"lastStatus": "Initialising", "lastStatusTimestamp": None, "lastOnlineTimestamp": None}),
                retain=True,
                ttl=state.config.status_retain_ttl,
            )
    else:
        mqtt_devices = [d for d in devices if d.is_mqtt_only]
        if mqtt_devices:
            log.error("MQTT devices configured but no 'mqtt' section in config — they will not be monitored")

    tasks.append(http_pollers(states, bridge))

    if email_cfg:
        tasks.append(email_poller(email_cfg))
        tasks.append(inbox_processor(email_cfg))
        tasks.append(sent_cleaner(email_cfg))
        log.info("Email enabled — %s (POP3 port %d, SMTP port %d)", email_cfg.host, email_cfg.pop3_port, email_cfg.smtp_port)
    else:
        log.info("No email config — email polling disabled")

    ssl_ctx = ensure_tls_cert()
    ws_server = WatchdogServer(states, token, bridge)

    log.info("WebSocket server listening on %s:%d (wss)", host, port)
    try:
        async with websockets.serve(ws_server.handle, host, port, ssl=ssl_ctx):
            await asyncio.gather(*tasks)
    finally:
        if bridge:
            bridge.stop()


if __name__ == "__main__":
    asyncio.run(main())
