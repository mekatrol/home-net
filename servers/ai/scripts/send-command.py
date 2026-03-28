#!/usr/bin/env python3
"""Send a command to a monitored device via the watchdog WebSocket server.

Usage:
    send-command.py --list
    send-command.py <device-name> <command>

Commands:
    reboot          Immediately reboot the device
    upgrade         Run apt update + upgrade
    upgrade_reboot  Run apt update + upgrade + autoremove, then reboot

Examples:
    ./scripts/send-command.sh --list
    ./scripts/send-command.sh pi-nas upgrade_reboot
    ./scripts/send-command.sh ntp-server reboot
"""

import asyncio
import json
import ssl
import sys
from pathlib import Path

import websockets
import yaml


def load_config() -> tuple[str, str]:
    """Read token and server URL from secrets/config.yaml."""
    config_path = Path(__file__).parent.parent / "secrets" / "config.yaml"
    if not config_path.exists():
        print(f"Error: config not found at {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    server = cfg["server"]
    host = server.get("host", "0.0.0.0")
    if host == "0.0.0.0":
        host = "ai.lan"
    port = int(server.get("port", 8765))
    url = f"wss://{host}:{port}"
    return server["token"], url


async def run(args: list[str]) -> int:
    token, url = load_config()

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    try:
        async with websockets.connect(url, ssl=ssl_ctx) as ws:
            await ws.send(json.dumps({"type": "admin_auth", "token": token}))
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if resp.get("type") != "auth_ok":
                print(f"Auth failed: {resp.get('reason', 'unknown')}", file=sys.stderr)
                return 1

            if args[0] == "--list":
                await ws.send(json.dumps({"type": "admin_list"}))
                resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                devices = resp.get("devices", [])
                print(f"{'Name':<28} {'Slug':<18} {'Type':<12} {'Connected':<11} {'Ever Seen'}")
                print("─" * 82)
                for d in devices:
                    connected = "yes" if d["connected"] else ("disabled" if d["disabled"] else "no")
                    ever_seen = "yes" if d["ever_seen"] else "no"
                    print(f"{d['name']:<28} {d['device_name']:<18} {d['type']:<12} {connected:<11} {ever_seen}")
                return 0

            else:
                device_name, command = args[0], args[1]
                await ws.send(json.dumps({
                    "type": "admin_command",
                    "device_name": device_name,
                    "command": command,
                }))
                resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                if resp.get("type") == "ok":
                    print(f"OK: {resp['message']}")
                    if command in ("reboot", "upgrade_reboot"):
                        print("(device will not send a confirmation — it reboots immediately)")
                    return 0
                else:
                    print(f"Error: {resp.get('reason', 'unknown')}", file=sys.stderr)
                    return 1

    except (websockets.exceptions.WebSocketException, OSError) as exc:
        print(f"Connection failed: {exc}", file=sys.stderr)
        return 1


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        sys.exit(0)

    if sys.argv[1] == "--list":
        args = ["--list"]
    elif len(sys.argv) == 3:
        args = [sys.argv[1], sys.argv[2]]
    else:
        print("Usage: send-command.py --list  |  send-command.py <device-name> <command>", file=sys.stderr)
        sys.exit(1)

    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
