from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import math
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence
from unittest.mock import patch

import numpy as np

from backend.app.config import get_settings
from backend.app.engines.base import (
    EngineError,
    IAiEngine,
    normalize_requested_backend,
    resolve_backend_candidates,
)

FLORENCE_TASK_TOKEN = "<OPEN_VOCABULARY_DETECTION>"


@contextmanager
def _without_flash_attn_requirement() -> Iterator[None]:
    """Lọc bỏ kiểm tra bắt buộc `flash_attn` trong remote code Florence-2 trên Windows/iGPU."""
    if importlib.util.find_spec("flash_attn") is not None:
        yield
        return

    from transformers import dynamic_module_utils  # type: ignore[import-untyped]

    orig_get_imports = dynamic_module_utils.get_imports

    def _filtered_get_imports(filename: Any) -> list[str]:
        imports = list(orig_get_imports(filename))
        return [imp for imp in imports if imp != "flash_attn"]

    with patch.object(dynamic_module_utils, "get_imports", side_effect=_filtered_get_imports):
        yield


def build_florence_prompt(
    prompt: str | None,
    default_prompt: str = "watermark, logo, text, stamp, caption",
) -> tuple[str, str]:
    """Chuẩn hóa câu lệnh tìm kiếm và ghép task token `<OPEN_VOCABULARY_DETECTION>`."""
    raw = (prompt or "").strip()
    if raw.startswith(FLORENCE_TASK_TOKEN):
        raw = raw[len(FLORENCE_TASK_TOKEN) :].strip()
    clean = raw if raw else default_prompt.strip()
    return clean, f"{FLORENCE_TASK_TOKEN}{clean}"


def extract_raw_bboxes(parsed: Any, task_token: str = FLORENCE_TASK_TOKEN) -> list[list[float]]:
    """Trích xuất danh sách bounding box thô từ kết quả Florence-2 hoặc runner mock."""
    if parsed is None:
        return []
    if isinstance(parsed, (list, tuple)):
        return [[float(v) for v in box[:4]] for box in parsed if isinstance(box, (list, tuple)) and len(box) >= 4]

    if isinstance(parsed, dict):
        payload = parsed.get(task_token, parsed)
        if not isinstance(payload, dict):
            return []

        raw_boxes = payload.get("bboxes")
        if isinstance(raw_boxes, (list, tuple)) and raw_boxes:
            result: list[list[float]] = []
            for box in raw_boxes:
                if isinstance(box, (list, tuple)) and len(box) >= 4:
                    result.append([float(v) for v in box[:4]])
            if result:
                return result

        # Fallback: nếu Florence-2 trả về polygons thay vì bboxes, tính bao lồi chữ nhật
        raw_polygons = payload.get("polygons")
        if isinstance(raw_polygons, (list, tuple)):
            poly_boxes: list[list[float]] = []
            for poly_group in raw_polygons:
                # Có thể là [[x0, y0, x1, y1, ...]] hoặc [x0, y0, x1, y1, ...]
                candidates = (
                    poly_group
                    if (
                        isinstance(poly_group, (list, tuple))
                        and poly_group
                        and isinstance(poly_group[0], (list, tuple))
                    )
                    else [poly_group]
                )
                for pts in candidates:
                    if not isinstance(pts, (list, tuple)) or len(pts) < 4:
                        continue
                    xs = [float(pts[i]) for i in range(0, len(pts) - 1, 2)]
                    ys = [float(pts[i + 1]) for i in range(0, len(pts) - 1, 2)]
                    if xs and ys:
                        poly_boxes.append([min(xs), min(ys), max(xs), max(ys)])
            return poly_boxes

    return []


