"""ASGI middleware that assigns a request id, records the client address and logs each request."""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import client_ip_var, request_id_var, user_agent_var

logger = logging.getLogger("app.request")

_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_QUIET_PATHS = frozenset({"/health", "/ready"})


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        incoming = headers.get("x-request-id", "")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        client = scope.get("client")
        tokens = (
            request_id_var.set(request_id),
            client_ip_var.set(client[0] if client else None),
            user_agent_var.set((headers.get("user-agent") or "")[:300] or None),
        )
        status = 500
        started = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message).append("X-Request-ID", request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            if scope["path"] not in _QUIET_PATHS:
                logger.info(
                    "%s %s %s",
                    scope["method"],
                    scope["path"],
                    status,
                    extra={"status": status, "duration_ms": round((time.perf_counter() - started) * 1000, 1)},
                )
            request_id_var.reset(tokens[0])
            client_ip_var.reset(tokens[1])
            user_agent_var.reset(tokens[2])
