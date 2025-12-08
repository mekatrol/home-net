#!/usr/bin/env python3
"""
Merged UPS + Unraid NAS monitor.

This script runs on a small always-on machine (e.g. Raspberry Pi) and performs:

1. UPS monitoring over USB
   - Talks to a MEC0003-based UPS using the "descriptor Q1" method.
   - Reads Megatec/Q1-style status lines from a USB string descriptor.
   - Parses fields, especially:
       * on_battery (mains present or not)
       * battery_voltage (pack voltage)
       * various flags for logging / debugging

2. Power-loss handling (on UPS battery)
   - When mains fails (UPS goes "on_battery"), the script logs this event.
   - While on battery:
       * If battery_voltage <= LOW_BATT_VOLT:
             Stop the Unraid array via the Unraid 7.x HTTP API
             (/update.htm using csrf_token + curl).
       * If battery_voltage <= EXTRA_LOW_BATT_VOLT:
             Request a clean shutdown of the Unraid host
             via the same HTTP API.

3. Power-restore handling (mains back)
   - When mains power is restored (UPS is no longer "on_battery"),
     the script waits until BOTH conditions are true:
       * battery_voltage >= ENABLE_ARRAY_VOLTAGE
       * these conditions have held continuously for at least
         power_stable_time seconds.
   - Once those conditions are satisfied, it attempts to START the
     Unraid array (again using the Unraid 7.x HTTP API).
   - The script may attempt to start the array repeatedly over time,
     so that if Unraid reboots slowly or the array was intentionally
     stopped, it is eventually brought online (similar behavior to
     the original nas_monitor).

4. Continuous Unraid monitoring
   - Independently from UPS events, the script periodically checks
     Unraid's array status via SSH:
       grep -E 'arrayStarted=|mdState=|fsState=' /var/local/emhttp/var.ini
   - It logs whether the array is STARTED or not, and logs the raw
     status lines whenever there is a change.

Configuration:
    ./nas-monitor.conf  (same directory as this script, by default)

Logging:
    /home/pi/nas/nas-monitor.log (rotating file; ~1MB with 5 backups)

This file replaces the previous combination of:
    - ups_monitor.py
    - nas_monitor.py

All UPS-related configuration has been moved into nas-monitor.conf.
"""

import os
import time
import subprocess
import logging
from logging.handlers import RotatingFileHandler
from typing import Dict, Tuple, Any, List, Union, Optional, TYPE_CHECKING

import usb.core
import usb.util
import re
import json

if TYPE_CHECKING:
    import paho.mqtt.client as mqtt

# Runtime import for MQTT – this actually defines `mqtt` when running.
try:
    import paho.mqtt.client as mqtt  # type: ignore[import]
except ImportError:
    mqtt = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Paths / logger
# ---------------------------------------------------------------------------

# Configuration file path (relative to working directory)
CONFIG_PATH = "./nas-monitor.conf"

# Log file path (ensure the running user has permission to write here)
LOG_PATH = "/home/pi/nas/nas-monitor.log"

# Global logger instance, configured in setup_logging()
logger = logging.getLogger("nas-monitor")


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging(log_path: str) -> None:
    """
    Configure logging for this daemon.

    - Primary target: rotating log file (LOG_PATH)
    - Rotation: 1 MB, keep 5 backups
    - Format: "YYYY-MM-DD HH:MM:SS [LEVEL] message"

    If the log directory cannot be created or the log file cannot be
    opened, we fall back to logging to stderr.
    """
    logger.setLevel(logging.INFO)

    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception as e:
            # Fall back to basic stderr logging
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s [%(levelname)s] %(message)s",
            )
            logger.error(
                "Failed to create log directory %s: %s; using stderr only",
                log_dir,
                e,
            )
            return

    try:
        handler = RotatingFileHandler(
            log_path,
            maxBytes=1_000_000,  # ~1 MB
            backupCount=5,
        )
    except Exception as e:
        # If we cannot open the log file, fall back to stderr
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
        )
        logger.error(
            "Failed to open log file %s: %s; using stderr only",
            log_path,
            e,
        )
        return

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)

    if not logger.handlers:
        logger.addHandler(handler)


# ---------------------------------------------------------------------------
# Configuration loading
# ---------------------------------------------------------------------------


def _parse_bool(val: str) -> bool:
    """
    Parse a configuration value into boolean.

    Accepted true-ish values (case-insensitive):
        "1", "true", "yes", "on"
    Accepted false-ish values:
        "0", "false", "no", "off"

    Anything else defaults to False with a warning.
    """
    truthy = {"1", "true", "yes", "on"}
    falsy = {"0", "false", "no", "off"}

    lower = val.strip().lower()
    if lower in truthy:
        return True
    if lower in falsy:
        return False

    logger.warning("Unable to parse boolean from %r; defaulting to False", val)
    return False