def sanitize_bboxes(
    raw_bboxes: Sequence[Sequence[float | int]],
    width: int,
    height: int,
    max_area_ratio: float = 0.85,
    min_side_px: int = 2,
) -> list[list[int]]:
    """Clamp tọa độ box về khung ảnh, lọc box suy biến hoặc false-positive phủ gần kín ảnh."""
    if width <= 0 or height <= 0:
        return []

    image_area = float(width * height)
    sanitized: list[list[int]] = []
    seen: set[tuple[int, int, int, int]] = set()

    for box in raw_bboxes:
        if not isinstance(box, (list, tuple, np.ndarray)) or len(box) < 4:
            continue
        coords = [float(box[0]), float(box[1]), float(box[2]), float(box[3])]
        if not all(math.isfinite(c) for c in coords):
            continue

        lo_x = min(coords[0], coords[2])
        hi_x = max(coords[0], coords[2])
        lo_y = min(coords[1], coords[3])
        hi_y = max(coords[1], coords[3])

        ix1 = max(0, min(width, int(math.floor(lo_x))))
        iy1 = max(0, min(height, int(math.floor(lo_y))))
        ix2 = max(0, min(width, int(math.ceil(hi_x))))
        iy2 = max(0, min(height, int(math.ceil(hi_y))))

        box_w = ix2 - ix1
        box_h = iy2 - iy1
        if box_w < min_side_px or box_h < min_side_px:
            continue

        if max_area_ratio > 0.0 and ((box_w * box_h) / image_area) > max_area_ratio:
            continue

        key = (ix1, iy1, ix2, iy2)
        if key not in seen:
            seen.add(key)
            sanitized.append([ix1, iy1, ix2, iy2])

    return sanitized


def bboxes_to_binary_mask(
    bboxes: Sequence[Sequence[int]],
    width: int,
    height: int,
) -> np.ndarray:
    """Chuyển danh sách `[x1, y1, x2, y2]` thành mask nhị phân `(H, W)` uint8 `{0, 255}`."""
    mask = np.zeros((height, width), dtype=np.uint8)
    for box in bboxes:
        if len(box) < 4:
            continue
        x1 = max(0, min(width, int(box[0])))
        y1 = max(0, min(height, int(box[1])))
        x2 = max(0, min(width, int(box[2])))
        y2 = max(0, min(height, int(box[3])))
        if x2 > x1 and y2 > y1:
            mask[y1:y2, x1:x2] = 255
    return mask


