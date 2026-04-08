import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

LOG_FILE = Path("/var/log/home-monitor/watchdog.log")
DEVICE_LOG_FILE = Path("/var/log/home-monitor/devices.log")
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("watchdog")
    if logger.handlers:
        return logger

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
            logging.Formatter(
                "%(asctime)s [%(name)s] %(levelname)-8s %(message)s",
                LOG_DATE_FORMAT,
            )
        )
    logger.addHandler(_device_log_rotating)
    return logger