def load_config(path: str) -> Dict[str, Any]:
    """
    Load key=value pairs from the config file into a dictionary.

    - Supports comments starting with '#'.
    - Supports inline comments after a '#' character.
    - Values may be quoted with single or double quotes.

    The following keys are recognized and have defaults:

        host (str)                    : Unraid host name / IP
        user (str)                    : SSH username
        pwd (str)                     : ignored, only for legacy compatibility

        power_stable_time (int)       : seconds of stable mains + battery
                                        above threshold before starting array
        status_check_interval (int)   : seconds between array status polls

        low_batt_volt (float)         : <= this voltage (on battery) → stop array
        extra_low_batt_volt (float)   : <= this voltage (on battery) → shutdown NAS
        enable_array_voltage (float)  : >= this voltage (on mains) +
                                        stable time → start array

        ups_vendor_id (str hex)       : UPS USB vendor ID, e.g. "0001"
        ups_product_id (str hex)      : UPS USB product ID, e.g. "0000"
        ups_timeout_ms (int)          : control-transfer timeout
        ups_poll_interval (int)       : seconds between UPS polls

        silence_beeper (bool)         : whether to attempt to disable UPS beeper
    """

    cfg: Dict[str, Any] = {
        "host": None,
        "user": None,
        "pwd": "",
        "power_stable_time": 180,
        "status_check_interval": 10,
        "low_batt_volt": 24.7,
        "extra_low_batt_volt": 22.5,
        "enable_array_voltage": 23.0,
        "ups_vendor_id": "0001",
        "ups_product_id": "0000",
        "ups_timeout_ms": 5000,
        "ups_poll_interval": 2,
        "silence_beeper": True,
        # MQTT defaults
        "mqtt_enabled": False,
        "mqtt_host": "127.0.0.1",
        "mqtt_port": 1883,
        "mqtt_keepalive": 30,
        "mqtt_username": "",
        "mqtt_password": "",
        "mqtt_tls": False,
        "mqtt_base_topic": "home/nas",
    }

    if not os.path.exists(path):
        logger.error("Config file not found: %s; using defaults where possible", path)
        return cfg

    int_keys = {
        "power_stable_time",
        "status_check_interval",
        "ups_timeout_ms",
        "ups_poll_interval",
        "mqtt_port",
        "mqtt_keepalive",
    }
    float_keys = {"low_batt_volt", "extra_low_batt_volt", "enable_array_voltage"}
    bool_keys = {"silence_beeper", "mqtt_enabled", "mqtt_tls"}

    try:
        with open(path, "r") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue

                # Strip inline comments
                if "#" in line:
                    line = line.split("#", 1)[0].strip()
                    if not line:
                        continue

                if "=" not in line:
                    logger.warning(
                        "Ignoring malformed config line (no '='): %s", raw_line.strip()
                    )
                    continue

                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")

                # Integer keys
                if key in int_keys:
                    try:
                        cfg[key] = int(val)
                    except ValueError:
                        logger.warning(
                            "Invalid int for %s: %r, using default %r",
                            key,
                            val,
                            cfg[key],
                        )
                    continue

                # Float keys
                if key in float_keys:
                    try:
                        cfg[key] = float(val)
                    except ValueError:
                        logger.warning(
                            "Invalid float for %s: %r, using default %r",
                            key,
                            val,
                            cfg[key],
                        )
                    continue

                # Boolean keys
                if key in bool_keys:
                    cfg[key] = _parse_bool(val)
                    continue

                # Everything else is treated as a raw string
                cfg[key] = val

    except Exception as e:
        logger.error("Error reading config file %s: %s", path, e)

    return cfg


# ---------------------------------------------------------------------------
# Local command / SSH helpers
# ---------------------------------------------------------------------------


def run_local_cmd(
    cmd: Union[List[str], str],
    shell: bool = False,
) -> Tuple[int, str, str]:
    """
    Run a command locally and return (return_code, stdout, stderr).

    Parameters:
        cmd   : Command to run. If shell=True, this must be a string.
                If shell=False, this should be a list of arguments.
        shell : Whether to execute through a shell.

    Returns:
        (rc, out, err)
            rc  : Exit code
            out : Captured stdout as text
            err : Captured stderr as text
    """
    try:
        result = subprocess.run(
            cmd,  # type: ignore[arg-type]
            shell=shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        # On failure, emulate a non-zero exit code with error text
        return 1, "", str(e)


def build_ssh_command(cfg: Dict[str, Any], remote_cmd: str) -> List[str]:
    """
    Build an SSH command list to execute `remote_cmd` on the Unraid host.

    Notes:
        - Only key-based SSH authentication is supported.
        - Any configured `pwd` is ignored (but a warning is logged if present).

    Returns:
        List[str] representing the SSH command and its arguments.
    """
    host = cfg.get("host")
    user = cfg.get("user")
    pwd = cfg.get("pwd", "")

    if pwd:
        logger.warning(
            "Config contains a password, but password-based SSH is not used; "
            "ensure key-based authentication is configured."
        )

    if not host:
        raise RuntimeError("Unraid host is not configured (host is empty)")

    ssh_cmd: List[str] = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=10",
    ]

    if user:
        target = f"{user}@{host}"
    else:
        target = str(host)

    ssh_cmd.append(target)
    ssh_cmd.append(remote_cmd)
    return ssh_cmd


