import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.throttle import LoginRateLimiter
from app.database.session import dispose_engine
from app.middleware.errors import (
    http_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.middleware.request_id import RequestIDMiddleware
from app.routers.analytics import router as analytics_router
from app.routers.auth import router as auth_router
from app.routers.bookings import router as bookings_router
from app.routers.health import router as health_router
from app.routers.host import router as host_router
from app.routers.listings import router as listings_router

settings = get_settings()
logging.basicConfig(level=settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    application.state.login_limiter = LoginRateLimiter(
        settings.login_max_attempts, settings.login_window_seconds
    )
    application.add_middleware(RequestIDMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    application.add_exception_handler(StarletteHTTPException, http_error_handler)
    application.add_exception_handler(RequestValidationError, validation_error_handler)
    application.add_exception_handler(Exception, unhandled_error_handler)
    application.include_router(health_router)
    application.include_router(auth_router, prefix="/api/v1")
    application.include_router(host_router, prefix="/api/v1")
    application.include_router(listings_router, prefix="/api/v1")
    application.include_router(bookings_router, prefix="/api/v1")
    application.include_router(analytics_router, prefix="/api/v1")
    return application


app = create_app()
