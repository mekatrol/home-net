#!/usr/bin/env python3
"""Home monitoring watchdog.

Listens for MQTT ping topics from registered devices. If a device misses
`miss_threshold` consecutive expected pings it is rebooted via SSH.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

import asyncssh
import paho.mqtt.client as mqtt
import yaml

LOG_FILE = Path("/var/log/home-monitor/watchdog.log")
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("watchdog")
    logger.setLevel(logging.INFO)

    # stdout — keeps docker logs working
    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    logger.addHandler(stream)

    # rotating file — 5 × 1 MB files kept, readable by the web layer later
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    rotating = RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    rotating.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    logger.addHandler(rotating)

    return logger


log = setup_logging()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class DeviceConfig:
    name: str
    host: str
    mqtt_topic: str
    ssh_user: str
    ssh_key: str                  # path to private key file
    ping_interval: int = 60       # seconds between expected pings
    miss_threshold: int = 3       # missed pings before reboot
    reboot_cooldown: int = 300    # seconds to suppress alerts after a reboot


@dataclass
class DeviceState:
    config: DeviceConfig
    last_seen: float = field(default_factory=time.monotonic)
    rebooting: bool = False
    reboot_at: Optional[float] = None


def load_config(path: Path) -> tuple[dict, list[DeviceConfig]]:
    with open(path) as f:
        raw = yaml.safe_load(f)
    mqtt_cfg = raw["mqtt"]
    devices = [DeviceConfig(**d) for d in raw["devices"]]
    return mqtt_cfg, devices


# ---------------------------------------------------------------------------
# MQTT bridge  (paho callbacks → asyncio Queue)
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

        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if username:
            self._client.username_pw_set(username, password)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

    def subscribe(self, topic: str) -> None:
        self._subscriptions.append(topic)

    # --- paho callbacks (run in paho's background thread) ---

    def _on_connect(self, client, userdata, connect_flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("MQTT connect failed: %s", reason_code)
            return
        log.info("MQTT connected to %s:%s", self._broker, self._port)
        for topic in self._subscriptions:
            client.subscribe(topic)
            log.info("Subscribed to %s", topic)

    def _on_message(self, client, userdata, msg):
        # Bridge into asyncio safely from paho's thread
        self._loop.call_soon_threadsafe(
            self._queue.put_nowait, (msg.topic, msg.payload)
        )

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        log.warning("MQTT disconnected (reason: %s) — paho will reconnect", reason_code)

    # --- asyncio interface ---

    async def messages(self):
        """Async generator yielding (topic, payload) tuples."""
        while True:
            yield await self._queue.get()

    def start(self) -> None:
        self._client.connect_async(self._broker, self._port)
        self._client.loop_start()

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()


# ---------------------------------------------------------------------------
# SSH reboot
# ---------------------------------------------------------------------------

async def ssh_reboot(device: DeviceConfig) -> None:
    log.info("[%s] SSH reboot → %s@%s", device.name, device.ssh_user, device.host)
    try:
        async with asyncssh.connect(
            device.host,
            username=device.ssh_user,
            client_keys=[device.ssh_key],
            known_hosts=None,           # fine for a trusted home network
            connect_timeout=15,
        ) as conn:
            # The remote authorized_keys forces all connections through the
            # watchdog dispatcher, which maps "reboot" → sudo /sbin/reboot
            await conn.run("reboot", check=False, timeout=10)
        log.info("[%s] Reboot command sent", device.name)
    except (asyncssh.Error, OSError, asyncio.TimeoutError) as exc:
        log.error("[%s] SSH reboot failed: %s", device.name, exc)


# ---------------------------------------------------------------------------
# Watchdog loop
# ---------------------------------------------------------------------------

async def watchdog_loop(states: dict[str, DeviceState]) -> None:
    """Checks every 10 s whether any device has gone silent long enough to reboot."""
    while True:
        await asyncio.sleep(10)
        now = time.monotonic()

        for state in states.values():
            cfg = state.config

            if state.rebooting:
                elapsed_since_reboot = now - state.reboot_at
                if elapsed_since_reboot < cfg.reboot_cooldown:
                    remaining = cfg.reboot_cooldown - elapsed_since_reboot
                    log.debug(
                        "[%s] Post-reboot cooldown — %ds remaining", cfg.name, remaining
                    )
                    continue
                log.info("[%s] Cooldown elapsed, resuming monitoring", cfg.name)
                state.rebooting = False
                state.last_seen = now   # avoid an immediate re-trigger
                continue

            silence = now - state.last_seen
            threshold = cfg.miss_threshold * cfg.ping_interval

            if silence >= threshold:
                log.warning(
                    "[%s] Silent for %.0fs (threshold %dx%ds = %ds) — rebooting",
                    cfg.name,
                    silence,
                    cfg.miss_threshold,
                    cfg.ping_interval,
                    threshold,
                )
                state.rebooting = True
                state.reboot_at = now
                asyncio.create_task(ssh_reboot(cfg))
            elif silence > cfg.ping_interval:
                log.info(
                    "[%s] Overdue by %.0fs (last seen %.0fs ago)",
                    cfg.name,
                    silence - cfg.ping_interval,
                    silence,
                )


# ---------------------------------------------------------------------------
# MQTT listener
# ---------------------------------------------------------------------------

async def mqtt_listener(
    bridge: MqttBridge, states: dict[str, DeviceState]
) -> None:
    topic_map = {s.config.mqtt_topic: s for s in states.values()}

    async for topic, payload in bridge.messages():
        state = topic_map.get(topic)
        if state:
            state.last_seen = time.monotonic()
            log.debug("[%s] Ping received", state.config.name)
        else:
            log.debug("Untracked topic: %s", topic)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    config_path = Path("/run/secrets/config.yaml")
    if not config_path.exists():
        config_path = Path(__file__).parent / "config.yaml"

    log.info("Loading config from %s", config_path)
    mqtt_cfg, devices = load_config(config_path)

    loop = asyncio.get_running_loop()
    bridge = MqttBridge(
        broker=mqtt_cfg["broker"],
        port=int(mqtt_cfg.get("port", 1883)),
        loop=loop,
        username=mqtt_cfg.get("username"),
        password=mqtt_cfg.get("password"),
    )

    states: dict[str, DeviceState] = {d.name: DeviceState(config=d) for d in devices}

    for dev in devices:
        bridge.subscribe(dev.mqtt_topic)
        log.info(
            "Watching [%s] on topic '%s' (reboot after %dx%ds silence)",
            dev.name,
            dev.mqtt_topic,
            dev.miss_threshold,
            dev.ping_interval,
        )

    bridge.start()

    try:
        await asyncio.gather(
            mqtt_listener(bridge, states),
            watchdog_loop(states),
        )
    finally:
        bridge.stop()


if __name__ == "__main__":
    asyncio.run(main())
