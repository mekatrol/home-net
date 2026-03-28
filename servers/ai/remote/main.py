#!/usr/bin/env python3
"""Watchdog WebSocket client.

Connects to the home monitor server via wss://, sends heartbeats, forwards
logs, and executes commands sent by the server (reboot, upgrade, etc.).
"""

import asyncio
import json
import logging
import ssl
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import websockets
import yaml

LOG_FILE = Path("/var/log/watchdog/watchdog.log")
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("watchdog")
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


def load_config() -> dict:
    config_path = Path("/etc/watchdog/config.yaml")
    if not config_path.exists():
        config_path = Path(__file__).parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Remote log handler — forwards log records to the server over WebSocket
# ---------------------------------------------------------------------------

class RemoteLogHandler(logging.Handler):
    """Queues log records for forwarding to the server during the next heartbeat."""

    def __init__(self):
        super().__init__()
        self._queue: asyncio.Queue | None = None

    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        self._queue = asyncio.Queue()
        self._loop = loop

    def emit(self, record: logging.LogRecord) -> None:
        if self._queue is None:
            return
        msg = {
            "type": "log",
            "level": record.levelname.lower(),
            "message": self.format(record),
            "timestamp": datetime.now().astimezone().isoformat(),
        }
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, msg)
        except Exception:
            pass

    async def drain(self, ws) -> None:
        """Send all queued log messages to the server."""
        while self._queue and not self._queue.empty():
            try:
                msg = self._queue.get_nowait()
                await ws.send(json.dumps(msg))
            except Exception:
                break


remote_handler = RemoteLogHandler()
remote_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))


# ---------------------------------------------------------------------------
# Command execution
# ---------------------------------------------------------------------------

ALLOWED_COMMANDS = {"reboot", "upgrade", "upgrade_reboot"}
UPGRADE_TIMEOUT = 600  # seconds; apt upgrade can be slow


async def run_command(command: str) -> tuple[bool, str, str]:
    """Execute an allowed system command. Returns (success, stdout, stderr)."""
    if command not in ALLOWED_COMMANDS:
        return False, "", f"command not allowed: {command}"

    try:
        if command == "reboot":
            # Fire-and-forget — we will be killed by the reboot
            await asyncio.create_subprocess_exec("sudo", "/sbin/reboot")
            return True, "", ""

        if command == "upgrade":
            ok, out, err = await _apt_update_upgrade()
            return ok, out, err

        if command == "upgrade_reboot":
            ok, out, err = await _apt_update_upgrade(autoremove=True)
            if ok:
                await asyncio.create_subprocess_exec("sudo", "/sbin/reboot")
            return ok, out, err

    except asyncio.TimeoutError:
        return False, "", "command timed out"
    except Exception as exc:
        return False, "", str(exc)

    return False, "", "unhandled command"


APT_ENV = {"DEBIAN_FRONTEND": "noninteractive", "PATH": "/usr/bin:/usr/sbin:/bin:/sbin"}


async def _apt_update_upgrade(autoremove: bool = False) -> tuple[bool, str, str]:
    stdout_parts: list[str] = []

    async def run(*args) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=APT_ENV,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=UPGRADE_TIMEOUT)
        return proc.returncode, out.decode()[:2000], err.decode()[:500]

    # -o DPkg::Lock::Timeout=60 waits up to 60s for the dpkg lock rather than failing immediately
    apt = ("sudo", "/usr/bin/apt-get", "-y", "-q", "-o", "DPkg::Lock::Timeout=60")

    rc, out, err = await run(*apt, "update")
    stdout_parts.append(out)
    if rc != 0:
        return False, "\n".join(stdout_parts), f"apt update failed (rc={rc}): {err}"

    rc, out, err = await run(*apt, "upgrade")
    stdout_parts.append(out)
    if rc != 0:
        return False, "\n".join(stdout_parts), f"apt upgrade failed (rc={rc}): {err}"

    if autoremove:
        rc, out, err = await run(*apt, "autoremove")
        stdout_parts.append(out)
        if rc != 0:
            return False, "\n".join(stdout_parts), f"apt autoremove failed (rc={rc}): {err}"

    return True, "\n".join(stdout_parts), ""


# ---------------------------------------------------------------------------
# WebSocket client
# ---------------------------------------------------------------------------

async def watchdog_client(cfg: dict) -> None:
    server_url: str = cfg["server"]["url"]
    device_name: str = cfg["server"]["device_name"]
    token: str = cfg["server"]["token"]
    heartbeat_interval: int = int(cfg.get("heartbeat_interval", 30))

    # Skip cert verification — self-signed cert on home LAN
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    loop = asyncio.get_running_loop()
    remote_handler.attach(loop)
    log.addHandler(remote_handler)

    backoff = 5
    max_backoff = 120

    while True:
        try:
            log.info("Connecting to %s as '%s'", server_url, device_name)
            async with websockets.connect(server_url, ssl=ssl_ctx) as ws:
                backoff = 5  # reset on successful connection

                # Authenticate
                await ws.send(json.dumps({
                    "type": "auth",
                    "device_name": device_name,
                    "token": token,
                }))

                resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                if resp.get("type") != "auth_ok":
                    reason = resp.get("reason", "unknown")
                    log.error("Auth rejected by server: %s — retrying in 60s", reason)
                    await asyncio.sleep(60)
                    continue

                log.info("Connected. Sending heartbeats every %ds", heartbeat_interval)

                await asyncio.gather(
                    _heartbeat_loop(ws, heartbeat_interval),
                    _receive_loop(ws),
                )

        except (websockets.exceptions.WebSocketException, OSError, asyncio.TimeoutError) as exc:
            log.warning("Connection lost: %s — retrying in %ds", exc, backoff)
        except Exception as exc:
            log.error("Unexpected error: %s — retrying in %ds", exc, backoff)

        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, max_backoff)


async def _heartbeat_loop(ws, interval: int) -> None:
    while True:
        await ws.send(json.dumps({
            "type": "heartbeat",
            "timestamp": datetime.now().astimezone().isoformat(),
        }))
        await remote_handler.drain(ws)
        await asyncio.sleep(interval)


async def _receive_loop(ws) -> None:
    async for raw in ws:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue

        mtype = msg.get("type")
        if mtype == "command":
            cmd = msg.get("command", "")
            cmd_id = msg.get("command_id", "")
            log.info("Executing command: %s (id=%s)", cmd, cmd_id)

            success, output, error = await run_command(cmd)

            if error:
                log.warning("Command '%s' failed: %s", cmd, error[:200])
            else:
                log.info("Command '%s' completed: success=%s", cmd, success)

            try:
                await ws.send(json.dumps({
                    "type": "command_result",
                    "command_id": cmd_id,
                    "success": success,
                    "output": output,
                    "error": error,
                }))
            except Exception:
                pass  # may be rebooting — fine if this fails
        else:
            log.debug("Unknown message type from server: %s", mtype)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    cfg = load_config()
    await watchdog_client(cfg)


if __name__ == "__main__":
    asyncio.run(main())
