import datetime
import logging
import ssl
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine, Optional

import yaml

from watchdog_redirects import load_redirects_config

CERT_DIR = Path("/var/lib/watchdog-server")
CERT_FILE = CERT_DIR / "server.crt"
KEY_FILE = CERT_DIR / "server.key"
EMAIL_CONFIG_FILENAME = "email_config.yaml"


@dataclass
class DeviceConfig:
    name: str
    device_name: str = ""
    mqtt_topic: str = ""
    mqtt_device_name: str = ""
    status_retain_ttl: Optional[int] = None
    http_url: str = ""
    ping_interval: int = 60
    miss_threshold: int = 3
    reboot_cooldown: int = 300
    upgrade_reboot_time: Optional[str] = None
    upgrade_time: Optional[str] = None
    container_device_name: Optional[str] = None
    container_name: Optional[str] = None

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
    sent_retention_days: int = 10
    dropped_retention_days: int = 10
    catchall: dict = field(default_factory=dict)
    drop: list[str] = field(default_factory=list)
    allowed_domains: list[str] = field(default_factory=list)
    redirects: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    config_path: Optional[str] = None


@dataclass
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    web_pwd: str = ""


def normalize_email_path(address: str) -> str:
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
    pending_command_callback: Optional[Callable[[bool], Coroutine[Any, Any, None]]] = (
        None
    )
    ws: Optional[object] = None

    @property
    def connected(self) -> bool:
        return self.ws is not None


def load_config(
    path: Path,
) -> tuple[
    dict,
    Optional[dict],
    list[DeviceConfig],
    dict[str, int],
    int,
    Optional[EmailConfig],
    WebConfig,
]:
    with open(path) as f:
        raw = yaml.safe_load(f)
    server_cfg = raw["server"]
    mqtt_cfg = raw.get("mqtt")
    devices = [DeviceConfig(**d) for d in raw["devices"]]
    default_log_level = _parse_log_level(raw.get("log_level", "INFO"))
    raw_log_levels = raw.get("log_levels", {}) if isinstance(raw, dict) else {}
    log_levels = {
        "watchdog": _parse_log_level(
            raw_log_levels.get("watchdog", default_log_level)
            if isinstance(raw_log_levels, dict)
            else default_log_level
        ),
        "email": _parse_log_level(
            raw_log_levels.get("email", default_log_level)
            if isinstance(raw_log_levels, dict)
            else default_log_level
        ),
        "device": _parse_log_level(
            raw_log_levels.get("device", default_log_level)
            if isinstance(raw_log_levels, dict)
            else default_log_level
        ),
    }
    status_interval = int(raw.get("status_interval", 10))
    web_cfg = WebConfig(**raw.get("web", {}))
    email_cfg = load_email_config(path.with_name(EMAIL_CONFIG_FILENAME))
    return server_cfg, mqtt_cfg, devices, log_levels, status_interval, email_cfg, web_cfg


def load_email_config(path: Path) -> Optional[EmailConfig]:
    if not path.exists():
        return None

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    email_section = raw.get("email", raw) if isinstance(raw, dict) else {}
    if not isinstance(email_section, dict) or not email_section:
        return None

    email_cfg = EmailConfig(
        **{
            key: value
            for key, value in email_section.items()
            if key in EmailConfig.__dataclass_fields__ and key not in {"redirects", "config_path"}
        }
    )
    email_cfg.config_path = str(path)
    email_cfg.redirects = load_redirects_config(path)
    return email_cfg


def _parse_log_level(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        parsed = logging.getLevelName(value.upper())
        if isinstance(parsed, int):
            return parsed
    return logging.INFO


def ensure_tls_cert() -> ssl.SSLContext:
    if not CERT_FILE.exists() or not KEY_FILE.exists():
        raise FileNotFoundError(
            f"TLS certificate not found at {CERT_FILE} — "
            "it should have been generated by start.sh at container startup"
        )
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT_FILE, KEY_FILE)
    return ctx