def run_ssh_command(cfg: Dict[str, Any], remote_cmd: str) -> Tuple[int, str, str]:
    """
    Execute a remote command on the Unraid host via SSH.

    Logs:
        - The SSH command string (for diagnostics)
        - STDOUT (if non-empty)
        - STDERR (if non-empty)
        - Exit code

    Returns:
        (rc, out, err) from subprocess.
    """
    ssh_cmd = build_ssh_command(cfg, remote_cmd)
    logger.info("SSH EXEC: %s", " ".join(ssh_cmd))

    rc, out, err = run_local_cmd(ssh_cmd)

    if out.strip():
        logger.info("SSH STDOUT:\n%s", out.strip())
    if err.strip():
        logger.warning("SSH STDERR:\n%s", err.strip())

    logger.info("SSH EXIT CODE: %d", rc)
    return rc, out, err


# ---------------------------------------------------------------------------
# MQTT publishing helpers
# ---------------------------------------------------------------------------


def setup_mqtt(cfg: Dict[str, Any]) -> Optional["mqtt.Client"]:
    """
    Initialise a persistent MQTT client if MQTT is enabled and paho-mqtt
    is installed. The client connection is kept open and used to publish
    UPS and Unraid array status messages.

    Behavior:
        - If cfg['mqtt_enabled'] is false, logs and returns None.
        - If paho-mqtt is not installed, logs and returns None.
        - Otherwise:
            * Creates a client
            * Applies optional username/password auth
            * Optionally enables basic TLS
            * Connects to the broker
            * Starts the network loop (loop_start) in a background thread

    Returns:
        mqtt.Client instance, or None if MQTT is effectively disabled.
    """
    if not cfg.get("mqtt_enabled", False):
        logger.info("MQTT disabled by configuration (mqtt_enabled=false).")
        return None

    if mqtt is None:
        logger.error(
            "MQTT requested but paho-mqtt is not installed. "
            "Run 'pip install paho-mqtt' or disable mqtt_enabled."
        )
        return None

    host = str(cfg.get("mqtt_host", "127.0.0.1"))
    port = int(cfg.get("mqtt_port", 1883))
    keepalive = int(cfg.get("mqtt_keepalive", 30))
    username = str(cfg.get("mqtt_username") or "") or None
    password = str(cfg.get("mqtt_password") or "") or None
    use_tls = bool(cfg.get("mqtt_tls", False))

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)  # type: ignore[call-arg]

    # Optional authentication
    if username is not None:
        client.username_pw_set(username, password)

    # Optional TLS (basic system CA usage)
    if use_tls:
        logger.info("Enabling TLS for MQTT connection.")
        client.tls_set()

    logger.info(
        "Connecting to MQTT broker %s:%d (keepalive=%d, tls=%s)...",
        host,
        port,
        keepalive,
        use_tls,
    )

    try:
        client.connect(host, port, keepalive)
        # Use a background thread for MQTT network handling; this keeps
        # the main loop simple and synchronous.
        client.loop_start()
    except Exception as e:
        logger.error("Failed to connect to MQTT broker: %s", e)
        return None

    logger.info("MQTT connection established successfully.")
    return client


def _mqtt_topic(cfg: Dict[str, Any], suffix: str) -> str:
    """
    Build a concrete MQTT topic by appending a suffix to the configured
    base topic.

    Example:
        base: "home/nas"
        suffix: "ups"
        -> "home/nas/ups"
    """
    base = str(cfg.get("mqtt_base_topic", "home/nas")).rstrip("/")
    return f"{base}/{suffix}"


def publish_ups_status(
    cfg: Dict[str, Any],
    client: Optional["mqtt.Client"],
    status: Dict[str, Any],
) -> None:
    """
    Publish a single UPS status sample to MQTT.

    Topic:
        <mqtt_base_topic>/ups

    Payload (JSON object), for example:
        {
          "time": 1710001234,
          "input_voltage": 230.1,
          "output_voltage": 228.5,
          "load_percent": 23,
          "battery_voltage": 25.1,
          "temperature_c": 28.0,
          "on_battery": false,
          "battery_low": false,
          "flags_raw": "01000011"
        }
    """
    if client is None:
        return

    topic = _mqtt_topic(cfg, "ups")
    payload = {
        "time": int(time.time()),
        "input_voltage": status.get("input_voltage"),
        "output_voltage": status.get("output_voltage"),
        "load_percent": status.get("load_percent"),
        "battery_voltage": status.get("battery_voltage"),
        "temperature_c": status.get("temperature_c"),
        "on_battery": bool(status.get("on_battery")),
        "battery_low": bool(status.get("battery_low")),
        "flags_raw": status.get("flags_raw"),
    }

    try:
        client.publish(topic, json.dumps(payload), qos=0, retain=False)
        logger.info("Published UPS status to MQTT topic '%s'.", topic)
    except Exception as e:
        logger.warning("Failed to publish UPS status to MQTT: %s", e)


