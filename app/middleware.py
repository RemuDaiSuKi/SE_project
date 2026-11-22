"""只接受本機 Host 標頭（防止 DNS rebinding）。"""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Receive, Scope, Send

from .errors import error_body


class LocalHostOnlyMiddleware:
    def __init__(self, app: ASGIApp, port: int) -> None:
        self.app = app
        self.allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            self.allowed.update({"127.0.0.1", "localhost"})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        host = ""
        for name, value in scope.get("headers", []):
            if name == b"host":
                host = value.decode("latin-1").strip().lower()
                break
        if host in self.allowed:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = json.dumps(error_body("HOST_NOT_ALLOWED", "不允許的連線來源"),
                          ensure_ascii=False).encode("utf-8")
        await send({"type": "http.response.start", "status": 400,
                    "headers": [(b"content-type", b"application/json; charset=utf-8"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
