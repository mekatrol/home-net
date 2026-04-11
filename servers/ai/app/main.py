#!/usr/bin/env python3
"""Home monitoring watchdog entrypoint."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

import websockets

from watchdog_email import (
    dropped_cleaner,
    email_poller,
    inbox_processor,
    processed_sender,
    processing_processor,
    sent_cleaner,
)
from watchdog_http import http_pollers
from watchdog_logging import email_log, log, set_log_levels
from watchdog_models import DeviceState, ensure_tls_cert, load_config
from watchdog_mqtt import MqttBridge, mqtt_listener, status_publisher
from watchdog_schedulers import (
    upgrade_reboot_scheduler,
    upgrade_scheduler,
    watchdog_loop,
)
from watchdog_server import WatchdogServer
from watchdog_web import RedirectConfigStore, start_web_server


def _log_device_startup(devices) -> None:
    for dev in devices:
        if dev.is_mqtt_only:
            log.info(
                "Watching [%s] via MQTT topic '%s' (alert after %dx%ds silence)",
                dev.name,
                dev.mqtt_topic,
                dev.miss_threshold,
                dev.ping_interval,
            )
        elif dev.is_http_polled:
            continue
        else:
            log.info(
                "Watching [%s] via WebSocket (device_name=%s, reboot after %dx%ds silence)",
                dev.name,
                dev.device_name,
                dev.miss_threshold,
                dev.ping_interval,
            )


def _publish_initial_statuses(
    bridge: MqttBridge, states: dict[str, DeviceState]
) -> None:
    for state in states.values():
        bridge.publish(
            f"status/{state.config.mqtt_device_name}",
            json.dumps(
                {
                    "lastStatus": "Initialising",
                    "lastStatusTimestamp": None,
                    "lastOnlineTimestamp": None,
                }
            ),
            retain=True,
            ttl=state.config.status_retain_ttl,
        )


async def main() -> None:
    config_path = Path("/run/config/config.yaml")
    if not config_path.exists():
        config_path = Path(__file__).parent / "config.yaml"

    log.info("Loading config from %s", config_path)
    (
        server_cfg,
        mqtt_cfg,
        devices,
        log_levels,
        status_interval,
        email_cfg,
        web_cfg,
    ) = load_config(config_path)
    set_log_levels(
        watchdog_level=log_levels["watchdog"],
        email_level=log_levels["email"],
        device_level=log_levels["device"],
    )
    log.info("Watchdog log level set to %s", logging.getLevelName(log_levels["watchdog"]))
    email_log.info("Email log level set to %s", logging.getLevelName(log_levels["email"]))

    states: dict[str, DeviceState] = {d.name: DeviceState(config=d) for d in devices}
    _log_device_startup(devices)

    token: str = server_cfg["token"]
    host: str = server_cfg.get("host", "0.0.0.0")
    port: int = int(server_cfg.get("port", 8765))

    tasks: list = [
        watchdog_loop(states),
        upgrade_scheduler(states),
        upgrade_reboot_scheduler(states),
        start_web_server(
            web_cfg.host,
            web_cfg.port,
            web_cfg.web_pwd,
            RedirectConfigStore(config_path.with_name("email_config.yaml")),
            email_cfg,
        ),
    ]

    bridge: Optional[MqttBridge] = None
    mqtt_devices = [d for d in devices if d.is_mqtt_only]
    if mqtt_cfg:
        loop = asyncio.get_running_loop()
        bridge = MqttBridge(
            broker=mqtt_cfg["broker"],
            port=int(mqtt_cfg.get("port", 1883)),
            loop=loop,
            username=mqtt_cfg.get("username"),
            password=mqtt_cfg.get("password"),
        )
        for dev in mqtt_devices:
            bridge.subscribe(dev.mqtt_topic)
        bridge.start()
        if mqtt_devices:
            tasks.append(mqtt_listener(bridge, states))
        tasks.append(status_publisher(bridge, states, status_interval))
        log.info("MQTT bridge started — status publishing every %ds", status_interval)
        _publish_initial_statuses(bridge, states)
    elif mqtt_devices:
        log.error(
            "MQTT devices configured but no 'mqtt' section in config — they will not be monitored"
        )

    tasks.append(http_pollers(states, bridge))

    if email_cfg:
        tasks.append(email_poller(email_cfg))
        tasks.append(inbox_processor(email_cfg))
        tasks.append(processing_processor(email_cfg))
        tasks.append(processed_sender(email_cfg))
        tasks.append(sent_cleaner(email_cfg))
        tasks.append(dropped_cleaner(email_cfg))
        email_log.info(
            "Email enabled — %s (POP3 port %d, SMTP port %d)",
            email_cfg.host,
            email_cfg.pop3_port,
            email_cfg.smtp_port,
        )
    else:
        email_log.info("No email config — email polling disabled")

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