def publish_array_status(
    cfg: Dict[str, Any],
    client: Optional["mqtt.Client"],
    started: bool,
    raw_status: str,
) -> None:
    """
    Publish the current Unraid array status to MQTT.

    Topic:
        <mqtt_base_topic>/array

    Payload (JSON object), for example:
        {
          "time": 1710001234,
          "started": true,
          "raw_status": "mdState=STARTED\narrayStarted=\"yes\"..."
        }

    The 'raw_status' field is the combined lines from var.ini that were
    already obtained by get_array_status().
    """
    if client is None:
        return

    topic = _mqtt_topic(cfg, "array")
    payload = {
        "time": int(time.time()),
        "started": bool(started),
        "raw_status": raw_status,
    }

    try:
        client.publish(topic, json.dumps(payload), qos=0, retain=False)
        logger.info("Published array status to MQTT topic '%s'.", topic)
    except Exception as e:
        logger.warning("Failed to publish array status to MQTT: %s", e)


# ---------------------------------------------------------------------------
# Unraid HTTP (update.htm) helpers
# ---------------------------------------------------------------------------


def _build_update_cmd(data_expr: str) -> str:
    """
    Build the shell one-liner that:
        - Extracts csrf_token from /var/local/emhttp/var.ini
        - Issues a POST to /update.htm via curl (HTTP)
        - If HTTP fails, retries via HTTPS

    The caller must provide `data_expr`, which typically includes
    a reference to ${CSRF}, for example:
        "startState=STOPPED&file=&csrf_token=${CSRF}&cmdStart=Start"
    """
    cmd = (
        "CSRF=$(grep -Po '^csrf_token=\"\\K[^\"]+' /var/local/emhttp/var.ini);"
        'curl -sS -k --fail -e "http://localhost/Main" '
        "-c /tmp/unraid.cookies -b /tmp/unraid.cookies "
        f'--data "{data_expr}" '
        "http://localhost/update.htm || "
        'curl -sS -k --fail -e "https://localhost/Main" '
        "-c /tmp/unraid.cookies -b /tmp/unraid.cookies "
        f'--data "{data_expr}" '
        "https://localhost/update.htm"
    )
    return cmd


def start_array_via_update(cfg: Dict[str, Any]) -> bool:
    """
    Request that Unraid START the array via /update.htm.

    This mirrors the behavior of the Unraid web UI for starting the array
    and is compatible with Unraid 7.x (and similar versions).

    It constructs a POST with:
        startState=STOPPED
        file=
        csrf_token=<token>
        cmdStart=Start
    """
    data_expr = "startState=STOPPED&file=&csrf_token=${CSRF}&cmdStart=Start"
    remote_cmd = _build_update_cmd(data_expr)

    logger.info("Sending START ARRAY request via update.htm (curl + csrf_token)")
    rc, out, err = run_ssh_command(cfg, remote_cmd)

    if rc == 0:
        logger.info("Start array request sent successfully via update.htm.")
        return True

    logger.error(
        "Start array request FAILED (rc=%d). stdout:\n%s\nstderr:\n%s",
        rc,
        out.strip(),
        err.strip(),
    )
    return False


def stop_array_via_update(cfg: Dict[str, Any]) -> bool:
    """
    Request that Unraid STOP the array via /update.htm.

    Per your instructions, this uses:
        startState=STARTED
        file=
        csrf_token=<token>
        cmdStop=Stop
    """
    data_expr = "startState=STARTED&file=&csrf_token=${CSRF}&cmdStop=Stop"
    remote_cmd = _build_update_cmd(data_expr)

    logger.info("Sending STOP ARRAY request via update.htm (curl + csrf_token)")
    rc, out, err = run_ssh_command(cfg, remote_cmd)

    if rc == 0:
        logger.info("Stop array request sent successfully via update.htm.")
        return True

    logger.error(
        "Stop array request FAILED (rc=%d). stdout:\n%s\nstderr:\n%s",
        rc,
        out.strip(),
        err.strip(),
    )
    return False


def shutdown_nas_via_update(cfg: Dict[str, Any]) -> bool:
    """
    Request that Unraid SHUT DOWN the system via /update.htm.

    Per your instructions, this uses:
        csrf_token=<token>
        cmdShutdown=Shutdown
    """
    data_expr = "csrf_token=${CSRF}&cmdShutdown=Shutdown"
    remote_cmd = _build_update_cmd(data_expr)

    logger.info("Sending SHUTDOWN request via update.htm (curl + csrf_token)")
    rc, out, err = run_ssh_command(cfg, remote_cmd)

    if rc == 0:
        logger.info("Shutdown request sent successfully via update.htm.")
        return True

    logger.error(
        "Shutdown request FAILED (rc=%d). stdout:\n%s\nstderr:\n%s",
        rc,
        out.strip(),
        err.strip(),
    )
    return False


# ---------------------------------------------------------------------------
# Unraid array status
# ---------------------------------------------------------------------------


