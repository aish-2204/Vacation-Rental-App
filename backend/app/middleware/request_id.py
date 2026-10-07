from uuid import uuid4

from fastapi import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestIDMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = next(
            (
                value.decode()
                for key, value in scope.get("headers", [])
                if key.lower() == b"x-request-id"
            ),
            str(uuid4()),
        )
        scope["request_id"] = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_request_id)


def request_id(request: Request) -> str:
    return request.scope.get("request_id", str(uuid4()))
