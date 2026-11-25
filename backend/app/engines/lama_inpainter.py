from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

import numpy as np

try:
    import cv2

    _HAS_CV2 = True
except ImportError:
    cv2 = None  # type: ignore[assignment]
    _HAS_CV2 = False

from backend.app.config import get_settings
from backend.app.engines.base import (
    EngineError,
    IAiEngine,
    normalize_requested_backend,
    resolve_backend_candidates,
)

logger = logging.getLogger(__name__)


def pad_to_modulo(arr: np.ndarray, mod: int = 8, mode: str = "symmetric") -> np.ndarray:
    """Đệm cạnh phải/dưới sao cho chiều cao và rộng chia hết cho `mod`."""
    if mod < 1:
        raise ValueError("Tham số mod phải >= 1.")
    if arr.ndim not in (2, 3):
        raise ValueError(f"Chỉ hỗ trợ mảng 2D hoặc 3D, nhận được ndim={arr.ndim}.")

    h, w = arr.shape[:2]
    pad_h = (mod - (h % mod)) % mod
    pad_w = (mod - (w % mod)) % mod
    if pad_h == 0 and pad_w == 0:
        return np.ascontiguousarray(arr)

    if arr.ndim == 2:
        pad_width = ((0, pad_h), (0, pad_w))
    else:
        pad_width = ((0, pad_h), (0, pad_w), (0, 0))

    padded = np.pad(arr, pad_width=pad_width, mode=mode)
    return np.ascontiguousarray(padded)


def crop_to_shape(arr: np.ndarray, height: int, width: int) -> np.ndarray:
    """Cắt mảng kết quả về đúng kích thước `(height, width)` ban đầu sau inference."""
    if height <= 0 or width <= 0:
        raise ValueError("Kích thước cắt phải > 0.")
    if arr.shape[0] < height or arr.shape[1] < width:
        raise ValueError(
            f"Mảng ({arr.shape[0]}x{arr.shape[1]}) nhỏ hơn kích thước đích ({height}x{width})."
        )
    if arr.ndim == 2:
        return np.ascontiguousarray(arr[:height, :width])
    return np.ascontiguousarray(arr[:height, :width, :])


def prepare_lama_inputs(
    rgb_uint8: np.ndarray, mask_uint8: np.ndarray, mod: int = 8
) -> tuple[np.ndarray, np.ndarray, tuple[int, int]]:
    """Chuẩn hóa và pad cặp RGB `(H,W,3)` + Mask `(H,W)` thành tensor NCHW float32."""
    if rgb_uint8.ndim != 3 or rgb_uint8.shape[2] != 3:
        raise EngineError(
            "Ảnh đầu vào cho LaMa phải có shape (H, W, 3).",
            status_code=400,
            code="BAD_REQUEST",
        )
    if mask_uint8.ndim != 2 or mask_uint8.shape[:2] != rgb_uint8.shape[:2]:
        raise EngineError(
            "Mask đầu vào cho LaMa phải là mảng 2D (H, W) khớp kích thước ảnh.",
            status_code=400,
            code="BAD_REQUEST",
        )

    orig_h, orig_w = rgb_uint8.shape[:2]
    binary_mask = ((mask_uint8 > 127).astype(np.uint8) * 255)

    rgb_pad = pad_to_modulo(rgb_uint8, mod=mod, mode="symmetric")
    mask_pad = pad_to_modulo(binary_mask, mod=mod, mode="symmetric")

    img_nchw = (rgb_pad.astype(np.float32) / 255.0).transpose(2, 0, 1)[None, ...]
    mask_nchw = (mask_pad > 127).astype(np.float32)[None, None, ...]
    return np.ascontiguousarray(img_nchw), np.ascontiguousarray(mask_nchw), (orig_h, orig_w)