class FlorenceDetector(IAiEngine):
    """Engine phát hiện watermark/text tự động bằng `microsoft/Florence-2-base`."""

    def __init__(
        self,
        models_dir: Path | None = None,
        model_id: str | None = None,
        revision: str | None = None,
        quantization_policy: str | None = None,
        default_prompt: str | None = None,
        allow_hub_download: bool = False,
        runner_override: Callable[[np.ndarray, str], Sequence[Sequence[float | int]]] | None = None,
    ) -> None:
        super().__init__(name="florence2", estimated_ram_mb=1450)
        settings = get_settings()
        self.models_dir = Path(models_dir) if models_dir is not None else settings.models_dir
        self.model_id = model_id or settings.florence_model_id
        self.revision = revision or settings.florence_revision
        self.quantization_policy = (quantization_policy or settings.quantization_policy).lower()
        self.default_prompt = default_prompt or settings.default_detect_prompt
        self.allow_hub_download = allow_hub_download

        self.pytorch_dir = self.models_dir / "florence2-base"
        self.openvino_dir = self.models_dir / "openvino" / "florence2-base"

        self._runner_override = runner_override
        self._runner: Callable[[np.ndarray, str], Sequence[Sequence[float | int]]] | None = None
        self._model: Any = None
        self._processor: Any = None
        self._requested_backend: str = "auto"

    @staticmethod
    def _has_local_weights(directory: Path) -> bool:
        return directory.is_dir() and (directory / "config.json").is_file()

    def _run_hf_model(self, rgb_uint8: np.ndarray, full_prompt: str, device: str, torch_dtype: Any) -> list[list[float]]:
        import torch  # type: ignore[import-untyped]
        from PIL import Image

        height, width = rgb_uint8.shape[:2]
        pil_image = Image.fromarray(rgb_uint8, mode="RGB")
        inputs = self._processor(text=full_prompt, images=pil_image, return_tensors="pt")

        moved_inputs: dict[str, Any] = {}
        for k, v in inputs.items():
            if hasattr(v, "to"):
                if getattr(v, "is_floating_point", lambda: False)():
                    moved_inputs[k] = v.to(device=device, dtype=torch_dtype)
                else:
                    moved_inputs[k] = v.to(device=device)
            else:
                moved_inputs[k] = v

        with torch.inference_mode():
            generated_ids = self._model.generate(
                input_ids=moved_inputs["input_ids"],
                pixel_values=moved_inputs["pixel_values"],
                max_new_tokens=512,
                do_sample=False,
                num_beams=1,
                use_cache=False,
            )

        generated_text = self._processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
        parsed = self._processor.post_process_generation(
            generated_text,
            task=FLORENCE_TASK_TOKEN,
            image_size=(width, height),
        )
        return extract_raw_bboxes(parsed, task_token=FLORENCE_TASK_TOKEN)

    def _load_openvino_candidate(self, candidate: str) -> None:
        if not self._has_local_weights(self.openvino_dir):
            raise FileNotFoundError(f"Chưa có OpenVINO IR tại {self.openvino_dir}")

        import torch  # type: ignore[import-untyped]
        from optimum.intel.openvino import OVModelForCausalLM  # type: ignore[import-untyped]
        from transformers import AutoProcessor  # type: ignore[import-untyped]

        ov_device = candidate.split(":", 1)[1].upper()
        with _without_flash_attn_requirement():
            self._processor = AutoProcessor.from_pretrained(
                str(self.openvino_dir),
                trust_remote_code=True,
                local_files_only=True,
            )
            self._model = OVModelForCausalLM.from_pretrained(
                str(self.openvino_dir),
                device=ov_device,
                trust_remote_code=True,
                local_files_only=True,
            )
        self._runner = lambda img, prompt: self._run_hf_model(img, prompt, "cpu", torch.float32)

    def _load_pytorch_candidate(self, candidate: str) -> None:
        import torch  # type: ignore[import-untyped]
        from transformers import AutoModelForCausalLM, AutoProcessor  # type: ignore[import-untyped]

        has_local = self._has_local_weights(self.pytorch_dir)
        if not has_local and not self.allow_hub_download:
            raise FileNotFoundError(f"Chưa có weights Florence-2 tại {self.pytorch_dir}")

        source = str(self.pytorch_dir) if has_local else self.model_id
        local_only = has_local or not self.allow_hub_download
        device = "cuda" if candidate == "pytorch:cuda" else "cpu"
        use_fp16 = device == "cuda" and self.quantization_policy in ("fp16", "int8")
        torch_dtype = torch.float16 if use_fp16 else torch.float32

        proc_kwargs: dict[str, Any] = {
            "trust_remote_code": True,
            "local_files_only": local_only,
        }
        model_kwargs: dict[str, Any] = {
            "trust_remote_code": True,
            "local_files_only": local_only,
            "torch_dtype": torch_dtype,
            "attn_implementation": "eager",
        }
        if not has_local and self.revision:
            proc_kwargs["revision"] = self.revision
            model_kwargs["revision"] = self.revision

        with _without_flash_attn_requirement():
            self._processor = AutoProcessor.from_pretrained(source, **proc_kwargs)
            try:
                self._model = AutoModelForCausalLM.from_pretrained(source, **model_kwargs)
            except TypeError:
                # Một số phiên bản transformers cũ không nhận tham số attn_implementation
                model_kwargs.pop("attn_implementation", None)
                self._model = AutoModelForCausalLM.from_pretrained(source, **model_kwargs)

        self._model = self._model.to(device).eval()
        self._runner = lambda img, prompt: self._run_hf_model(img, prompt, device, torch_dtype)

    def load(self, backend: str = "auto") -> None:
        """Nạp Florence-2 vào RAM/GPU (thread-safe, hỗ trợ OpenVINO/PyTorch fallback)."""
        with self._lock:
            norm = normalize_requested_backend(backend)
            if self._is_loaded and self._requested_backend == norm:
                self.touch()
                return

            if self._is_loaded:
                self._release_resources()
                self._is_loaded = False
                self._backend_used = "unloaded"

            if self._runner_override is not None:
                self._runner = self._runner_override
                self._requested_backend = norm
                self._backend_used = "mock:override"
                self._is_loaded = True
                self.touch()
                return

            if (
                not self._has_local_weights(self.openvino_dir)
                and not self._has_local_weights(self.pytorch_dir)
                and not self.allow_hub_download
            ):
                raise EngineError(
                    "Chưa tìm thấy trọng số Florence-2 tại backend/models/florence2-base. Hãy chạy scripts/download_models.py.",
                    status_code=503,
                    code="MODEL_UNAVAILABLE",
                )

            # Không ép dynamic-shape transformer của Florence-2 lên NPU hay ONNX
            candidates = [
                c
                for c in resolve_backend_candidates(norm, allow_npu=False)
                if not c.startswith("onnx:")
            ]
            if not candidates:
                candidates = ["pytorch:cpu"]

            errors: list[str] = []
            for candidate in candidates:
                try:
                    if candidate.startswith("openvino:"):
                        self._load_openvino_candidate(candidate)
                    elif candidate.startswith("pytorch:"):
                        self._load_pytorch_candidate(candidate)
                    else:
                        continue

                    self._requested_backend = norm
                    self._backend_used = candidate
                    self._is_loaded = True
                    self.touch()
                    return
                except Exception as exc:
                    self._release_resources()
                    errors.append(f"{candidate}: {exc}")

            raise EngineError(
                f"Không thể nạp model Florence-2 trên các backend khả dụng ({'; '.join(errors)}).",
                status_code=503,
                code="MODEL_UNAVAILABLE",
            )

    def _release_resources(self) -> None:
        self._model = None
        self._processor = None
        self._runner = None
        self._requested_backend = "auto"

    def detect(
        self,
        rgb_uint8: np.ndarray,
        prompt: str | None = None,
        max_box_area_ratio: float = 0.85,
        backend: str | None = None,
    ) -> dict[str, Any]:
        """Phát hiện watermark/text và trả về bboxes đã lọc cùng binary mask `(H, W)` uint8."""
        if not isinstance(rgb_uint8, np.ndarray) or rgb_uint8.ndim != 3 or rgb_uint8.shape[2] != 3:
            raise EngineError(
                "Ảnh đầu vào cho FlorenceDetector phải là mảng RGB shape (H, W, 3).",
                status_code=400,
                code="BAD_REQUEST",
            )
        height, width = rgb_uint8.shape[:2]
        if height <= 0 or width <= 0:
            raise EngineError("Kích thước ảnh đầu vào không hợp lệ.", status_code=400, code="BAD_REQUEST")

        img = np.ascontiguousarray(rgb_uint8, dtype=np.uint8)

        with self._lock:
            target_backend = normalize_requested_backend(backend) if backend is not None else self._requested_backend
            if not self._is_loaded or (
                backend is not None
                and self._runner_override is None
                and target_backend != "auto"
                and target_backend != self._backend_used
            ):
                self.load(backend=target_backend)

            if self._runner is None:
                raise EngineError("FlorenceDetector chưa sẵn sàng sau khi load.", status_code=503, code="MODEL_UNAVAILABLE")

            self.touch()
            clean_prompt, full_prompt = build_florence_prompt(prompt, default_prompt=self.default_prompt)
            raw_output = self._runner(img, full_prompt)
            raw_bboxes = extract_raw_bboxes(raw_output, task_token=FLORENCE_TASK_TOKEN)
            self.touch()

        bboxes = sanitize_bboxes(
            raw_bboxes,
            width=width,
            height=height,
            max_area_ratio=max_box_area_ratio,
        )
        mask = bboxes_to_binary_mask(bboxes, width=width, height=height)

        return {
            "bboxes": bboxes,
            "mask": mask,
            "prompt_used": clean_prompt,
            "backend_used": self._backend_used,
            "width": width,
            "height": height,
        }

    def predict(self, rgb_uint8: np.ndarray, prompt: str | None = None, **kwargs: Any) -> dict[str, Any]:
        """Ủy quyền suy luận chuẩn IAiEngine sang `detect()`."""
        return self.detect(rgb_uint8=rgb_uint8, prompt=prompt, **kwargs)
