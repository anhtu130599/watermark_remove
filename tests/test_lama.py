from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.app.engines.base import EngineError, resolve_backend_candidates
from backend.app.engines.lama_inpainter import (
    LamaInpainter,
    compute_context_rois,
    crop_to_shape,
    pad_to_modulo,
    postprocess_lama_output,
    prepare_lama_inputs,
)


def test_pad_to_modulo_and_crop_odd_dimensions() -> None:
    # 1x1x3 -> 8x8x3
    tiny = np.array([[[12, 34, 56]]], dtype=np.uint8)
    padded_tiny = pad_to_modulo(tiny, mod=8)
    assert padded_tiny.shape == (8, 8, 3)
    assert np.array_equal(crop_to_shape(padded_tiny, 1, 1), tiny)

    # 8x8 -> giữ nguyên không pad dư
    exact = np.arange(64, dtype=np.uint8).reshape(8, 8)
    padded_exact = pad_to_modulo(exact, mod=8)
    assert padded_exact.shape == (8, 8)
    assert np.array_equal(padded_exact, exact)

    # Kích thước lẻ điển hình: 77x101x3 -> 80x104x3, và 1079x1920x3 -> 1080x1920x3
    odd_rgb = np.random.default_rng(42).integers(0, 256, size=(77, 101, 3), dtype=np.uint8)
    padded_odd = pad_to_modulo(odd_rgb, mod=8)
    assert padded_odd.shape == (80, 104, 3)
    assert padded_odd.shape[0] % 8 == 0 and padded_odd.shape[1] % 8 == 0
    assert np.array_equal(crop_to_shape(padded_odd, 77, 101), odd_rgb)

    hd_odd = np.zeros((1079, 1920, 3), dtype=np.uint8)
    assert pad_to_modulo(hd_odd, mod=8).shape == (1080, 1920, 3)


def test_prepare_and_postprocess_lama_tensors() -> None:
    rgb = np.full((53, 67, 3), 128, dtype=np.uint8)
    mask = np.zeros((53, 67), dtype=np.uint8)
    mask[10:20, 15:25] = 255

    img_nchw, mask_nchw, orig_hw = prepare_lama_inputs(rgb, mask, mod=8)
    assert orig_hw == (53, 67)
    assert img_nchw.shape == (1, 3, 56, 72)
    assert mask_nchw.shape == (1, 1, 56, 72)
    assert img_nchw.dtype == np.float32
    assert mask_nchw.dtype == np.float32
    assert float(img_nchw.min()) >= 0.0 and float(img_nchw.max()) <= 1.0
    assert set(np.unique(mask_nchw).tolist()).issubset({0.0, 1.0})

    # Hỗ trợ cả output [0..1] lẫn [0..255]
    out_01 = np.ones((1, 3, 56, 72), dtype=np.float32) * 0.5
    restored_01 = postprocess_lama_output(out_01, orig_hw)
    assert restored_01.shape == (53, 67, 3)
    assert restored_01.dtype == np.uint8
    assert np.all((restored_01 >= 127) & (restored_01 <= 128))

    out_255 = np.full((3, 56, 72), 200.0, dtype=np.float32)
    restored_255 = postprocess_lama_output(out_255, orig_hw)
    assert restored_255.shape == (53, 67, 3)
    assert np.all(restored_255 == 200)


def test_inpaint_empty_mask_fast_path(tmp_path: Path) -> None:
    called = {"count": 0}

    def _never_called(img_t: np.ndarray, mask_t: np.ndarray) -> np.ndarray:
        called["count"] += 1
        return img_t

    engine = LamaInpainter(models_dir=tmp_path, runner_override=_never_called)
    rgb = np.random.default_rng(7).integers(0, 255, size=(33, 41, 3), dtype=np.uint8)
    empty_mask = np.zeros((33, 41), dtype=np.uint8)

    out = engine.inpaint(rgb, empty_mask)
    assert called["count"] == 0
    assert engine.is_loaded is False
    assert np.array_equal(out, rgb)


def test_inpaint_mock_runner_preserves_unmasked_pixels(tmp_path: Path) -> None:
    captured_shapes: list[tuple[tuple[int, ...], tuple[int, ...]]] = []

    def _mock_red_runner(img_nchw: np.ndarray, mask_nchw: np.ndarray) -> np.ndarray:
        captured_shapes.append((img_nchw.shape, mask_nchw.shape))
        out = np.zeros_like(img_nchw, dtype=np.float32)
        out[:, 0, :, :] = 1.0  # R = 255, G = 0, B = 0
        return out

    engine = LamaInpainter(models_dir=tmp_path, runner_override=_mock_red_runner)
    rgb = np.random.default_rng(99).integers(10, 220, size=(53, 67, 3), dtype=np.uint8)
    mask = np.zeros((53, 67), dtype=np.uint8)
    mask[12:24, 18:30] = 255

    result = engine.inpaint(rgb, mask)
    assert engine.is_loaded is True
    assert engine.backend_used == "mock"
    assert captured_shapes == [((1, 3, 56, 72), (1, 1, 56, 72))]
    assert result.shape == (53, 67, 3)
    assert result.dtype == np.uint8

    # Vùng trong mask được thay thành đỏ [255, 0, 0]
    assert np.all(result[12:24, 18:30] == np.array([255, 0, 0], dtype=np.uint8))
    # Toàn bộ pixel ngoài mask giữ nguyên 100% từng bit
    outside = mask == 0
    assert np.array_equal(result[outside], rgb[outside])

    engine.unload()
    assert engine.is_loaded is False
    assert engine.backend_used == "unloaded"


