import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from prometheus_fastapi_instrumentator import Instrumentator

from app.core.config import settings
from app.core.logging_config import setup_logging
from app.core.database import engine, AsyncSessionLocal
from app.core.limiter import limiter
from app.routers import auth, users, routes, comments, feed, ai, notifications, upload, ws, reports, admin, subscriptions, payments

setup_logging(level=settings.LOG_LEVEL, environment=settings.ENVIRONMENT)
logger = logging.getLogger(__name__)

_CLEANUP_INTERVAL_SECONDS = settings.TOKEN_CLEANUP_INTERVAL_SECONDS


async def _cleanup_loop() -> None:
    """Фоновая задача: удаляет истёкшие записи из token_blacklist раз в час."""
    from app.services.auth_service import cleanup_expired_tokens
    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
        try:
            async with AsyncSessionLocal() as db:
                deleted = await cleanup_expired_tokens(db)
                await db.commit()
                if deleted:
                    logger.info("token_blacklist cleanup: removed %d expired entries", deleted)
        except Exception:
            logger.exception("token_blacklist cleanup failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_task = asyncio.create_task(_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        await engine.dispose()


app = FastAPI(
    title="Trail Social API",
    description="Backend API for the Trail Social hiking network app",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Prometheus метрики — эндпоинт /metrics
Instrumentator(excluded_handlers=["/metrics", "/health", "/uploads"]).instrument(app).expose(app)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _make_json_safe(obj):
    """Рекурсивно преобразует объекты в JSON-сериализуемые типы.
    Нужно для Pydantic v2, который кладёт Exception-объекты в ctx полях ошибок."""
    if isinstance(obj, dict):
        return {k: _make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_safe(v) for v in obj]
    if isinstance(obj, Exception):
        return str(obj)
    return obj


# Exception handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_make_json_safe({"detail": exc.errors(), "body": exc.body}),
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    logger.exception("Database error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Database error"},
    )


_request_logger = logging.getLogger("app.http")

_SKIP_LOG_PREFIXES = ("/uploads/", "/health", "/docs", "/openapi", "/redoc")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    # Не логируем статику и health-check
    if request.url.path.startswith(_SKIP_LOG_PREFIXES):
        return await call_next(request)

    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000

    level = logging.WARNING if response.status_code >= 500 else logging.INFO
    _request_logger.log(
        level,
        "%s %s %d %.0fms",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


# Routers
API_PREFIX = "/api/v1"

app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(users.router, prefix=API_PREFIX)
app.include_router(routes.router, prefix=API_PREFIX)
app.include_router(comments.router, prefix=API_PREFIX)
app.include_router(feed.router, prefix=API_PREFIX)
app.include_router(ai.router, prefix=API_PREFIX)
app.include_router(notifications.router, prefix=API_PREFIX)
app.include_router(upload.router, prefix=API_PREFIX)
app.include_router(reports.router, prefix=API_PREFIX)
app.include_router(admin.router, prefix=API_PREFIX)
app.include_router(subscriptions.router, prefix=API_PREFIX)
app.include_router(payments.router, prefix=API_PREFIX)
app.include_router(ws.router)

# Static files — раздача загруженных изображений
_upload_dir = Path(settings.UPLOAD_DIR)
_upload_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_upload_dir)), name="uploads")


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}