def get_array_status(cfg: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Query Unraid for array status via /var/local/emhttp/var.ini.

    The remote command executed is:
        grep -E 'arrayStarted=|mdState=|fsState=' /var/local/emhttp/var.ini

    Returns:
        (started_bool, raw_output)
            started_bool : True if array appears to be STARTED
                           (based on mdState/arrayStarted fields)
            raw_output   : Combined stdout+stderr for logging / diagnostics
    """
    remote_cmd = (
        "grep -E 'arrayStarted=|mdState=|fsState=' /var/local/emhttp/var.ini "
        "2>/dev/null || true"
    )

    rc, out, err = run_ssh_command(cfg, remote_cmd)
    if rc != 0:
        logger.warning("Failed to get array status (rc=%d): %s", rc, err.strip())

    started = False
    md_state = None
    array_started = None
    fs_state = None

    for line in out.splitlines():
        line = line.strip()
        if line.startswith("mdState="):
            md_state = line
            if "STARTED" in line:
                started = True
        elif line.startswith("arrayStarted="):
            array_started = line
            if '"yes"' in line:
                started = True
        elif line.startswith("fsState="):
            fs_state = line

    if not started:
        logger.warning(
            "Array not started. mdState=%s, arrayStarted=%s, fsState=%s",
            md_state,
            array_started,
            fs_state,
        )

    # Combine stdout+stderr text for optional logging by caller
    raw = out + (("\n" + err) if err else "")
    return started, raw.strip()


# ---------------------------------------------------------------------------
# UPS interface (descriptor-based Megatec Q1)
# ---------------------------------------------------------------------------

# Regular expression used to strip non-numeric characters from tokens
NUM_RE = re.compile(r"[^0-9.+-]")


def clean_num(token: str) -> float:
    """
    Strip any non-numeric noise from a token and convert to float.

    Raises:
        ValueError if cleaning results in an empty or trivial string.
    """
    cleaned = NUM_RE.sub("", token)
    if cleaned in {"", ".", "+", "-"}:
        raise ValueError(f"Empty or invalid numeric after cleaning: {token!r}")
    return float(cleaned)


def parse_megatec_q1(line: str) -> Dict[str, Any]:
    """
    Parse a Megatec Q1 status line, tolerating stray control characters.

    Expected logical format:
        MMM.M NNN.N PPP.P QQQ RR.R SS.S TT.T b7b6b5b4b3b2b1b0

    Returns a dictionary with:
        input_voltage
        input_fault_voltage
        output_voltage
        load_percent
        input_frequency
        battery_voltage
        temperature_c
        flags_raw
        on_battery
        battery_low
        avr_active
        ups_failed
        standby_type
        test_in_progress
        shutdown_active
        beeper_on
    """
    parts = line.split()
    if len(parts) < 8:
        raise ValueError(f"Not enough fields in Megatec line: {parts!r}")

    vin = clean_num(parts[0])
    vin_fault = clean_num(parts[1])
    vout = clean_num(parts[2])
    load_pct = int(clean_num(parts[3]))
    freq = clean_num(parts[4])
    batt_v = clean_num(parts[5])
    temp_c = clean_num(parts[6])

    flags = parts[7].strip()
    flags = "".join(c for c in flags if c in "01")  # ensure only bits remain

    if len(flags) != 8:
        raise ValueError(
            f"Flags field should be 8 bits, got {flags!r} from {parts[7]!r}"
        )

    b7, b6, b5, b4, b3, b2, b1, b0 = flags

    return {
        "input_voltage": vin,
        "input_fault_voltage": vin_fault,
        "output_voltage": vout,
        "load_percent": load_pct,
        "input_frequency": freq,
        "battery_voltage": batt_v,
        "temperature_c": temp_c,
        "flags_raw": flags,
        "on_battery": (b7 == "1"),
        "battery_low": (b6 == "1"),
        "avr_active": (b5 == "1"),
        "ups_failed": (b4 == "1"),
        "standby_type": (b3 == "1"),
        "test_in_progress": (b2 == "1"),
        "shutdown_active": (b1 == "1"),
        "beeper_on": (b0 == "1"),
    }


def find_ups(cfg: Dict[str, Any]) -> usb.core.Device:
    """
    Locate and prepare the MEC0003 UPS device using vendor/product IDs
    from the configuration file.

    Steps:
        - Convert hex strings to integers (e.g. "0001" -> 0x0001).
        - Call usb.core.find() to locate the device.
        - Detach any kernel driver on interface 0 (where supported).
        - Set configuration and claim interface 0.

    Raises:
        RuntimeError if the device cannot be found or configured.
    """
    try:
        vendor_id = int(str(cfg.get("ups_vendor_id", "0001")), 16)
        product_id = int(str(cfg.get("ups_product_id", "0000")), 16)
    except ValueError as e:
        raise RuntimeError(f"Invalid ups_vendor_id/product_id in config: {e}") from e

    logger.info(
        "Searching for UPS device: vendor=0x%04X, product=0x%04X",
        vendor_id,
        product_id,
    )

    dev = usb.core.find(idVendor=vendor_id, idProduct=product_id)
    if dev is None:
        raise RuntimeError(
            f"MEC0003 UPS device not found (vendor=0x{vendor_id:04X}, "
            f"product=0x{product_id:04X})."
        )

    try:
        if dev.is_kernel_driver_active(0):
            try:
                dev.detach_kernel_driver(0)
                logger.info("Detached kernel driver from UPS interface 0")
            except usb.core.USBError as e:
                logger.warning("Could not detach kernel driver: %s", e)
    except (NotImplementedError, usb.core.USBError):
        # Some platforms do not implement is_kernel_driver_active
        pass

    dev.set_configuration()
    usb.util.claim_interface(dev, 0)
    logger.info("UPS found and interface 0 claimed successfully")
    return dev


def megatec_q1_from_usb(dev: usb.core.Device, timeout_ms: int) -> str:
    """
    Request a Megatec/Q1 status string via USB string descriptor
    (index 3, language 0x0409), as used by many MEC0003+UPSmart devices.

    Returns:
        Cleaned status string (parentheses, NULLs, and control characters
        stripped).

    Raises:
        RuntimeError if the response is too short or cannot be decoded.
    """
    raw = dev.ctrl_transfer(
        0x80,  # bmRequestType: device-to-host, standard, device
        0x06,  # bRequest: GET_DESCRIPTOR
        0x0303,  # wValue: type=STRING(0x03), index=3
        0x0409,  # wIndex: language ID (en-US)
        102,  # wLength
        timeout_ms,
    )

    if len(raw) < 4:
        raise RuntimeError(f"UPS response too short: {list(raw)}")

    # USB string descriptor: [bLength, bDescType, UTF-16LE bytes...]
    data_utf16 = bytes(raw[2:])
    text = data_utf16.decode("utf-16le", errors="ignore").strip("\x00")

    cleaned = text.strip().strip("()").strip("\r\n")
    return cleaned


def _get_io_endpoints(
    dev: usb.core.Device,
) -> Tuple[usb.core.Endpoint, usb.core.Endpoint]:
    """
    Locate the first BULK/INT IN and OUT endpoints on interface 0.

    This is only used for optional beeper toggle ("Q" command) and not
    for regular status polling (which uses the descriptor method).
    """
    cfg = dev.get_active_configuration()
    intf = cfg[(0, 0)]

    ep_out = usb.util.find_descriptor(
        intf,
        custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
        == usb.util.ENDPOINT_OUT,
    )
    ep_in = usb.util.find_descriptor(
        intf,
        custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
        == usb.util.ENDPOINT_IN,
    )

    if ep_out is None or ep_in is None:
        raise RuntimeError("Could not find both IN and OUT endpoints for UPS.")

    return ep_in, ep_out


def send_megatec_command(dev: usb.core.Device, cmd: str, timeout_ms: int) -> None:
    """
    Send a raw Megatec command (ASCII) over the UPS bulk OUT endpoint.

    This is used only to toggle the beeper ("Q\\r") once per outage
    if configured to do so.

    No reply is expected.
    """
    ep_in, ep_out = _get_io_endpoints(dev)
    _ = ep_in  # unused; retained for completeness / future expansion
    ep_out.write(cmd.encode("ascii"), timeout=timeout_ms)


def disable_beeper_if_needed(cfg: Dict[str, Any], dev: usb.core.Device) -> None:
    """
    If configured to do so, check the UPS's beeper status and, if it is
    currently enabled, send the Megatec "Q" command to toggle it off.

    This is performed on script startup and once per outage when needed.
    """
    if not cfg.get("silence_beeper", True):
        logger.info("silence_beeper=false; leaving UPS beeper state unchanged.")
        return

    timeout_ms = int(cfg.get("ups_timeout_ms", 5000))
    try:
        line = megatec_q1_from_usb(dev, timeout_ms)
        status = parse_megatec_q1(line)
    except Exception as e:
        logger.warning("Could not read initial UPS status to check beeper: %s", e)
        return

    if status.get("beeper_on"):
        logger.info("UPS beeper is currently ON – sending 'Q\\r' to disable it.")
        try:
            send_megatec_command(dev, "Q\r", timeout_ms)
        except Exception as e:
            logger.warning("Failed to send beeper toggle command: %s", e)
    else:
        logger.info("UPS beeper already disabled; no action needed.")


def read_ups_status(cfg: Dict[str, Any], dev: usb.core.Device) -> Dict[str, Any]:
    """
    Retrieve and parse a single UPS status sample.

    Steps:
        - Request descriptor-based Megatec/Q1 string using megatec_q1_from_usb().
        - Parse the line via parse_megatec_q1().
        - Log a concise summary for debugging.

    Returns:
        Dictionary with parsed fields (see parse_megatec_q1()).
    """
    timeout_ms = int(cfg.get("ups_timeout_ms", 5000))
    line = megatec_q1_from_usb(dev, timeout_ms)
    status = parse_megatec_q1(line)

    # Concise debug summary of the most important values
    logger.info(
        "UPS: Vin=%.1fV, Vout=%.1fV, Load=%d%%, Batt=%.2fV, "
        "on_battery=%s, batt_low=%s, flags=%s",
        status["input_voltage"],
        status["output_voltage"],
        status["load_percent"],
        status["battery_voltage"],
        status["on_battery"],
        status["battery_low"],
        status["flags_raw"],
    )

    return status


# ---------------------------------------------------------------------------
# Main control loop
# ---------------------------------------------------------------------------


def main_control_loop(
    cfg: Dict[str, Any], mqtt_client: Optional["mqtt.Client"]
) -> None:
    """
    Main hybrid loop that:

        - Continuously polls the UPS at `ups_poll_interval`.
        - Interprets power states (mains vs battery) and battery voltage.
        - Triggers Unraid actions based on thresholds:
              * Stop array at LOW_BATT_VOLT (on battery)
              * Shutdown Unraid at EXTRA_LOW_BATT_VOLT (on battery)
              * Start array once power restored and
                voltage >= ENABLE_ARRAY_VOLTAGE for power_stable_time.
        - Independently polls Unraid array status at
          `status_check_interval` for logging and confirmation.

    All timing in this function is based on time and the configured
    intervals. The UPS is re-discovered if the USB device disappears.
    """

    # Extract core timing / threshold values
    ups_poll_interval = int(cfg.get("ups_poll_interval", 2))
    status_check_interval = int(cfg.get("status_check_interval", 10))
    power_stable_time = int(cfg.get("power_stable_time", 180))

    low_batt = float(cfg.get("low_batt_volt", 24.7))
    extra_low_batt = float(cfg.get("extra_low_batt_volt", 22.5))
    enable_array_voltage = float(cfg.get("enable_array_voltage", 23.0))

    logger.info("UPS poll interval: %ds", ups_poll_interval)
    logger.info("Array status check interval: %ds", status_check_interval)
    logger.info("power_stable_time: %ds", power_stable_time)
    logger.info(
        "Thresholds: LOW_BATT_VOLT=%.2fV, EXTRA_LOW_BATT_VOLT=%.2fV, "
        "ENABLE_ARRAY_VOLTAGE=%.2fV",
        low_batt,
        extra_low_batt,
        enable_array_voltage,
    )

    dev: Optional[usb.core.Device] = None

    # Track mains/UPS state for edge detection
    last_on_battery: Optional[bool] = None

    # Track cumulative mains + voltage stability time
    stable_mains_time: float = 0.0

    # Wall-clock timestamp of last Unraid status check
    last_status_check_ts: float = time.time()

    # When we last attempted to start the array (so we don't hammer it)
    last_start_attempt_ts: float = 0.0
    MIN_START_RETRY_INTERVAL = 60.0  # seconds between start attempts

    # Flags about last outage (for logging only)
    array_stopped_this_outage = False
    nas_shutdown_this_outage = False

    # The script runs indefinitely under systemd
    while True:
        loop_start = time.time()

        # Ensure we have a UPS device; try to (re)discover if needed.
        if dev is None:
            try:
                dev = find_ups(cfg)
                disable_beeper_if_needed(cfg, dev)
            except Exception as e:
                logger.error("Unable to find/initialize UPS: %s", e)
                logger.info("Retrying UPS discovery in %ds", ups_poll_interval)
                time.sleep(ups_poll_interval)
                continue

        # Attempt to read UPS status
        try:
            status = read_ups_status(cfg, dev)

            # Publish each UPS sample to MQTT (if enabled).
            publish_ups_status(cfg, mqtt_client, status)

        except Exception as e:
            logger.error("Error querying UPS: %s", e)
            logger.info("Releasing UPS handle and retrying discovery next loop")
            try:
                usb.util.dispose_resources(dev)
            except Exception:
                pass
            dev = None
            time.sleep(ups_poll_interval)
            continue

        on_battery = bool(status["on_battery"])
        batt_v = float(status["battery_voltage"])

        # Detect transitions between mains and battery
        if last_on_battery is None:
            logger.info(
                "Initial UPS state: on_battery=%s, battery_voltage=%.2fV",
                on_battery,
                batt_v,
            )
        elif last_on_battery and not on_battery:
            # Transition: battery -> mains
            logger.warning("Mains power RESTORED (UPS back on line).")
            # Reset stability timer so we measure clean continuous uptime
            stable_mains_time = 0.0
        elif not last_on_battery and on_battery:
            # Transition: mains -> battery
            logger.warning("Mains power LOST – UPS is now on battery.")
            # Reset per-outage flags
            array_stopped_this_outage = False
            nas_shutdown_this_outage = False
            # Any mains stability timer is no longer relevant
            stable_mains_time = 0.0

        last_on_battery = on_battery

        # -------------------------------------------------------------------
        # Branch 1: UPS is ON BATTERY (mains failed)
        # -------------------------------------------------------------------
        if on_battery:
            # While on battery, mains stability time is meaningless
            stable_mains_time = 0.0

            # 1) Stop array when battery at or below LOW_BATT_VOLT
            if not array_stopped_this_outage and batt_v <= low_batt:
                logger.warning(
                    "Battery voltage %.2fV <= LOW_BATT_VOLT %.2fV – "
                    "requesting Unraid array STOP.",
                    batt_v,
                    low_batt,
                )

                if stop_array_via_update(cfg):
                    logger.info(
                        "Array stop request succeeded for this outage (low battery)."
                    )
                    array_stopped_this_outage = True
                else:
                    logger.error(
                        "Array stop request FAILED; will retry while "
                        "voltage remains below threshold."
                    )

            # 2) Shutdown NAS when battery at or below EXTRA_LOW_BATT_VOLT
            if not nas_shutdown_this_outage and batt_v <= extra_low_batt:
                logger.error(
                    "Battery voltage %.2fV <= EXTRA_LOW_BATT_VOLT %.2fV – "
                    "requesting Unraid SHUTDOWN.",
                    batt_v,
                    extra_low_batt,
                )

                if shutdown_nas_via_update(cfg):
                    logger.info(
                        "Shutdown request succeeded; Unraid should be powering down."
                    )
                    nas_shutdown_this_outage = True
                else:
                    logger.error(
                        "Shutdown request FAILED; will retry while "
                        "voltage remains below threshold."
                    )

        # -------------------------------------------------------------------
        # Branch 2: UPS is on MAINS (power present)
        # -------------------------------------------------------------------
        else:
            # When on mains, check whether voltage is high enough to
            # consider starting/maintaining the array.
            if batt_v >= enable_array_voltage:
                # Voltage meets our enable threshold – accumulate
                # continuous stability time.
                stable_mains_time += ups_poll_interval
            else:
                # Voltage below threshold; reset stability timer.
                if stable_mains_time > 0:
                    logger.info(
                        "Battery voltage dropped below ENABLE_ARRAY_VOLTAGE "
                        "(%.2fV < %.2fV) – resetting mains stability timer.",
                        batt_v,
                        enable_array_voltage,
                    )
                stable_mains_time = 0.0

            # When mains + voltage have been stable long enough, attempt
            # to start the array periodically.
            if stable_mains_time >= power_stable_time:
                now = time.time()
                time_since_last_start = now - last_start_attempt_ts
                if time_since_last_start >= MIN_START_RETRY_INTERVAL:
                    logger.info(
                        "Mains power + battery voltage have been stable for "
                        "%.0fs (>= %ds) and Batt=%.2fV >= %.2fV – "
                        "attempting to START Unraid array.",
                        stable_mains_time,
                        power_stable_time,
                        batt_v,
                        enable_array_voltage,
                    )
                    last_start_attempt_ts = now
                    if start_array_via_update(cfg):
                        logger.info(
                            "Start array request sent successfully; "
                            "will verify via periodic status checks."
                        )
                    else:
                        logger.error(
                            "Start array request FAILED; will retry in "
                            "%.0f seconds if conditions remain stable.",
                            MIN_START_RETRY_INTERVAL,
                        )

        # -------------------------------------------------------------------
        # Periodic Unraid status check (independent from UPS logic)
        # -------------------------------------------------------------------
        now = time.time()
        if now - last_status_check_ts >= status_check_interval:
            last_status_check_ts = now

            started, raw = get_array_status(cfg)
            if started:
                logger.info("Periodic check: Unraid array is STARTED.")
            else:
                logger.warning("Periodic check: Unraid array is NOT started.")

            if raw:
                logger.info("Unraid raw status output:\n%s", raw)

            # Publish current array state to MQTT (if enabled).
            publish_array_status(cfg, mqtt_client, started, raw)

        # Sleep so that loop timing approximates ups_poll_interval
        sleep_time = max(0.0, ups_poll_interval - (time.time() - loop_start))
        if sleep_time > 0:
            time.sleep(sleep_time)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """
    Top-level entry point.

    High-level steps:

        1. Configure logging (file or stderr fallback).
        2. Load configuration from CONFIG_PATH.
        3. Validate that host and user are set.
        4. Enter the main_control_loop(), which never returns under
           normal operation (systemd supervises the process).
    """
    setup_logging(LOG_PATH)
    logger.info("nas_monitor starting up (UPS + Unraid integration)")

    cfg = load_config(CONFIG_PATH)
    logger.info(
        "Loaded configuration: host=%r, user=%r", cfg.get("host"), cfg.get("user")
    )

    if not cfg.get("host") or not cfg.get("user"):
        logger.error("host and/or user not set in config, exiting.")
        return

    # Initialise MQTT (if enabled and available). The returned client will
    # be used for all subsequent UPS/array status publishes.
    mqtt_client = setup_mqtt(cfg)

    try:
        main_control_loop(cfg, mqtt_client)
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt; exiting.")
    except Exception as e:
        logger.exception("Unhandled exception in main_control_loop: %s", e)
    finally:
        # Cleanly stop MQTT network loop if it was started.
        if mqtt_client is not None:
            try:
                mqtt_client.loop_stop()
                mqtt_client.disconnect()
            except Exception:
                pass


if __name__ == "__main__":
    main()