def postprocess_lama_output(
    raw_output: np.ndarray, orig_hw: tuple[int, int]
) -> np.ndarray:
    """Chuyển tensor output `(1,3,H_pad,W_pad)` hoặc `(3,H_pad,W_pad)` về RGB uint8 đúng `(H,W)`."""
    arr = np.asarray(raw_output)
    if arr.ndim == 4:
        arr = arr[0]
    if arr.ndim != 3 or arr.shape[0] != 3:
        raise EngineError(
            f"Output tensor từ LaMa có shape không hợp lệ: {raw_output.shape}.",
            status_code=500,
            code="INTERNAL_ERROR",
        )

    chw = arr.astype(np.float32, copy=False)
    if chw.size == 0 or not np.isfinite(chw).all():
        raise EngineError(
            "Output tensor từ LaMa chứa NaN/Inf (tràn số dấu phẩy động trên thiết bị suy luận).",
            status_code=500,
            code="INTERNAL_ERROR",
        )

    max_val = float(np.max(chw))
    scale = 1.0 if max_val > 1.5 else 255.0

    hwc = np.clip(chw * scale, 0.0, 255.0).round().astype(np.uint8).transpose(1, 2, 0)
    orig_h, orig_w = orig_hw
    return crop_to_shape(hwc, orig_h, orig_w)


def _merge_boxes(boxes: list[tuple[int, int, int, int]], gap: int = 0) -> list[tuple[int, int, int, int]]:
    """Gộp các bounding box `(x1, y1, x2, y2)` giao nhau hoặc cách nhau <= `gap` pixel."""
    if not boxes:
        return []
    merged = [tuple(b) for b in boxes]
    changed = True
    while changed:
        changed = False
        next_boxes: list[tuple[int, int, int, int]] = []
        used = [False] * len(merged)
        for i in range(len(merged)):
            if used[i]:
                continue
            ax1, ay1, ax2, ay2 = merged[i]
            used[i] = True
            for j in range(i + 1, len(merged)):
                if used[j]:
                    continue
                bx1, by1, bx2, by2 = merged[j]
                if (
                    ax1 - gap <= bx2
                    and bx1 - gap <= ax2
                    and ay1 - gap <= by2
                    and by1 - gap <= ay2
                ):
                    ax1 = min(ax1, bx1)
                    ay1 = min(ay1, by1)
                    ax2 = max(ax2, bx2)
                    ay2 = max(ay2, by2)
                    used[j] = True
                    changed = True
            next_boxes.append((ax1, ay1, ax2, ay2))
        merged = next_boxes
    return merged


def compute_context_rois(
    mask_uint8: np.ndarray,
    min_crop: int = 256,
    merge_gap: int = 96,
) -> list[tuple[int, int, int, int]]:
    """Tính các vùng ROI ngữ cảnh đủ rộng quanh mask (có corner-shift) để giữ chi tiết LaMa."""
    h, w = mask_uint8.shape[:2]
    binary = (mask_uint8 > 127).astype(np.uint8)
    if not np.any(binary):
        return []
    if min(h, w) < 192:
        return [(0, 0, w, h)]

    raw_boxes: list[tuple[int, int, int, int]] = []
    if _HAS_CV2 and cv2 is not None:
        num_labels, _labels, stats, _centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
        for label_idx in range(1, num_labels):
            x = int(stats[label_idx, cv2.CC_STAT_LEFT])
            y = int(stats[label_idx, cv2.CC_STAT_TOP])
            bw = int(stats[label_idx, cv2.CC_STAT_WIDTH])
            bh = int(stats[label_idx, cv2.CC_STAT_HEIGHT])
            if bw > 0 and bh > 0:
                raw_boxes.append((x, y, x + bw, y + bh))
    else:
        ys, xs = np.where(binary > 0)
        raw_boxes.append((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))

    if not raw_boxes:
        return []

    clustered = _merge_boxes(raw_boxes, gap=merge_gap)
    expanded: list[tuple[int, int, int, int]] = []
    for x1, y1, x2, y2 in clustered:
        bw = x2 - x1
        bh = y2 - y1
        margin = max(80, int(max(bw, bh) * 1.15))
        target_w = min(w, max(min_crop, bw + 2 * margin))
        target_h = min(h, max(min_crop, bh + 2 * margin))

        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        rx1 = int(round(cx - target_w / 2.0))
        ry1 = int(round(cy - target_h / 2.0))
        rx2 = rx1 + target_w
        ry2 = ry1 + target_h

        # Dịch cửa sổ khỏi mép ảnh (corner-shift) để watermark ở góc vẫn đủ ngữ cảnh xung quanh
        if rx2 > w:
            rx1 -= rx2 - w
            rx2 = w
        if rx1 < 0:
            rx2 = min(w, rx2 - rx1)
            rx1 = 0
        if ry2 > h:
            ry1 -= ry2 - h
            ry2 = h
        if ry1 < 0:
            ry2 = min(h, ry2 - ry1)
            ry1 = 0

        expanded.append((max(0, rx1), max(0, ry1), min(w, rx2), min(h, ry2)))

    rois = _merge_boxes(expanded, gap=16)
    total_area = sum((rx2 - rx1) * (ry2 - ry1) for rx1, ry1, rx2, ry2 in rois)
    if total_area > 0.65 * float(h * w):
        return [(0, 0, w, h)]
    return rois


