from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    _HAS_PYDANTIC_SETTINGS = True
except ImportError:  # Fallback sạch nếu chưa cài pydantic-settings
    from pydantic import BaseModel as BaseSettings
    SettingsConfigDict = None  # type: ignore[assignment]
    _HAS_PYDANTIC_SETTINGS = False


_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Cấu hình trung tâm cho AI Watermark Studio (đọc từ .env và biến môi trường)."""

    app_name: str = "AI Watermark Studio"
    app_host: str = Field(default_factory=lambda: os.getenv("APP_HOST", "127.0.0.1"))
    app_port: int = Field(default_factory=lambda: int(os.getenv("APP_PORT", "8000")))
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:8000",
        ]
    )

    # Hardware & Memory
    execution_backend: str = Field(
        default_factory=lambda: os.getenv("EXECUTION_BACKEND", "auto")
    )
    quantization_policy: str = Field(
        default_factory=lambda: os.getenv("QUANTIZATION_POLICY", "fp16")
    )
    low_mem_mode: bool = Field(
        default_factory=lambda: os.getenv("LOW_MEM_MODE", "true").lower() == "true"
    )
    ram_budget_gb: int = Field(
        default_factory=lambda: int(os.getenv("RAM_BUDGET_GB", "16"))
    )
    auto_unload_seconds: int = Field(
        default_factory=lambda: int(os.getenv("AUTO_UNLOAD_SECONDS", "180"))
    )
    max_concurrent_jobs: int = Field(
        default_factory=lambda: int(os.getenv("MAX_CONCURRENT_JOBS", "1"))
    )

    # Media & AI Models
    max_input_size_mb: int = Field(
        default_factory=lambda: int(os.getenv("MAX_INPUT_SIZE_MB", "20"))
    )
    max_resolution_px: int = Field(
        default_factory=lambda: int(os.getenv("MAX_RESOLUTION_PX", "4096"))
    )
    default_dilation_px: int = Field(
        default_factory=lambda: int(os.getenv("DEFAULT_DILATION_PX", "5"))
    )
    default_detect_prompt: str = Field(
        default_factory=lambda: os.getenv(
            "DEFAULT_DETECT_PROMPT", "watermark, logo, text, stamp, caption"
        )
    )
    florence_model_id: str = Field(
        default_factory=lambda: os.getenv("FLORENCE_MODEL_ID", "microsoft/Florence-2-base")
    )
    florence_revision: str = Field(
        default_factory=lambda: os.getenv("FLORENCE_REVISION", "main")
    )

    # Paths
    project_root: Path = _PROJECT_ROOT
    models_dir: Path = _PROJECT_ROOT / "backend" / "models"
    frontend_dist_dir: Path = _PROJECT_ROOT / "frontend" / "dist"

    if _HAS_PYDANTIC_SETTINGS and SettingsConfigDict is not None:
        model_config = SettingsConfigDict(
            env_file=str(_PROJECT_ROOT / ".env"),
            env_file_encoding="utf-8",
            extra="ignore",
        )

    def ensure_directories(self) -> None:
        """Tạo thư mục lưu model weights nếu chưa tồn tại."""
        self.models_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Trả về singleton Settings cho toàn ứng dụng."""
    settings = Settings()
    settings.ensure_directories()
    return settings
