from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.api import router as api_router
from backend.app.config import Settings, get_settings
from backend.app.engines.base import EngineError
from backend.app.engines.memory_manager import MemoryManager, get_memory_manager
from backend.app.media import MediaValidationError

logger = logging.getLogger(__name__)

_HTTP_STATUS_CODE_MAP: dict[int, str] = {
    400: "BAD_REQUEST",
    404: "NOT_FOUND",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "TOO_MANY_REQUESTS",
    503: "MODEL_UNAVAILABLE",
}


def _register_exception_handlers(app: FastAPI) -> None:
    """Đăng ký bộ xử lý lỗi JSON thống nhất theo API Contract."""

    @app.exception_handler(MediaValidationError)
    async def _handle_media_error(_request: Request, exc: MediaValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "code": exc.code},
        )

    @app.exception_handler(EngineError)
    async def _handle_engine_error(_request: Request, exc: EngineError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "code": exc.code},
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        first_msg = errors[0].get("msg", "Dữ liệu đầu vào không hợp lệ.") if errors else "Dữ liệu đầu vào không hợp lệ."
        return JSONResponse(
            status_code=422,
            content={"detail": str(first_msg), "code": "VALIDATION_ERROR"},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict) and "detail" in exc.detail and "code" in exc.detail:
            payload = {"detail": str(exc.detail["detail"]), "code": str(exc.detail["code"])}
        else:
            code = _HTTP_STATUS_CODE_MAP.get(exc.status_code, "INTERNAL_ERROR")
            payload = {"detail": str(exc.detail), "code": code}
        return JSONResponse(status_code=exc.status_code, content=payload)

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled backend error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Lỗi hệ thống nội bộ khi xử lý yêu cầu.",
                "code": "INTERNAL_ERROR",
            },
        )


def _mount_frontend(app: FastAPI, cfg: Settings) -> None:
    """Phục vụ frontend/dist (SPA) nếu đã build, không làm ảnh hưởng đường dẫn /api."""
    dist_dir = Path(cfg.frontend_dist_dir)
    index_html = dist_dir / "index.html"

    if dist_dir.is_dir() and index_html.is_file():
        dist_root = dist_dir.resolve()
        assets_dir = dist_dir / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

        @app.get("/", include_in_schema=False)
        async def _serve_root() -> FileResponse:
            return FileResponse(index_html)

        @app.get("/{full_path:path}", include_in_schema=False)
        async def _serve_spa(full_path: str) -> Any:
            normalized = full_path.lstrip("/")
            if normalized == "api" or normalized.startswith("api/"):
                raise StarletteHTTPException(status_code=404, detail="Endpoint không tồn tại.")

            if normalized:
                candidate = (dist_root / normalized).resolve()
                if candidate.is_relative_to(dist_root) and candidate.is_file():
                    return FileResponse(candidate)

            return FileResponse(index_html)
    else:

        @app.get("/", include_in_schema=False)
        async def _api_root_info() -> dict[str, Any]:
            return {
                "name": cfg.app_name,
                "status": "ok",
                "api_prefix": cfg.api_prefix,
            }


def create_app(
    settings: Settings | None = None,
    memory_manager: MemoryManager | None = None,
) -> FastAPI:
    """Khởi tạo ứng dụng FastAPI hoàn chỉnh với CORS, Lifecycle Reaper, Concurrency và SPA Static."""
    cfg = settings if settings is not None else get_settings()
    manager = memory_manager if memory_manager is not None else get_memory_manager()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.started_at = time.monotonic()
        application.state.job_semaphore = asyncio.Semaphore(max(1, int(cfg.max_concurrent_jobs)))
        application.state.memory_manager.start_reaper()
        try:
            yield
        finally:
            application.state.memory_manager.stop_reaper()

    application = FastAPI(
        title=cfg.app_name,
        version="1.0.0",
        lifespan=lifespan,
    )

    application.state.settings = cfg
    application.state.memory_manager = manager
    application.state.job_semaphore = None
    application.state.started_at = time.monotonic()

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(cfg.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Latency-Ms", "X-Backend-Used", "X-Ram-Used-MB"],
    )

    _register_exception_handlers(application)
    application.include_router(api_router, prefix=cfg.api_prefix)
    _mount_frontend(application, cfg)
    return application


app = create_app()