class LamaInpainter(IAiEngine):
    """AI Engine xóa watermark bằng Big-LaMa (OpenVINO / PyTorch / ONNX Runtime fallback)."""

    def __init__(
        self,
        models_dir: Path | None = None,
        quantization_policy: str | None = None,
        pad_modulo: int = 8,
        runner_override: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None,
    ) -> None:
        super().__init__(name="lama", estimated_ram_mb=950)
        settings = get_settings()
        self.models_dir = Path(models_dir) if models_dir is not None else settings.models_dir
        self.quantization_policy = (
            quantization_policy if quantization_policy is not None else settings.quantization_policy
        ).lower()
        self.pad_modulo = pad_modulo
        self._runner_override = runner_override

        self.pt_path = self.models_dir / "big-lama.pt"
        self.ov_xml_path = self.models_dir / "openvino" / "big-lama-fp32.xml"
        self._legacy_ov_xml_path = self.models_dir / "openvino" / "big-lama.xml"
        self.onnx_path = self.models_dir / "onnx" / "lama.onnx"

        self._model_handle: Any = None
        self._runner: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None

    def _has_any_artifact(self) -> bool:
        return self.pt_path.exists() or self.ov_xml_path.exists() or self.onnx_path.exists()

    def _release_resources(self) -> None:
        self._runner = None
        self._model_handle = None

    def _load_openvino(self, device: str) -> tuple[Any, Callable[[np.ndarray, np.ndarray], np.ndarray]]:
        import openvino as ov  # type: ignore[import-untyped]

        core = ov.Core()
        ov_model = None
        converted_now = False

        if self.ov_xml_path.exists():
            ov_model = core.read_model(str(self.ov_xml_path))
        elif self.onnx_path.exists():
            ov_model = core.read_model(str(self.onnx_path))
        elif self.pt_path.exists():
            import torch  # type: ignore[import-untyped]

            ts_model = torch.jit.load(str(self.pt_path), map_location="cpu")
            ts_model.eval()
            ex_img = torch.zeros(1, 3, 256, 256, dtype=torch.float32)
            ex_mask = torch.zeros(1, 1, 256, 256, dtype=torch.float32)
            ov_model = ov.convert_model(
                ts_model,
                example_input=(ex_img, ex_mask),
                input=[(1, 3, -1, -1), (1, 1, -1, -1)],
            )
            converted_now = True
        else:
            raise FileNotFoundError("Không có tệp IR/ONNX/TorchScript cho OpenVINO.")

        ov_device = "AUTO:GPU,CPU" if device == "AUTO" else device
        # Tầng 2D FFT (rfft2/irfft2) của LaMa vượt ngưỡng FP16 (65504) -> NaN (đen ảnh) trên iGPU; bắt buộc FP32.
        ov_config: dict[str, str] = {"INFERENCE_PRECISION_HINT": "f32"}

        compiled = core.compile_model(ov_model, ov_device, ov_config)
        output_port = compiled.output(0)

        # Kiểm chứng khả năng chạy đa kích thước động và tính hữu hạn (không NaN/Inf) trên dữ liệu khác 0
        for test_h, test_w in ((64, 64), (64, 80)):
            probe_img = np.full((1, 3, test_h, test_w), 0.5, dtype=np.float32)
            probe_mask = np.zeros((1, 1, test_h, test_w), dtype=np.float32)
            probe_mask[:, :, 16:48, 16:48] = 1.0
            probe_res = np.asarray(compiled([probe_img, probe_mask])[output_port])
            if probe_res.size == 0 or not np.isfinite(probe_res).all():
                raise RuntimeError(
                    f"OpenVINO LaMa ({ov_device}) sinh NaN/Inf trong bài test độ chính xác động."
                )

        if converted_now:
            self.ov_xml_path.parent.mkdir(parents=True, exist_ok=True)
            ov.save_model(
                ov_model,
                str(self.ov_xml_path),
                compress_to_fp16=False,
            )
            for legacy_path in (
                self._legacy_ov_xml_path,
                self._legacy_ov_xml_path.with_suffix(".bin"),
            ):
                if legacy_path.exists():
                    legacy_path.unlink(missing_ok=True)

        def _run(img_nchw: np.ndarray, mask_nchw: np.ndarray) -> np.ndarray:
            result = compiled([img_nchw, mask_nchw])
            return np.asarray(result[output_port])

        return compiled, _run

    def _load_onnx(self, backend_id: str) -> tuple[Any, Callable[[np.ndarray, np.ndarray], np.ndarray]]:
        if not self.onnx_path.exists():
            raise FileNotFoundError(f"Không tìm thấy ONNX model tại {self.onnx_path}.")
        import onnxruntime as ort  # type: ignore[import-untyped]

        providers = (
            ["DmlExecutionProvider", "CPUExecutionProvider"]
            if backend_id == "onnx:dml"
            else ["CPUExecutionProvider"]
        )
        session = ort.InferenceSession(str(self.onnx_path), providers=providers)
        input_names = [inp.name for inp in session.get_inputs()]
        if len(input_names) < 2:
            raise RuntimeError(f"ONNX LaMa thiếu đủ 2 inputs (image, mask): {input_names}")

        def _run(img_nchw: np.ndarray, mask_nchw: np.ndarray) -> np.ndarray:
            outputs = session.run(
                None,
                {input_names[0]: img_nchw, input_names[1]: mask_nchw},
            )
            return np.asarray(outputs[0])

        return session, _run

    def _load_pytorch(self, device_name: str) -> tuple[Any, Callable[[np.ndarray, np.ndarray], np.ndarray]]:
        if not self.pt_path.exists():
            raise FileNotFoundError(f"Không tìm thấy TorchScript weights tại {self.pt_path}.")
        import torch  # type: ignore[import-untyped]

        device = torch.device(device_name)
        model = torch.jit.load(str(self.pt_path), map_location=device)
        model.eval()

        def _run(img_nchw: np.ndarray, mask_nchw: np.ndarray) -> np.ndarray:
            with torch.inference_mode():
                img_t = torch.from_numpy(img_nchw).to(device)
                mask_t = torch.from_numpy(mask_nchw).to(device)
                out = model(img_t, mask_t)
                if isinstance(out, (tuple, list)):
                    out = out[0]
                return out.detach().cpu().numpy()

        return model, _run

    def load(self, backend: str = "auto") -> None:
        """Nạp LaMa theo chuỗi ưu tiên phần cứng và tự fallback nếu runtime không hỗ trợ."""
        with self._lock:
            if self._runner_override is not None:
                self._runner = self._runner_override
                self._model_handle = "mock"
                self._is_loaded = True
                self._backend_used = "mock"
                self.touch()
                return

            if not self._has_any_artifact():
                raise EngineError(
                    "Không tìm thấy trọng số LaMa (big-lama.pt). Hãy chạy scripts/download_models.py trước.",
                    status_code=503,
                    code="MODEL_UNAVAILABLE",
                )

            norm_requested = normalize_requested_backend(backend)
            if self._is_loaded and (
                norm_requested == "auto" or norm_requested == self._backend_used
            ):
                self.touch()
                return

            candidates = resolve_backend_candidates(norm_requested, allow_npu=False)
            if norm_requested in ("auto", "openvino:AUTO"):
                # Khi FP32 được bật cho FFT của LaMa, OneDNN trên CPU (Core Ultra) nhanh hơn OpenCL iGPU ~4-5 lần
                priority = [
                    "pytorch:cuda",
                    "openvino:CPU",
                    "pytorch:cpu",
                    "openvino:GPU",
                    "onnx:dml",
                    "onnx:cpu",
                ]
                candidates = sorted(
                    candidates,
                    key=lambda c: priority.index(c) if c in priority else len(priority),
                )
            if not candidates:
                raise EngineError(
                    "Chưa có AI runtime khả dụng (cần PyTorch, OpenVINO hoặc ONNX Runtime).",
                    status_code=503,
                    code="MODEL_UNAVAILABLE",
                )

            errors: list[str] = []
            for candidate in candidates:
                try:
                    self._release_resources()
                    if candidate.startswith("openvino:"):
                        ov_device = candidate.split(":", 1)[1]
                        handle, runner = self._load_openvino(ov_device)
                    elif candidate.startswith("onnx:"):
                        handle, runner = self._load_onnx(candidate)
                    elif candidate.startswith("pytorch:"):
                        pt_device = candidate.split(":", 1)[1]
                        handle, runner = self._load_pytorch(pt_device)
                    else:
                        raise RuntimeError(f"Backend không được hỗ trợ: {candidate}")

                    self._model_handle = handle
                    self._runner = runner
                    self._is_loaded = True
                    self._backend_used = candidate
                    self.touch()
                    return
                except Exception as exc:
                    logger.warning("LaMa không nạp được trên %s: %s", candidate, exc)
                    errors.append(f"{candidate}: {exc}")

            self._is_loaded = False
            self._backend_used = "unloaded"
            raise EngineError(
                f"Không thể khởi tạo LaMa trên bất kỳ backend nào ({'; '.join(errors)}).",
                status_code=503,
                code="MODEL_UNAVAILABLE",
            )

    def _run_crop_inference(
        self,
        rgb_crop: np.ndarray,
        mask_crop: np.ndarray,
        norm_req: str,
    ) -> np.ndarray:
        """Chạy LaMa trên một ROI cụ thể kèm fallback CPU nếu runtime lỗi hoặc sinh NaN."""
        if self._runner is None:
            raise EngineError(
                "LaMa runner chưa sẵn sàng.",
                status_code=503,
                code="MODEL_UNAVAILABLE",
            )

        img_nchw, mask_nchw, orig_hw = prepare_lama_inputs(
            rgb_crop, mask_crop, mod=self.pad_modulo
        )
        try:
            raw_out = self._runner(img_nchw, mask_nchw)
            return postprocess_lama_output(raw_out, orig_hw)
        except Exception as exc:
            if self._runner_override is None and self._backend_used != "pytorch:cpu":
                logger.warning(
                    "LaMa runtime/NaN error trên %s (%s); tự chuyển sang pytorch:cpu.",
                    self._backend_used,
                    exc,
                )
                self.load(backend="pytorch:cpu")
                raw_out = self._runner(img_nchw, mask_nchw)
                return postprocess_lama_output(raw_out, orig_hw)
            raise

    def _inpaint_roi_with_supersample(
        self,
        rgb_crop: np.ndarray,
        mask_crop: np.ndarray,
        norm_req: str,
    ) -> np.ndarray:
        """Khóng đại Lanczos4 lên 512px cho ROI nhỏ để giữ nét vẽ sắc, sau đó thu về kích thước gốc."""
        ch, cw = rgb_crop.shape[:2]
        if (
            self._runner_override is None
            and _HAS_CV2
            and cv2 is not None
            and max(ch, cw) < 512
        ):
            scale = min(2.5, 512.0 / float(max(1, max(ch, cw))))
            if scale > 1.15:
                up_w = max(8, int(round(cw * scale / 8.0)) * 8)
                up_h = max(8, int(round(ch * scale / 8.0)) * 8)
                up_rgb = cv2.resize(rgb_crop, (up_w, up_h), interpolation=cv2.INTER_LANCZOS4)
                up_mask_raw = cv2.resize(mask_crop, (up_w, up_h), interpolation=cv2.INTER_LINEAR)
                up_mask = ((up_mask_raw > 127).astype(np.uint8) * 255)
                up_pred = self._run_crop_inference(up_rgb, up_mask, norm_req=norm_req)
                return cv2.resize(up_pred, (cw, ch), interpolation=cv2.INTER_LANCZOS4)

        return self._run_crop_inference(rgb_crop, mask_crop, norm_req=norm_req)

    def inpaint(
        self,
        rgb_uint8: np.ndarray,
        mask_uint8: np.ndarray,
        backend: str | None = None,
    ) -> np.ndarray:
        """Xóa vùng watermark theo mask nhị phân, giữ nguyên 100% pixel ngoài mask."""
        if rgb_uint8.ndim != 3 or rgb_uint8.shape[2] != 3:
            raise EngineError(
                "Ảnh đầu vào cho LaMa phải có shape (H, W, 3).",
                status_code=400,
                code="BAD_REQUEST",
            )
        if mask_uint8.ndim != 2 or mask_uint8.shape[:2] != rgb_uint8.shape[:2]:
            raise EngineError(
                "Mask đầu vào cho LaMa phải là mảng 2D (H, W) khớp kích thước ảnh.",
                status_code=400,
                code="BAD_REQUEST",
            )

        mask_bool = mask_uint8 > 127
        if not np.any(mask_bool):
            return np.ascontiguousarray(rgb_uint8.copy())

        with self._lock:
            norm_req = normalize_requested_backend(backend)
            need_reload = not self._is_loaded or (
                norm_req != "auto"
                and self._runner_override is None
                and norm_req != self._backend_used
            )
            if need_reload:
                self.load(backend=norm_req)

            if self._runner_override is not None:
                inpainted_rgb = self._run_crop_inference(rgb_uint8, mask_uint8, norm_req=norm_req)
            else:
                inpainted_rgb = rgb_uint8.copy()
                for x1, y1, x2, y2 in compute_context_rois(mask_uint8):
                    roi_rgb = rgb_uint8[y1:y2, x1:x2]
                    roi_mask = mask_uint8[y1:y2, x1:x2]
                    roi_mask_bool = roi_mask > 127
                    if not np.any(roi_mask_bool):
                        continue
                    roi_pred = self._inpaint_roi_with_supersample(
                        roi_rgb, roi_mask, norm_req=norm_req
                    )
                    dst_slice = inpainted_rgb[y1:y2, x1:x2]
                    dst_slice[roi_mask_bool] = roi_pred[roi_mask_bool]

            composited = np.where(mask_bool[:, :, None], inpainted_rgb, rgb_uint8).astype(
                np.uint8, copy=False
            )
            self.touch()
            return np.ascontiguousarray(composited)

    def predict(
        self,
        rgb_uint8: np.ndarray,
        mask_uint8: np.ndarray,
        backend: str | None = None,
    ) -> np.ndarray:
        """Thực thi contract `IAiEngine.predict` cho tác vụ LaMa inpainting."""
        return self.inpaint(rgb_uint8=rgb_uint8, mask_uint8=mask_uint8, backend=backend)
