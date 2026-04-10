import datetime
import logging
import ssl
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine, Optional

import yaml

CERT_DIR = Path("/var/lib/watchdog-server")
CERT_FILE = CERT_DIR / "server.crt"
KEY_FILE = CERT_DIR / "server.key"


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
    catchall: dict = field(default_factory=dict)
    redirects: dict[str, list[dict[str, str]]] = field(default_factory=dict)


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
    email_cfg: Optional[EmailConfig] = None
    if "email" in raw:
        email_cfg = EmailConfig(**raw["email"])
        redirects_path = path.with_name("redirects_config.yaml")
        if redirects_path.exists():
            with open(redirects_path) as f:
                redirects_raw = yaml.safe_load(f) or {}
            email_cfg.redirects = _normalize_redirects_config(redirects_raw)
    return server_cfg, mqtt_cfg, devices, log_levels, status_interval, email_cfg


def _parse_log_level(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        parsed = logging.getLevelName(value.upper())
        if isinstance(parsed, int):
            return parsed
    return logging.INFO


def _normalize_redirects_config(raw: Any) -> dict[str, list[dict[str, str]]]:
    redirects = raw.get("redirects", raw) if isinstance(raw, dict) else {}
    normalized: dict[str, list[dict[str, str]]] = {}
    for catchall_email, rules in redirects.items():
        if not isinstance(catchall_email, str):
            continue
        catchall_email = catchall_email.strip().lower()
        if "@" not in catchall_email:
            continue

        _, domain = catchall_email.rsplit("@", 1)
        normalized_rules: list[dict[str, str]] = []
        raw_rules = rules if isinstance(rules, list) else []
        for rule in raw_rules:
            if isinstance(rule, str):
                value = rule.strip()
                if not value:
                    continue
                if value.lower().startswith("regex:"):
                    pattern = value[6:].strip()
                    if pattern:
                        normalized_rules.append({"type": "regex", "value": pattern})
                    continue
                address = value.lower()
                if "@" not in address:
                    address = f"{address}@{domain}"
                normalized_rules.append({"type": "exact", "value": address})
                continue

            if not isinstance(rule, dict):
                continue

            exact_value = rule.get("exact") or rule.get("address")
            if isinstance(exact_value, str) and exact_value.strip():
                address = exact_value.strip().lower()
                if "@" not in address:
                    address = f"{address}@{domain}"
                normalized_rules.append({"type": "exact", "value": address})

            regex_value = rule.get("regex")
            if isinstance(regex_value, str) and regex_value.strip():
                normalized_rules.append(
                    {"type": "regex", "value": regex_value.strip()}
                )

        normalized[catchall_email] = normalized_rules
    return normalized


def ensure_tls_cert() -> ssl.SSLContext:
    if not CERT_FILE.exists() or not KEY_FILE.exists():
        raise FileNotFoundError(
            f"TLS certificate not found at {CERT_FILE} — "
            "it should have been generated by start.sh at container startup"
        )
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT_FILE, KEY_FILE)
    return ctx
