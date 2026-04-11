from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from aiohttp import web

from watchdog_logging import log
from watchdog_redirects import (
    load_redirects_config,
    normalize_redirects_config,
    save_redirects_config,
)


class RedirectConfigStore:
    def __init__(self, path: Path):
        self._path = path
        self._lock = asyncio.Lock()
        self._cache = load_redirects_config(path)

    @property
    def path(self) -> Path:
        return self._path

    async def get(self) -> dict[str, list[dict[str, str]]]:
        async with self._lock:
            self._cache = load_redirects_config(self._path)
            return _clone_redirects(self._cache)

    async def save(self, redirects: dict[str, list[dict[str, str]]]) -> dict[str, list[dict[str, str]]]:
        async with self._lock:
            self._cache = save_redirects_config(self._path, redirects)
            return _clone_redirects(self._cache)


def create_web_app(web_pwd: str, store: RedirectConfigStore) -> web.Application:
    app = web.Application()
    app["web_pwd"] = web_pwd
    app["redirect_store"] = store

    app.router.add_get("/api/health", api_health)
    app.router.add_get("/api/redirects", api_get_redirects)
    app.router.add_put("/api/redirects", api_put_redirects)

    web_dir = Path(__file__).parent / "web"
    app.router.add_get("/", serve_index)
    app.router.add_static("/assets", web_dir / "assets")
    app.router.add_get("/{tail:.*}", serve_index)
    return app


async def start_web_server(
    host: str,
    port: int,
    web_pwd: str,
    store: RedirectConfigStore,
) -> None:
    app = create_web_app(web_pwd, store)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info("Web server listening on http://%s:%d", host, port)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


async def api_health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def api_get_redirects(request: web.Request) -> web.Response:
    _require_token(request)
    store: RedirectConfigStore = request.app["redirect_store"]
    redirects = await store.get()
    return web.json_response({"redirects": _serialize_redirects_for_api(redirects)})


async def api_put_redirects(request: web.Request) -> web.Response:
    _require_token(request)
    payload = await request.json()
    redirects = payload.get("redirects")
    if not isinstance(redirects, list):
        raise web.HTTPBadRequest(reason="'redirects' must be a list")

    normalized_payload = _normalize_redirects_payload(redirects)
    store: RedirectConfigStore = request.app["redirect_store"]
    saved = await store.save(normalized_payload)
    log.info("Redirect config updated via web UI: %d catchall destinations", len(saved))
    return web.json_response({"redirects": _serialize_redirects_for_api(saved)})


async def serve_index(_: web.Request) -> web.FileResponse:
    return web.FileResponse(Path(__file__).parent / "web" / "index.html")


def _require_token(request: web.Request) -> None:
    expected = request.app["web_pwd"]
    auth_header = request.headers.get("Authorization", "")
    provided = ""
    if auth_header.startswith("Bearer "):
        provided = auth_header[7:].strip()
    if not provided:
        provided = request.headers.get("X-Admin-Token", "").strip()
    if provided != expected:
        raise web.HTTPUnauthorized(reason="Invalid web password")


def _normalize_redirects_payload(
    redirects: list[dict[str, Any]],
) -> dict[str, list[dict[str, str]]]:
    normalized_input: dict[str, list[dict[str, str]]] = {}
    for redirect in redirects:
        if not isinstance(redirect, dict):
            continue
        catchall_email = str(redirect.get("catchall_email", "")).strip().lower()
        if "@" not in catchall_email:
            continue
        rules: list[dict[str, str]] = []
        for rule in redirect.get("rules", []):
            if not isinstance(rule, dict):
                continue
            rule_type = str(rule.get("type", "")).strip().lower()
            value = str(rule.get("value", "")).strip()
            if rule_type not in {"exact", "regex"} or not value:
                continue
            if rule_type == "regex":
                try:
                    re.compile(value)
                except re.error as exc:
                    raise web.HTTPBadRequest(
                        reason=f"Invalid regex for {catchall_email}: {value} ({exc})"
                    ) from exc
            rules.append({"type": rule_type, "value": value})
        normalized_input[catchall_email] = rules
    return normalize_redirects_config({"redirects": normalized_input})


def _serialize_redirects_for_api(
    redirects: dict[str, list[dict[str, str]]]
) -> list[dict[str, Any]]:
    return [
        {
            "catchall_email": catchall_email,
            "rules": rules,
        }
        for catchall_email, rules in sorted(redirects.items())
    ]


def _clone_redirects(
    redirects: dict[str, list[dict[str, str]]]
) -> dict[str, list[dict[str, str]]]:
    return {
        catchall_email: [dict(rule) for rule in rules]
        for catchall_email, rules in redirects.items()
    }
