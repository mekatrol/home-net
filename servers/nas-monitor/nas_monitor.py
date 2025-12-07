#!/usr/bin/env python3
"""
nas_monitor.py

Runs on a Raspberry Pi (or similar) to:
- Wait until power has been stable for a configured duration
- Then, over SSH, tell an Unraid server to start the array using:
      /usr/local/sbin/emcmd cmdStart=Start
- Monitor Unraid array status via:
      grep -E 'arrayStarted=|mdState=' /var/local/emhttp/var.ini
- Retry start attempts at most `start_retries` times (1 min apart)
- Give up after `start_timeout` seconds for this start attempt
- Log everything to /home/pi/nas/nas-monitor.log

Configuration file: ./nas-monitor.conf
Example:

    host="nas.lan"
    user="admin"
    pwd="PasswordGoesHere"
    start_retries=5
    power_stable_time=600
    power_check_interval=5
    start_timeout=1800
    status_check_interval=10
    power_check_cmd="true"

Notes:
- SSH keys are assumed for authentication.
- `pwd` is currently ignored; keep it empty and rely on key-based SSH.
- power_check_cmd must exit 0 when power is OK, non-zero when not OK.
"""

import os
import time
import subprocess
import logging
from logging.handlers import RotatingFileHandler
from typing import Dict, Tuple, Any, List, Union

# ---------------------------------------------------------------------------
# Constants / paths
# ---------------------------------------------------------------------------

# Configuration file path
CONFIG_PATH = "./nas-monitor.conf"

# Log file path (ensure the running user has permission to write here)
LOG_PATH = "/home/pi/nas/nas-monitor.log"

# Global logger (configured in setup_logging())
logger = logging.getLogger("nas-monitor")


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging(log_path: str) -> None:
    """
    Configure logging to a rotating log file.

    - Log file: log_path
    - Rotation: 1 MB, keep 5 backups
    - Format: 2025-12-06 12:34:56 [LEVEL] message

    If the log directory or file cannot be created, fall back to stderr logging.
    """
    logger.setLevel(logging.INFO)

    # Ensure log directory exists if there is a directory component
    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception as e:
            # If we cannot create the directory, fall back to stderr logging
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s [%(levelname)s] %(message)s",
            )
            # At this point, logger has no handlers; its messages will propagate
            # to the root logger configured above.
            logger.error(
                "Failed to create log directory %s: %s; using stderr only",
                log_dir,
                e,
            )
            return

    try:
        # Create a rotating file handler for the specified log file
        handler = RotatingFileHandler(
            log_path,
            maxBytes=1_000_000,  # ~1 MB
            backupCount=5,
        )
    except Exception as e:
        # If we cannot create/open the log file, fall back to stderr logging
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

    # Configure log message format
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)

    # Avoid duplicate handlers if setup_logging is called multiple times
    if not logger.handlers:
        logger.addHandler(handler)


# ---------------------------------------------------------------------------
# Configuration loading
# ---------------------------------------------------------------------------


def load_config(path: str) -> Dict[str, Any]:
    """
    Load key=value pairs from the config file into a dict.

    Supports inline comments using '#', e.g.:
        start_timeout=1800  # 30 minutes
    """
    cfg: Dict[str, Any] = {
        "host": None,
        "user": None,
        "pwd": "",
        "start_retries": 5,
        "power_stable_time": 600,
        "power_check_interval": 5,
        "start_timeout": 1800,
        "status_check_interval": 10,
        "power_check_cmd": "true",
    }

    if not os.path.exists(path):
        logger.error("Config file not found: %s; using defaults where possible", path)
        return cfg

    try:
        with open(path, "r") as f:
            for line in f:
                # Strip leading/trailing whitespace
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                # Strip inline comments: everything after the first '#'
                if "#" in line:
                    line = line.split("#", 1)[0].strip()
                    if not line:
                        continue

                if "=" not in line:
                    logger.warning("Ignoring malformed config line (no '='): %s", line)
                    continue

                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")

                if key in (
                    "start_retries",
                    "power_stable_time",
                    "power_check_interval",
                    "start_timeout",
                    "status_check_interval",
                ):
                    try:
                        cfg[key] = int(val)
                    except ValueError:
                        logger.warning(
                            "Invalid int for %s: %s, using default %s",
                            key,
                            val,
                            cfg[key],
                        )
                else:
                    cfg[key] = val
    except Exception as e:
        logger.error("Error reading config file %s: %s", path, e)

    return cfg


# ---------------------------------------------------------------------------
# Utility command runners
# ---------------------------------------------------------------------------