def test_missing_weights_raises_503_model_unavailable(tmp_path: Path) -> None:
    engine = LamaInpainter(models_dir=tmp_path)
    with pytest.raises(EngineError) as exc_info:
        engine.load(backend="auto")

    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "MODEL_UNAVAILABLE"


def test_resolve_backend_candidates_fallback_and_no_npu() -> None:
    full_ov = {
        "openvino_available": True,
        "openvino_devices": ["CPU", "GPU", "NPU"],
        "torch_available": True,
        "cuda_available": True,
        "ort_available": True,
        "ort_providers": ["DmlExecutionProvider", "CPUExecutionProvider"],
    }
    candidates = resolve_backend_candidates("auto", runtime_info=full_ov, allow_npu=False)
    assert candidates == [
        "openvino:GPU",
        "openvino:CPU",
        "pytorch:cuda",
        "onnx:dml",
        "pytorch:cpu",
        "onnx:cpu",
    ]
    assert "openvino:NPU" not in candidates

    # Khi thiếu OpenVINO và CUDA, fallback về DirectML / PyTorch CPU
    cpu_dml_only = {
        "openvino_available": False,
        "openvino_devices": [],
        "torch_available": True,
        "cuda_available": False,
        "ort_available": True,
        "ort_providers": ["DmlExecutionProvider", "CPUExecutionProvider"],
    }
    fallback = resolve_backend_candidates("openvino:GPU", runtime_info=cpu_dml_only, allow_npu=False)
    assert fallback == ["onnx:dml", "pytorch:cpu", "onnx:cpu"]


def test_postprocess_lama_output_rejects_nan_and_inf() -> None:
    nan_out = np.full((1, 3, 16, 16), np.nan, dtype=np.float32)
    with pytest.raises(EngineError) as nan_exc:
        postprocess_lama_output(nan_out, (16, 16))
    assert nan_exc.value.status_code == 500
    assert nan_exc.value.code == "INTERNAL_ERROR"

    inf_out = np.full((1, 3, 16, 16), np.inf, dtype=np.float32)
    with pytest.raises(EngineError):
        postprocess_lama_output(inf_out, (16, 16))


def test_inpaint_nan_runner_falls_back_to_safe_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / "big-lama.pt").write_bytes(b"stub-pt")

    engine = LamaInpainter(models_dir=models_dir)
    monkeypatch.setattr(
        "backend.app.engines.lama_inpainter.resolve_backend_candidates",
        lambda req="auto", **_kwargs: ["pytorch:cpu"] if req == "pytorch:cpu" else ["openvino:GPU", "pytorch:cpu"],
    )

    def _bad_ov_gpu(_device: str):
        def _nan_runner(img_nchw: np.ndarray, _mask_nchw: np.ndarray) -> np.ndarray:
            return np.full_like(img_nchw, np.nan, dtype=np.float32)

        return "fake-ov", _nan_runner

    def _good_pytorch(_device: str):
        def _valid_runner(img_nchw: np.ndarray, _mask_nchw: np.ndarray) -> np.ndarray:
            out = np.zeros_like(img_nchw, dtype=np.float32)
            out[:, 1, :, :] = 0.75
            return out

        return "fake-pt", _valid_runner

    monkeypatch.setattr(engine, "_load_openvino", _bad_ov_gpu)
    monkeypatch.setattr(engine, "_load_pytorch", _good_pytorch)

    rgb = np.full((32, 32, 3), 80, dtype=np.uint8)
    mask = np.zeros((32, 32), dtype=np.uint8)
    mask[8:16, 8:16] = 255

    # Dù chỉ định openvino:GPU bị trả NaN, engine vẫn fallback sang pytorch:cpu chứ không xuất ảnh đen
    out = engine.inpaint(rgb, mask, backend="openvino:GPU")
    assert engine.backend_used == "pytorch:cpu"
    assert int(out[12, 12, 1]) in (191, 192)
    assert np.array_equal(out[mask == 0], rgb[mask == 0])


def test_compute_context_rois_corner_shift_and_merging() -> None:
    # Ảnh 1024x918 với mask nhỏ ở sát góc phải dưới -> ROI phải tự dịch khỏi mép để đủ 256x256
    mask = np.zeros((1024, 918), dtype=np.uint8)
    mask[945:995, 845:895] = 255
    rois = compute_context_rois(mask, min_crop=256)
    assert len(rois) == 1
    x1, y1, x2, y2 = rois[0]
    assert x2 == 918 and y2 == 1024
    assert (x2 - x1) >= 256 and (y2 - y1) >= 256
    assert x1 <= 845 and y1 <= 945

    # Hai watermark ở xa nhau (> merge_gap) -> tách 2 ROI cục bộ riêng biệt để giữ nét
    mask_two = np.zeros((1000, 1000), dtype=np.uint8)
    mask_two[40:80, 40:80] = 255
    mask_two[900:950, 900:950] = 255
    rois_two = compute_context_rois(mask_two, min_crop=256, merge_gap=64)
    assert len(rois_two) == 2
