from __future__ import annotations

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Chuẩn JSON trả về khi xảy ra lỗi HTTP API."""

    detail: str
    code: str


class HealthResponse(BaseModel):
    """Phản hồi kiểm tra sức khỏe và trạng thái model đang nạp."""

    status: str = "ok"
    loaded_models: list[str] = Field(default_factory=list)
    low_mem_mode: bool
    uptime_s: float


class HardwareDevice(BaseModel):
    """Mô tả một thiết bị/backend suy luận được phát hiện trên máy."""

    id: str
    name: str
    type: str
    available: bool = True


class HardwareResponse(BaseModel):
    """Phản hồi thông tin CPU, GPU/NPU và RAM thực tế của hệ thống."""

    cpu: str
    devices: list[HardwareDevice] = Field(default_factory=list)
    recommended_backend: str
    total_ram_mb: int
    available_ram_mb: int


class DetectResponse(BaseModel):
    """Phản hồi nhận diện watermark tự động từ Florence-2."""

    status: str = "success"
    mask_base64: str
    bboxes: list[list[int]] = Field(default_factory=list)
    width: int
    height: int
    latency_ms: float
    backend_used: str


class UnloadResponse(BaseModel):
    """Phản hồi giải phóng RAM/VRAM chủ động."""

    status: str = "ok"
    unloaded: list[str] = Field(default_factory=list)
    available_ram_mb: int