def run_local_cmd(
    cmd: Union[List[str], str], shell: bool = False
) -> Tuple[int, str, str]:
    """
    Run a command locally and return (return_code, stdout, stderr).

    Parameters:
        cmd   : Command to run. If shell=True, this should be a string.
                If shell=False, this should typically be a list of arguments.
        shell : Whether to execute through the shell.

    Returns:
        (rc, out, err) where:
            rc  = integer exit code
            out = captured stdout (string)
            err = captured stderr (string)
    """
    try:
        if shell:
            # Execute command string through the shell
            result = subprocess.run(
                cmd,  # type: ignore[arg-type]
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        else:
            # Execute command directly (no shell)
            result = subprocess.run(
                cmd,  # type: ignore[arg-type]
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        # On unexpected failure, emulate non-zero exit with error in stderr
        return 1, "", str(e)


def build_ssh_command(cfg: Dict[str, Any], remote_cmd: str) -> List[str]:
    """
    Build an SSH command list to execute `remote_cmd` on the Unraid host.

    This script uses key-based SSH authentication only. Any configured `pwd`
    in the config is ignored, and a warning is logged if it is non-empty.

    Returns:
        List of arguments representing the ssh command.
    """
    host = cfg["host"]
    user = cfg["user"]
    pwd = cfg.get("pwd", "")

    # Warn if a password has been configured, because it is not used
    if pwd:
        logger.warning(
            "Config contains a password, but password-based SSH is not used; "
            "ensure key-based authentication is configured."
        )

    # Base SSH options:
    # - BatchMode=yes: do not prompt for passwords
    # - StrictHostKeyChecking=accept-new: auto-add unknown host keys
    # - ConnectTimeout=10: give up after 10 seconds if host not reachable
    ssh_cmd: List[str] = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=10",
    ]

    # Build the SSH target (user@host or host)
    if user:
        target = f"{user}@{host}"
    else:
        target = str(host)

    ssh_cmd += [target, remote_cmd]
    return ssh_cmd


def run_ssh_command(cfg: Dict[str, Any], remote_cmd: str) -> Tuple[int, str, str]:
    """
    Execute a remote command on the Unraid host via SSH.

    Logs:
        - Full SSH command (for diagnostics)
        - STDOUT and STDERR (if non-empty)
        - Exit code

    Returns:
        (rc, out, err) from the underlying SSH invocation.
    """
    ssh_cmd = build_ssh_command(cfg, remote_cmd)

    logger.info("SSH EXEC: %s", " ".join(ssh_cmd))

    rc, out, err = run_local_cmd(ssh_cmd)

    if out.strip():
        logger.info("SSH STDOUT:\n%s", out.strip())

    if err.strip():
        logger.warning("SSH STDERR:\n%s", err.strip())

    logger.info("SSH EXIT CODE: %s", rc)

    return rc, out, err


# ---------------------------------------------------------------------------
# Power / UPS monitoring
# ---------------------------------------------------------------------------


def is_power_stable(cfg: Dict[str, Any]) -> bool:
    """
    Check whether power is currently considered "stable".

    Uses the configured `power_check_cmd` which must:
        - Exit with code 0 when power is OK
        - Exit non-zero when power is NOT OK

    If `power_check_cmd` is empty or not set, power is assumed to be OK.
    """
    cmd = cfg.get("power_check_cmd", "true")

    if not cmd:
        # No check configured; assume power is OK
        logger.info("Power check command not set; assuming power is stable")
        return True

    rc, _, _ = run_local_cmd(cmd, shell=True)
    logger.info("Power check command exit code: %d", rc)
    return rc == 0


def wait_for_power_stability(cfg: Dict[str, Any]) -> None:
    """
    Block until power has been stable for at least `power_stable_time` seconds.

    Logic:
        - Check power every `power_check_interval` seconds.
        - Maintain a running count of how long power has continuously been OK.
        - Any failure resets the stability timer to 0.
        - Exit only when the accumulated stable time >= required stable time.
    """
    stable_required = cfg["power_stable_time"]
    interval = cfg["power_check_interval"]

    logger.info(
        "Waiting for power to be stable for %s seconds (check interval: %ss)...",
        stable_required,
        interval,
    )

    # Total accumulated time for which power has been continuously OK
    stable_accum = 0

    while True:
        if is_power_stable(cfg):
            # Increment stable time by the check interval
            stable_accum += interval
            remaining = max(stable_required - stable_accum, 0)
            logger.info(
                "Power OK: %s/%s seconds stable (remaining %ss)",
                stable_accum,
                stable_required,
                remaining,
            )
        else:
            # Any instability resets the timer
            if stable_accum > 0:
                logger.warning("Power unstable; resetting stability timer")
            stable_accum = 0
            logger.info(
                "Stability countdown reset; waiting for continuous stable power"
            )

        # If we've met or exceeded the required stable time, we can proceed
        if stable_accum >= stable_required:
            logger.info(
                "Power has been stable for the required duration (%ss) — continuing",
                stable_required,
            )
            return

        # Sleep with a 1-second countdown until the next power check
        for sec in range(interval, 0, -1):
            logger.info("Next power check in %ss", sec)
            time.sleep(1)


# ---------------------------------------------------------------------------
# Unraid array control
# ---------------------------------------------------------------------------


def get_array_status(cfg: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Query Unraid for array status via /var/local/emhttp/var.ini.

    The command executed is:
        grep -E 'arrayStarted=|mdState=|fsState=' /var/local/emhttp/var.ini

    Returns:
        (started_bool, raw_output)
    """
    remote_cmd = (
        "grep -E 'arrayStarted=|mdState=|fsState=' /var/local/emhttp/var.ini "
        "2>/dev/null || true"
    )
    rc, out, err = run_ssh_command(cfg, remote_cmd)

    if rc != 0:
        logger.warning("Failed to get array status (rc=%s): %s", rc, err.strip())

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
        if line.startswith("arrayStarted="):
            array_started = line
            if '"yes"' in line:
                started = True
        if line.startswith("fsState="):
            fs_state = line

    if not started:
        logger.warning(
            "Array not started. mdState=%s, arrayStarted=%s, fsState=%s",
            md_state,
            array_started,
            fs_state,
        )

    return started, out + (("\n" + err) if err else "")


def start_array_once(cfg: Dict[str, Any]) -> bool:
    """
    Start the Unraid array by mimicking the web UI:

    - Read csrf_token from /var/local/emhttp/var.ini
    - POST to /update.htm with:
        startState=STOPPED
        file=
        csrf_token=<token>
        cmdStart=Start

    This follows the official Unraid forum guidance for newer versions
    (e.g. 7.x / 7.1.4+), where direct emcmd calls are no longer sufficient
    in all cases.
    """

    # This one-liner runs on the Unraid host via SSH.
    # It:
    #   1) Extracts csrf_token from var.ini
    #   2) Tries an HTTP POST to /update.htm
    #   3) If that fails, falls back to HTTPS
    remote_cmd = (
        "CSRF=$(grep -Po '^csrf_token=\"\\K[^\"]+' /var/local/emhttp/var.ini);"
        'curl -sS -k --fail -e "http://localhost/Main" '
        "-c /tmp/unraid.cookies -b /tmp/unraid.cookies "
        '--data "startState=STOPPED&file=&csrf_token=${CSRF}&cmdStart=Start" '
        "http://localhost/update.htm || "
        'curl -sS -k --fail -e "https://localhost/Main" '
        "-c /tmp/unraid.cookies -b /tmp/unraid.cookies "
        '--data "startState=STOPPED&file=&csrf_token=${CSRF}&cmdStart=Start" '
        "https://localhost/update.htm"
    )

    logger.info("Sending start request via update.htm (curl + csrf_token)")

    rc, out, err = run_ssh_command(cfg, remote_cmd)

    # curl prints nothing on success with -sS; non-zero rc means failure
    if rc == 0:
        logger.info("Start request sent successfully via update.htm.")
    else:
        logger.error(
            "Start request via update.htm FAILED (rc=%s). stdout:\n%s\nstderr:\n%s",
            rc,
            out.strip(),
            err.strip(),
        )

    return rc == 0


# ---------------------------------------------------------------------------
# Helper: generic countdown logger
# ---------------------------------------------------------------------------


def countdown(seconds: int, label: str) -> None:
    """
    Log a countdown message every second for `seconds`.

    Example:
        countdown(10, "Next status check")
        -> logs: "Next status check in 10s", "Next status check in 9s", ...

    Parameters:
        seconds : Number of seconds to count down.
        label   : Description prefix for the countdown messages.
    """
    for remaining in range(seconds, 0, -1):
        # logger.info("%s in %ss", label, remaining)
        time.sleep(1)


# ---------------------------------------------------------------------------
# Continuous monitoring loop
# ---------------------------------------------------------------------------


def monitor_array_forever(cfg: Dict[str, Any]) -> None:
    """
    After the initial start attempt sequence, continue to monitor the array
    status indefinitely.

    - Polls Unraid using get_array_status().
    - Logs when the array is STARTED or NOT started.
    - Waits `status_check_interval` seconds between checks.
    """
    status_interval = cfg["status_check_interval"]
    last_started_state: bool | None = None

    logger.info(
        "Entering continuous monitoring loop (status interval: %ss)...",
        status_interval,
    )

    while True:
        started, raw = get_array_status(cfg)

        # Only log state transitions or first observation to reduce noise
        if last_started_state is None or started != last_started_state:
            if started:
                logger.info("Periodic check: array is STARTED")
            else:
                logger.warning("Periodic check: array is NOT started")
            if raw.strip():
                logger.info("Periodic raw status output:\n%s", raw.strip())
            last_started_state = started
        else:
            logger.info(
                "Periodic check: array state unchanged (%s)",
                "STARTED" if started else "NOT started",
            )

        countdown(status_interval, "Next periodic status check")


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def main() -> None:
    """
    Main entry point.

    High-level flow:

    1. Configure logging.
    2. Load configuration from CONFIG_PATH.
    3. Validate that `host` and `user` are set.
    4. Wait until power has been continuously stable for the configured time.
    5. Attempt to start the Unraid array:
       - Up to `start_retries` times.
       - Each start attempt at least 60 seconds apart.
       - In between, poll status every `status_check_interval` seconds.
       - Give up on this start attempt after `start_timeout` seconds.
    6. Regardless of success or timeout, continue monitoring the array
       status indefinitely at `status_check_interval` seconds.
    """
    setup_logging(LOG_PATH)
    logger.info("nas_monitor starting up")

    cfg = load_config(CONFIG_PATH)
    logger.info("Loaded configuration: host=%s, user=%s", cfg["host"], cfg["user"])

    # Basic config sanity check — we cannot proceed without host and user
    if not cfg["host"] or not cfg["user"]:
        logger.error("host/user not set in config, exiting")
        return

    # Step 1: wait for continuous power stability
    wait_for_power_stability(cfg)

    # Step 2: attempt to start array with retries and timeout
    start_retries = cfg["start_retries"]
    status_interval = cfg["status_check_interval"]
    start_timeout = cfg["start_timeout"]

    # Number of times we've sent the start command so far
    attempts = 0

    # Timestamp when the start sequence began
    start_time = time.time()

    # Timestamp when we last sent a start command (0 => never)
    last_start_cmd_time = 0.0

    logger.info(
        "Beginning array start sequence: up to %s attempts, timeout %ss",
        start_retries,
        start_timeout,
    )

    while True:
        # Check overall timeout
        elapsed = time.time() - start_time
        if elapsed > start_timeout:
            logger.error(
                "Start timeout (%ss) reached, giving up on this run",
                start_timeout,
            )
            break

        # Check current array status
        started, raw = get_array_status(cfg)
        if started:
            logger.info("Array is reported as STARTED")
            if raw.strip():
                logger.info("Raw status output:\n%s", raw.strip())
            break

        now = time.time()
        time_since_last_cmd = now - last_start_cmd_time

        # Decide whether to send a new start attempt:
        # - We still have attempts left, and
        #   * It's been >=60 seconds since the last attempt, OR
        #   * We have not yet attempted (attempts == 0)
        if attempts < start_retries and (time_since_last_cmd >= 60 or attempts == 0):
            attempts += 1
            last_start_cmd_time = now
            logger.info(
                "Sending start command attempt %s/%s",
                attempts,
                start_retries,
            )
            start_array_once(cfg)

            # After sending the command, wait for the next status check interval
            countdown(status_interval, "Next status check")
            continue

        # If we've exhausted all start attempts, just monitor status until
        # either success or timeout is reached.
        if attempts >= start_retries:
            logger.info(
                "All %s start attempts used. Monitoring until timeout or success.",
                start_retries,
            )
            countdown(status_interval, "Next status check")
            continue

        # We still have attempts left, but it's not yet time for the next retry.
        # Wait for the shorter of:
        #   - Remaining time until the 60s retry window
        #   - Next status check interval
        remaining_retry_seconds = int(60 - time_since_last_cmd)
        wait_seconds = min(remaining_retry_seconds, status_interval)

        logger.info(
            "Next start attempt not ready yet (retry in %ss, status interval %ss).",
            remaining_retry_seconds,
            status_interval,
        )
        countdown(wait_seconds, "Next retry/status check")

    # Step 3: after the initial start attempt sequence (success or timeout),
    # enter the continuous monitoring loop.
    logger.info(
        "Initial start sequence completed (success or timeout). "
        "Continuing with periodic status monitoring."
    )
    monitor_array_forever(cfg)


if __name__ == "__main__":
    main()
