from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from backend.app.config import Settings, get_settings
from backend.app.engines.florence_detector import sanitize_bboxes
from backend.app.engines.memory_manager import MemoryManager, get_memory_manager
from backend.app.media import (
    MediaValidationError,
    VALID_DEWATERMARK_MODES,
    bboxes_to_mask,
    detect_template_watermark_bboxes,
    dilate_mask,
    encode_mask_base64,
    encode_png_with_alpha,
    load_mask_image,
    restore_watermark_region,
    validate_and_load_image,
)
from backend.app.observability import probe_hardware
from backend.app.schemas import (
    DetectResponse,
    HardwareResponse,
    HealthResponse,
    UnloadResponse,
)

router = APIRouter(tags=["watermark-studio"])


def _get_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        settings = get_settings()
        request.app.state.settings = settings
    return settings


def _get_memory_manager(request: Request) -> MemoryManager:
    manager = getattr(request.app.state, "memory_manager", None)
    if manager is None:
        manager = get_memory_manager()
        request.app.state.memory_manager = manager
    return manager


def _get_job_semaphore(request: Request, settings: Settings) -> asyncio.Semaphore:
    semaphore = getattr(request.app.state, "job_semaphore", None)
    if semaphore is None:
        semaphore = asyncio.Semaphore(max(1, settings.max_concurrent_jobs))
        request.app.state.job_semaphore = semaphore
    return semaphore


def _resolve_dilation(dilation_px: int | None, default_px: int) -> int:
    value = default_px if dilation_px is None else int(dilation_px)
    if value < 0 or value > 25:
        raise MediaValidationError(
            "Tham số dilation_px phải nằm trong khoảng 0..25.",
            status_code=422,
            code="VALIDATION_ERROR",
        )
    return value


async def _read_upload_bounded(upload: UploadFile, max_size_mb: int, label: str) -> bytes:
    """Đọc upload có chặn trần byte tối đa để bảo vệ RAM trước khi giải mã ảnh."""
    max_bytes = max(1, int(max_size_mb)) * 1024 * 1024
    try:
        data = await upload.read(max_bytes + 1)
    finally:
        await upload.close()

    if not data:
        raise MediaValidationError(
            f"File {label} rỗng.",
            status_code=400,
            code="BAD_REQUEST",
        )
    if len(data) > max_bytes:
        raise MediaValidationError(
            f"Dung lượng file {label} vượt quá giới hạn {max_size_mb} MB.",
            status_code=413,
            code="PAYLOAD_TOO_LARGE",
        )
    return data


@router.get("/health", response_model=HealthResponse)
async def get_health(request: Request) -> HealthResponse:
    """Kiểm tra trạng thái dịch vụ và các AI model đang nằm trong RAM/VRAM."""
    manager = _get_memory_manager(request)
    started_at = getattr(request.app.state, "started_at", None)
    uptime_s = round(max(0.0, time.monotonic() - started_at), 2) if started_at is not None else 0.0
    return HealthResponse(
        status="ok",
        loaded_models=manager.loaded_models(),
        low_mem_mode=manager.low_mem_mode,
        uptime_s=uptime_s,
    )


@router.get("/hardware", response_model=HardwareResponse)
async def get_hardware() -> HardwareResponse:
    """Trả về thông tin CPU, GPU/iGPU/NPU khả dụng và dung lượng RAM trống."""
    info = await run_in_threadpool(probe_hardware)
    return HardwareResponse(**info)


@router.post("/detect", response_model=DetectResponse)
async def detect_watermark(
    request: Request,
    image: UploadFile = File(...),
    prompt: str | None = Form(default=None),
    dilation_px: int | None = Form(default=None),
    backend: str | None = Form(default=None),
) -> DetectResponse:
    """Tự động nhận diện vùng watermark/text bằng Florence-2 và trả về binary mask base64."""
    settings = _get_settings(request)
    manager = _get_memory_manager(request)
    semaphore = _get_job_semaphore(request, settings)

    eff_dilation = _resolve_dilation(dilation_px, settings.default_dilation_px)
    eff_prompt = prompt.strip() if (prompt is not None and prompt.strip()) else settings.default_detect_prompt
    eff_backend = backend.strip() if (backend is not None and backend.strip()) else settings.execution_backend

    image_bytes = await _read_upload_bounded(image, settings.max_input_size_mb, label="ảnh")

    def _run_detect() -> dict[str, Any]:
        started = time.perf_counter()
        rgb_uint8, _alpha_uint8, (orig_w, orig_h) = validate_and_load_image(
            image_bytes,
            max_size_mb=settings.max_input_size_mb,
            max_res_px=settings.max_resolution_px,
        )
        with manager.lease("florence2", backend=eff_backend) as engine:
            det = engine.predict(rgb_uint8, prompt=eff_prompt, backend=eff_backend)

        template_boxes = detect_template_watermark_bboxes(rgb_uint8)
        combined_bboxes = sanitize_bboxes(
            list(det["bboxes"]) + template_boxes,
            width=orig_w,
            height=orig_h,
        )
        raw_mask = bboxes_to_mask(combined_bboxes, width=orig_w, height=orig_h)
        final_mask = dilate_mask(raw_mask, kernel_px=eff_dilation) if eff_dilation > 0 else raw_mask
        mask_b64 = encode_mask_base64(final_mask)
        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)

        return {
            "status": "success",
            "mask_base64": mask_b64,
            "bboxes": combined_bboxes,
            "width": orig_w,
            "height": orig_h,
            "latency_ms": latency_ms,
            "backend_used": str(det.get("backend_used") or engine.backend_used),
        }

    async with semaphore:
        payload = await run_in_threadpool(_run_detect)

    return DetectResponse(**payload)


