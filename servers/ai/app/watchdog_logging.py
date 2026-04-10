import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

LOG_FILE = Path("/var/log/home-monitor/watchdog.log")
EMAIL_LOG_FILE = Path("/var/log/home-monitor/email.log")
DEVICE_LOG_FILE = Path("/var/log/home-monitor/devices.log")
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _setup_file_logger(name: str, log_file: Path) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    logger.addHandler(stream)

    log_file.parent.mkdir(parents=True, exist_ok=True)
    rotating = RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    rotating.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    logger.addHandler(rotating)

    return logger


def setup_logging() -> logging.Logger:
    return _setup_file_logger("watchdog", LOG_FILE)


def setup_email_logging() -> logging.Logger:
    return _setup_file_logger("email", EMAIL_LOG_FILE)


log = setup_logging()
email_log = setup_email_logging()

_device_log_rotating: Optional[RotatingFileHandler] = None
_device_log_level = logging.DEBUG


def get_device_logger(device_name: str) -> logging.Logger:
    global _device_log_rotating
    logger = logging.getLogger(f"device.{device_name}")
    if logger.handlers:
        return logger

    logger.setLevel(_device_log_level)
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


def set_log_level(level: int) -> None:
    log.setLevel(level)
    email_log.setLevel(level)


def set_log_levels(*, watchdog_level: int, email_level: int, device_level: int) -> None:
    global _device_log_level

    log.setLevel(watchdog_level)
    email_log.setLevel(email_level)
    _device_log_level = device_level

    logger_dict = logging.Logger.manager.loggerDict
    for logger_name, logger in logger_dict.items():
        if logger_name.startswith("device.") and isinstance(logger, logging.Logger):
            logger.setLevel(device_level)
