import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.middleware.request_id import request_id

logger = logging.getLogger(__name__)


def error_payload(code: str, message: str, details: list[dict[str, str]], request: Request) -> dict:
    return {
        "success": False,
        "error": {"code": code, "message": message, "details": details},
        "request_id": request_id(request),
    }


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    code = getattr(exc, "code", "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR")
    return JSONResponse(
        content=error_payload(code, detail, getattr(exc, "details", []), request),
        status_code=exc.status_code,
        headers=exc.headers,
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    if any(error["type"] == "json_invalid" for error in exc.errors()):
        return JSONResponse(
            content=error_payload("INVALID_JSON", "Malformed JSON request", [], request),
            status_code=400,
        )
    details = [
        {"field": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
        for error in exc.errors()
    ]
    return JSONResponse(
        content=error_payload("VALIDATION_ERROR", "Invalid request", details, request),
        status_code=422,
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Exception text/tracebacks can contain SQL row details or credentials.
    logger.error(
        "Unhandled request error (%s), request_id=%s", type(exc).__name__, request_id(request)
    )
    return JSONResponse(
        content=error_payload("INTERNAL_SERVER_ERROR", "Unexpected server error", [], request),
        status_code=500,
        headers={"X-Request-ID": request_id(request)},
    )