@router.post("/inpaint")
async def inpaint_watermark(
    request: Request,
    image: UploadFile = File(...),
    mask: UploadFile = File(...),
    dilation_px: int | None = Form(default=None),
    backend: str | None = Form(default=None),
    low_mem_mode: bool | None = Form(default=None),
    mode: str | None = Form(default="auto"),
) -> Response:
    """Xóa watermark theo 3 tầng (Reverse Alpha / Blind Decomposition / Big-LaMa), bảo toàn pixel ngoài mask & kênh Alpha gốc."""
    settings = _get_settings(request)
    manager = _get_memory_manager(request)
    semaphore = _get_job_semaphore(request, settings)

    eff_dilation = _resolve_dilation(dilation_px, settings.default_dilation_px)
    eff_backend = backend.strip() if (backend is not None and backend.strip()) else settings.execution_backend
    eff_mode = (mode or "auto").strip().lower()
    if eff_mode not in VALID_DEWATERMARK_MODES:
        eff_mode = "auto"

    image_bytes = await _read_upload_bounded(image, settings.max_input_size_mb, label="ảnh")
    mask_bytes = await _read_upload_bounded(mask, settings.max_input_size_mb, label="mask")

    def _run_inpaint() -> tuple[bytes, dict[str, str]]:
        started = time.perf_counter()
        rgb_uint8, alpha_uint8, (orig_w, orig_h) = validate_and_load_image(
            image_bytes,
            max_size_mb=settings.max_input_size_mb,
            max_res_px=settings.max_resolution_px,
        )
        mask_uint8 = load_mask_image(
            mask_bytes,
            target_size=(orig_w, orig_h),
            max_size_mb=settings.max_input_size_mb,
        )
        dilated_mask = dilate_mask(mask_uint8, kernel_px=eff_dilation)

        with manager.lease("lama", backend=eff_backend, low_mem_mode=low_mem_mode) as engine:
            inpainted_rgb = engine.predict(rgb_uint8, dilated_mask, backend=eff_backend)
            backend_used = str(engine.backend_used)

        final_rgb, method_used = restore_watermark_region(
            rgb_uint8,
            inpainted_rgb,
            mask_uint8,
            dilated_mask,
            mode=eff_mode,
            feather_px=max(2, eff_dilation),
        )
        reported_backend = backend_used if backend_used == "mock" else f"{backend_used} · {method_used}"
        png_bytes = encode_png_with_alpha(final_rgb, alpha_uint8)
        latency_ms = (time.perf_counter() - started) * 1000.0
        ram_rss_mb = manager.get_memory_snapshot().get("process_rss_mb", 0)

        headers = {
            "X-Latency-Ms": f"{latency_ms:.2f}",
            "X-Backend-Used": reported_backend,
            "X-Ram-Used-MB": str(ram_rss_mb),
            "Cache-Control": "no-store",
        }
        return png_bytes, headers

    async with semaphore:
        png_bytes, headers = await run_in_threadpool(_run_inpaint)

    return Response(content=png_bytes, media_type="image/png", headers=headers)


@router.post("/models/unload", response_model=UnloadResponse)
async def unload_models(request: Request) -> UnloadResponse:
    """Giải phóng toàn bộ AI models khỏi RAM/VRAM ngay lập tức."""
    manager = _get_memory_manager(request)

    def _do_unload() -> tuple[list[str], int]:
        unloaded = manager.unload_all()
        snapshot = manager.get_memory_snapshot()
        return unloaded, int(snapshot.get("available_ram_mb", 0))

    unloaded, available_ram_mb = await run_in_threadpool(_do_unload)
    return UnloadResponse(
        status="ok",
        unloaded=unloaded,
        available_ram_mb=available_ram_mb,
    )
