from __future__ import annotations

import os
import platform
import sys
from functools import lru_cache
from typing import Any

import psutil


def _read_windows_cpu_name() -> str | None:
    """Đọc tên CPU trực tiếp từ Windows Registry không cần mở tiến trình phụ."""
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\Description\System\CentralProcessor\0",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            cleaned = str(value).strip()
            return cleaned or None
    except Exception:
        return None


def _detect_cpu_name(ov_core: Any = None, ov_devices: list[str] | None = None) -> str:
    """Xác định tên CPU dễ đọc theo thứ tự ưu tiên Windows Registry -> OpenVINO -> platform."""
    reg_name = _read_windows_cpu_name()
    if reg_name:
        return reg_name

    if ov_core is not None and ov_devices:
        for dev in ov_devices:
            if str(dev).upper() == "CPU":
                try:
                    full_name = str(ov_core.get_property(dev, "FULL_DEVICE_NAME")).strip()
                    if full_name:
                        return full_name
                except Exception:
                    pass

    proc = platform.processor().strip()
    if proc:
        return proc

    env_cpu = os.getenv("PROCESSOR_IDENTIFIER", "").strip()
    return env_cpu or "Unknown CPU"


def _classify_gpu_type(full_name: str) -> str:
    """Phân loại GPU rời (dgpu) hay GPU tích hợp Intel Arc/Graphics (igpu)."""
    low = full_name.lower()
    if any(token in low for token in ("nvidia", "geforce", "rtx", "quadro", "radeon rx", "radeon pro")):
        return "dgpu"
    return "igpu"


@lru_cache(maxsize=1)
def _probe_static_hardware() -> dict[str, Any]:
    """Quét một lần danh sách CPU/GPU/NPU và runtime khả dụng (cache để GET /hardware nhanh)."""
    devices: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    ov_core = None
    ov_devices: list[str] = []

    def _append_device(dev_id: str, name: str, dev_type: str, available: bool = True) -> None:
        if dev_id in seen_ids:
            return
        seen_ids.add(dev_id)
        devices.append(
            {
                "id": dev_id,
                "name": name,
                "type": dev_type,
                "available": available,
            }
        )

    try:
        import openvino as ov  # type: ignore[import-untyped]

        ov_core = ov.Core()
        ov_devices = [str(d) for d in ov_core.available_devices]
        for raw_dev in ov_devices:
            dev_upper = raw_dev.upper()
            try:
                full_name = str(ov_core.get_property(raw_dev, "FULL_DEVICE_NAME")).strip()
            except Exception:
                full_name = dev_upper

            if dev_upper.startswith("GPU"):
                dev_id = "openvino:GPU" if dev_upper in ("GPU", "GPU.0") else f"openvino:{dev_upper}"
                _append_device(
                    dev_id=dev_id,
                    name=f"{full_name} (OpenVINO)",
                    dev_type=_classify_gpu_type(full_name),
                )
            elif dev_upper == "NPU":
                # Hiển thị Intel AI Boost NPU để user nắm trạng thái, không chọn cho Florence-2/LaMa
                _append_device(
                    dev_id="openvino:NPU",
                    name=f"{full_name} (OpenVINO)",
                    dev_type="npu",
                )
            elif dev_upper == "CPU":
                _append_device(
                    dev_id="openvino:CPU",
                    name=f"{full_name} (OpenVINO)",
                    dev_type="cpu",
                )
    except Exception:
        pass

    try:
        import torch  # type: ignore[import-untyped]

        if torch.cuda.is_available():
            try:
                cuda_name = str(torch.cuda.get_device_name(0)).strip()
            except Exception:
                cuda_name = "NVIDIA CUDA GPU"
            _append_device(
                dev_id="pytorch:cuda",
                name=f"{cuda_name} (CUDA)",
                dev_type="dgpu",
            )
        _append_device(
            dev_id="pytorch:cpu",
            name="PyTorch CPU",
            dev_type="cpu",
        )
    except Exception:
        pass

    try:
        import onnxruntime as ort  # type: ignore[import-untyped]

        providers = {str(p) for p in ort.get_available_providers()}
        if "DmlExecutionProvider" in providers:
            _append_device(
                dev_id="onnx:dml",
                name="DirectML GPU (ONNX Runtime)",
                dev_type="gpu",
            )
    except Exception:
        pass

    cpu_name = _detect_cpu_name(ov_core=ov_core, ov_devices=ov_devices)
    if not devices:
        _append_device(dev_id="cpu", name=cpu_name, dev_type="cpu")

    available_ids = [d["id"] for d in devices if d.get("available")]
    recommended_backend = "cpu"
    for preferred in (
        "pytorch:cuda",
        "openvino:GPU",
        "onnx:dml",
        "openvino:CPU",
        "pytorch:cpu",
        "cpu",
    ):
        if preferred in available_ids:
            recommended_backend = preferred
            break
    else:
        if available_ids:
            recommended_backend = available_ids[0]

    return {
        "cpu": cpu_name,
        "devices": devices,
        "recommended_backend": recommended_backend,
    }


def clear_hardware_probe_cache() -> None:
    """Xóa cache thiết bị tĩnh để quét lại phần cứng khi cần."""
    _probe_static_hardware.cache_clear()


def probe_hardware(refresh: bool = False) -> dict[str, Any]:
    """Trả về thông tin phần cứng tĩnh (cached) kết hợp dung lượng RAM trống thời gian thực."""
    if refresh:
        clear_hardware_probe_cache()

    static_info = _probe_static_hardware()
    try:
        vm = psutil.virtual_memory()
        total_ram_mb = int(round(vm.total / (1024 * 1024)))
        available_ram_mb = int(round(vm.available / (1024 * 1024)))
    except Exception:
        total_ram_mb = 0
        available_ram_mb = 0

    return {
        "cpu": static_info["cpu"],
        "devices": [dict(d) for d in static_info["devices"]],
        "recommended_backend": static_info["recommended_backend"],
        "total_ram_mb": total_ram_mb,
        "available_ram_mb": available_ram_mb,
    }
