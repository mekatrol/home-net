import asyncio
import datetime
import json
import time
from typing import Optional

import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from watchdog_logging import log
from watchdog_models import DeviceState


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

        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            protocol=mqtt.MQTTv5,
        )
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
        self._loop.call_soon_threadsafe(
            self._queue.put_nowait, (msg.topic, msg.payload)
        )

    def _on_disconnect(
        self, client, userdata, disconnect_flags, reason_code, properties
    ):
        log.warning("MQTT disconnected (reason: %s) — paho will reconnect", reason_code)

    async def messages(self):
        while True:
            yield await self._queue.get()

    def publish(
        self,
        topic: str,
        payload: str,
        retain: bool = False,
        ttl: Optional[int] = None,
    ) -> None:
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

    payload = json.dumps(
        {
            "lastStatus": status,
            "lastStatusTimestamp": _iso(state.last_seen_wall),
            "lastOnlineTimestamp": _iso(state.last_online_wall),
        }
    )

    bridge.publish(
        f"status/{cfg.mqtt_device_name}",
        payload,
        retain=True,
        ttl=cfg.status_retain_ttl,
    )
    log.debug("[%s] Status → status/%s = %s", cfg.name, cfg.mqtt_device_name, status)


async def status_publisher(
    bridge: MqttBridge,
    states: dict[str, DeviceState],
    interval: int,
) -> None:
    while True:
        await asyncio.sleep(interval)
        for state in states.values():
            publish_status(bridge, state)


async def mqtt_listener(bridge: MqttBridge, states: dict[str, DeviceState]) -> None:
    topic_map = {
        s.config.mqtt_topic: s for s in states.values() if s.config.is_mqtt_only
    }
    async for topic, payload in bridge.messages():
        state = topic_map.get(topic)
        if state:
            if state.disabled:
                log.debug(
                    "[%s] MQTT message received but device is disabled — ignoring",
                    state.config.name,
                )
                continue
            now = time.monotonic()
            was_online = state.ever_seen and (now - state.last_seen) < (
                state.config.miss_threshold * state.config.ping_interval
            )
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
