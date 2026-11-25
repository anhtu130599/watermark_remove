from __future__ import annotations

import gc
import sys
import threading
import time
from abc import ABC, abstractmethod
from typing import Any


class EngineError(Exception):
    """Lỗi vận hành AI Engine khớp chuẩn mã lỗi HTTP API Contract."""

    def __init__(self, message: str, status_code: int = 500, code: str = "INTERNAL_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


def normalize_requested_backend(backend: str | None) -> str:
    """Chuẩn hóa tên backend người dùng truyền vào về định dạng thống nhất."""
    if backend is None:
        return "auto"
    raw = backend.strip()
    if not raw:
        return "auto"

    low = raw.lower()
    alias_map = {
        "auto": "auto",
        "openvino": "openvino:AUTO",
        "openvino:auto": "openvino:AUTO",
        "openvino:gpu": "openvino:GPU",
        "openvino:cpu": "openvino:CPU",
        "openvino:npu": "openvino:NPU",
        "gpu": "openvino:GPU",
        "igpu": "openvino:GPU",
        "cuda": "pytorch:cuda",
        "pytorch:cuda": "pytorch:cuda",
        "pytorch:cpu": "pytorch:cpu",
        "dml": "onnx:dml",
        "directml": "onnx:dml",
        "onnx:dml": "onnx:dml",
        "onnx:cpu": "onnx:cpu",
        "cpu": "cpu",
    }
    if low in alias_map:
        return alias_map[low]

    if low.startswith("openvino:"):
        device = raw.split(":", 1)[1].strip().upper()
        return f"openvino:{device}"
    if low.startswith("pytorch:"):
        device = raw.split(":", 1)[1].strip().lower()
        return f"pytorch:{device}"
    if low.startswith("onnx:"):
        device = raw.split(":", 1)[1].strip().lower()
        return f"onnx:{device}"
    return raw


def probe_available_runtimes() -> dict[str, Any]:
    """Kiểm tra an toàn các AI runtime hiện có trên máy (OpenVINO, PyTorch, ONNX Runtime)."""
    info: dict[str, Any] = {
        "openvino_available": False,
        "openvino_devices": [],
        "torch_available": False,
        "cuda_available": False,
        "ort_available": False,
        "ort_providers": [],
    }

    try:
        import openvino as ov  # type: ignore[import-untyped]

        core = ov.Core()
        info["openvino_available"] = True
        info["openvino_devices"] = [str(d).upper() for d in core.available_devices]
    except Exception:
        pass

    try:
        import torch  # type: ignore[import-untyped]

        info["torch_available"] = True
        info["cuda_available"] = bool(torch.cuda.is_available())
    except Exception:
        pass

    try:
        import onnxruntime as ort  # type: ignore[import-untyped]

        info["ort_available"] = True
        info["ort_providers"] = [str(p) for p in ort.get_available_providers()]
    except Exception:
        pass

    return info


def _is_backend_available(candidate: str, runtime_info: dict[str, Any], allow_npu: bool) -> bool:
    """Kiểm tra runtime của một backend ứng viên có khả dụng hay không."""
    ov_devices = {str(d).upper() for d in runtime_info.get("openvino_devices", [])}
    ov_ok = bool(runtime_info.get("openvino_available"))
    torch_ok = bool(runtime_info.get("torch_available"))
    cuda_ok = bool(runtime_info.get("cuda_available"))
    ort_ok = bool(runtime_info.get("ort_available"))
    ort_providers = set(runtime_info.get("ort_providers", []))

    if candidate == "openvino:GPU":
        return ov_ok and any(d.startswith("GPU") for d in ov_devices)
    if candidate == "openvino:CPU":
        return ov_ok and ("CPU" in ov_devices or not ov_devices)
    if candidate == "openvino:NPU":
        return allow_npu and ov_ok and ("NPU" in ov_devices)
    if candidate == "openvino:AUTO":
        if not ov_ok:
            return False
        if not allow_npu:
            return any(d.startswith("GPU") or d == "CPU" for d in ov_devices) or not ov_devices
        return True
    if candidate == "pytorch:cuda":
        return torch_ok and cuda_ok
    if candidate == "pytorch:cpu":
        return torch_ok
    if candidate == "onnx:dml":
        return ort_ok and ("DmlExecutionProvider" in ort_providers)
    if candidate == "onnx:cpu":
        return ort_ok
    return False


def resolve_backend_candidates(
    requested: str = "auto",
    runtime_info: dict[str, Any] | None = None,
    allow_npu: bool = False,
) -> list[str]:
    """Xây dựng chuỗi backend ưu tiên và fallback an toàn theo cấu hình phần cứng."""
    info = runtime_info if runtime_info is not None else probe_available_runtimes()
    norm = normalize_requested_backend(requested)

    ordered: list[str] = []

    def _add(item: str) -> None:
        if item not in ordered and _is_backend_available(item, info, allow_npu=allow_npu):
            ordered.append(item)

    if norm == "auto":
        for item in (
            "openvino:GPU",
            "openvino:CPU",
            "pytorch:cuda",
            "onnx:dml",
            "pytorch:cpu",
            "onnx:cpu",
        ):
            _add(item)
        return ordered

    if norm == "cpu":
        for item in ("openvino:CPU", "pytorch:cpu", "onnx:cpu"):
            _add(item)
        return ordered

    if norm == "openvino:AUTO":
        # Với allow_npu=False, tránh ép lớp FFT/Dynamic shape lên NPU bằng cách ưu tiên GPU -> CPU
        for item in (
            "openvino:GPU",
            "openvino:CPU",
            "pytorch:cuda",
            "onnx:dml",
            "pytorch:cpu",
            "onnx:cpu",
        ):
            _add(item)
        return ordered

    _add(norm)
    for fallback in ("openvino:CPU", "pytorch:cuda", "onnx:dml", "pytorch:cpu", "onnx:cpu"):
        _add(fallback)
    return ordered


class IAiEngine(ABC):
    """Contract trừu tượng chuẩn cho toàn bộ AI Engines (LaMa, Florence-2)."""

    def __init__(self, name: str, estimated_ram_mb: int = 512) -> None:
        self.name: str = name
        self.estimated_ram_mb: int = estimated_ram_mb
        self._lock = threading.RLock()
        self._is_loaded: bool = False
        self._backend_used: str = "unloaded"
        self._last_used_at: float = 0.0

    @property
    def is_loaded(self) -> bool:
        """Trả về True nếu trọng số AI đã sẵn sàng trong bộ nhớ."""
        return self._is_loaded

    @property
    def backend_used(self) -> str:
        """Tên backend đang chạy thực tế (ví dụ: openvino:GPU, pytorch:cpu)."""
        return self._backend_used

    @property
    def last_used_at(self) -> float:
        """Mốc thời gian monotonic lần sử dụng gần nhất (phục vụ Auto-unload)."""
        return self._last_used_at

    def touch(self) -> None:
        """Cập nhật dấu thời gian sử dụng gần nhất."""
        self._last_used_at = time.monotonic()

    @abstractmethod
    def load(self, backend: str = "auto") -> None:
        """Nạp model lên backend được chọn (thread-safe)."""

    @abstractmethod
    def _release_resources(self) -> None:
        """Hook giải phóng tham chiếu model cụ thể của lớp con."""

    def unload(self) -> None:
        """Giải phóng hoàn toàn model khỏi RAM/VRAM."""
        with self._lock:
            self._release_resources()
            self._is_loaded = False
            self._backend_used = "unloaded"
            gc.collect()
            torch_mod = sys.modules.get("torch")
            if torch_mod is not None:
                try:
                    if torch_mod.cuda.is_available():
                        torch_mod.cuda.empty_cache()
                except Exception:
                    pass

    @abstractmethod
    def predict(self, *args: Any, **kwargs: Any) -> Any:
        """Chạy suy luận chính của engine."""
