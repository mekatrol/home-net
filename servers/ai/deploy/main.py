#!/usr/bin/env python3
"""MQTT ping publisher.

Publishes a heartbeat message to a configured MQTT topic at a regular interval
so the home monitor watchdog knows this device is alive.
"""

import logging
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import paho.mqtt.client as mqtt
import yaml

LOG_FILE = Path("/var/log/ping/ping.log")
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("ping")
    logger.setLevel(logging.INFO)

    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    logger.addHandler(stream)

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    rotating = RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    rotating.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    logger.addHandler(rotating)

    return logger


log = setup_logging()


def load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main() -> None:
    config_path = Path("/etc/ping/config.yaml")
    if not config_path.exists():
        config_path = Path(__file__).parent / "config.yaml"

    log.info("Loading config from %s", config_path)
    cfg = load_config(config_path)

    mqtt_cfg = cfg["mqtt"]
    topic: str = cfg["ping"]["topic"]
    interval: int = int(cfg["ping"]["interval"])

    connected = threading.Event()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if mqtt_cfg.get("username"):
        client.username_pw_set(mqtt_cfg["username"], mqtt_cfg.get("password"))

    def on_connect(client, userdata, connect_flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("MQTT connect failed: %s", reason_code)
        else:
            log.info("Connected to %s:%s — publishing to '%s' every %ds",
                     mqtt_cfg["broker"], mqtt_cfg.get("port", 1883), topic, interval)
            connected.set()

    def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
        connected.clear()
        log.warning("Disconnected (reason: %s) — will reconnect", reason_code)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.connect_async(mqtt_cfg["broker"], int(mqtt_cfg.get("port", 1883)))
    client.loop_start()

    log.info("Waiting for MQTT connection...")
    if not connected.wait(timeout=30):
        log.error("Timed out waiting for MQTT connection")

    try:
        while True:
            if not connected.is_set():
                log.debug("Not connected, skipping ping")
                time.sleep(interval)
                continue
            result = client.publish(topic, "ping")
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                log.debug("Published ping to '%s'", topic)
            else:
                log.warning("Publish failed (rc=%d)", result.rc)
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
