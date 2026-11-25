from __future__ import annotations

import base64
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.config import Settings
from backend.app.engines.florence_detector import FlorenceDetector
from backend.app.engines.lama_inpainter import LamaInpainter
from backend.app.engines.memory_manager import MemoryManager
from backend.app.main import create_app


def _make_png_bytes(
    width: int = 64,
    height: int = 48,
    rgba: bool = False,
    seed: int = 7,
) -> tuple[bytes, np.ndarray, np.ndarray | None]:
    rng = np.random.default_rng(seed)
    rgb = rng.integers(30, 220, size=(height, width, 3), dtype=np.uint8)
    alpha = None
    if rgba:
        alpha = np.full((height, width), 255, dtype=np.uint8)
        alpha[:10, :12] = 0
        alpha[10:20, :12] = 128
        arr = np.dstack([rgb, alpha])
        img = Image.fromarray(arr, mode="RGBA")
    else:
        img = Image.fromarray(rgb, mode="RGB")

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), rgb, alpha


def _make_mask_bytes(width: int = 64, height: int = 48, box: tuple[int, int, int, int] = (16, 12, 40, 30)) -> bytes:
    mask = np.zeros((height, width), dtype=np.uint8)
    x1, y1, x2, y2 = box
    mask[y1:y2, x1:x2] = 255
    buf = BytesIO()
    Image.fromarray(mask, mode="L").save(buf, format="PNG")
    return buf.getvalue()


def _create_mock_app(
    tmp_path: Path,
    *,
    low_mem_mode: bool = True,
    max_input_size_mb: int = 20,
    max_concurrent_jobs: int = 1,
    frontend_dist_dir: Path | None = None,
    detect_delay_s: float = 0.0,
    inpaint_delay_s: float = 0.0,
    active_tracker: dict[str, int] | None = None,
    real_missing_weights: bool = False,
) -> tuple[TestClient, MemoryManager]:
    settings = Settings(
        models_dir=tmp_path / "models",
        frontend_dist_dir=frontend_dist_dir if frontend_dist_dir is not None else (tmp_path / "no_dist"),
        low_mem_mode=low_mem_mode,
        max_input_size_mb=max_input_size_mb,
        max_concurrent_jobs=max_concurrent_jobs,
    )
    manager = MemoryManager(low_mem_mode=low_mem_mode, auto_unload_seconds=180)
    tracker_lock = threading.Lock()

    def _enter_track() -> None:
        if active_tracker is None:
            return
        with tracker_lock:
            active_tracker["current"] += 1
            active_tracker["peak"] = max(active_tracker["peak"], active_tracker["current"])

    def _exit_track() -> None:
        if active_tracker is None:
            return
        with tracker_lock:
            active_tracker["current"] -= 1

    if real_missing_weights:
        florence = FlorenceDetector(models_dir=tmp_path / "empty_models", allow_hub_download=False)
        lama = LamaInpainter(models_dir=tmp_path / "empty_models")
    else:
        def _fake_detect(img: np.ndarray, full_prompt: str) -> dict:
            _enter_track()
            try:
                if detect_delay_s > 0:
                    time.sleep(detect_delay_s)
                h, w = img.shape[:2]
                return {
                    "<OPEN_VOCABULARY_DETECTION>": {
                        "bboxes": [[4.0, 6.0, float(min(w - 2, 28)), float(min(h - 2, 22))]],
                        "labels": ["watermark"],
                    }
                }
            finally:
                _exit_track()

        def _fake_inpaint(img_nchw: np.ndarray, mask_nchw: np.ndarray) -> np.ndarray:
            _enter_track()
            try:
                if inpaint_delay_s > 0:
                    time.sleep(inpaint_delay_s)
                out = img_nchw.copy()
                m = mask_nchw > 0.5
                for c in range(3):
                    channel = out[:, c : c + 1, :, :]
                    channel[m] = 0.25 if c == 0 else (0.75 if c == 1 else 0.5)
                return out
            finally:
                _exit_track()

        florence = FlorenceDetector(models_dir=tmp_path / "models", runner_override=_fake_detect)
        lama = LamaInpainter(models_dir=tmp_path / "models", runner_override=_fake_inpaint)

    manager.register_engine(florence)
    manager.register_engine(lama)
    app = create_app(settings=settings, memory_manager=manager)
    return TestClient(app), manager


def test_health_and_unload_lifecycle(tmp_path: Path) -> None:
    client, manager = _create_mock_app(tmp_path)
    with client:
        r0 = client.get("/api/v1/health")
        assert r0.status_code == 200
        body0 = r0.json()
        assert body0["status"] == "ok"
        assert body0["loaded_models"] == []
        assert body0["low_mem_mode"] is True
        assert body0["uptime_s"] >= 0.0

        img_bytes, _, _ = _make_png_bytes(48, 36)
        r_det = client.post(
            "/api/v1/detect",
            files={"image": ("sample.png", img_bytes, "image/png")},
        )
        assert r_det.status_code == 200
        assert manager.loaded_models() == ["florence2"]

        r1 = client.get("/api/v1/health")
        assert r1.status_code == 200
        assert r1.json()["loaded_models"] == ["florence2"]

        r_unload = client.post("/api/v1/models/unload")
        assert r_unload.status_code == 200
        unload_body = r_unload.json()
        assert unload_body["status"] == "ok"
        assert unload_body["unloaded"] == ["florence2"]
        assert unload_body["available_ram_mb"] > 0
        assert manager.loaded_models() == []


def test_hardware_probe_endpoint(tmp_path: Path) -> None:
    client, _ = _create_mock_app(tmp_path)
    with client:
        res = client.get("/api/v1/hardware")
        assert res.status_code == 200
        body = res.json()
        assert isinstance(body["cpu"], str) and len(body["cpu"]) > 0
        assert isinstance(body["devices"], list) and len(body["devices"]) >= 1
        assert isinstance(body["recommended_backend"], str) and len(body["recommended_backend"]) > 0
        assert body["total_ram_mb"] > 0
        assert body["available_ram_mb"] > 0


def test_detect_endpoint_returns_valid_base64_mask(tmp_path: Path) -> None:
    client, _ = _create_mock_app(tmp_path)
    img_bytes, _, _ = _make_png_bytes(70, 50)
    with client:
        res = client.post(
            "/api/v1/detect",
            files={"image": ("test.png", img_bytes, "image/png")},
            data={"prompt": "watermark, logo", "dilation_px": "3"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "success"
        assert body["width"] == 70
        assert body["height"] == 50
        assert body["bboxes"] == [[4, 6, 28, 22]]
        assert body["latency_ms"] >= 0.0
        assert body["backend_used"] == "mock:override"
        assert body["mask_base64"].startswith("data:image/png;base64,")

        raw_png = base64.b64decode(body["mask_base64"].split(",", 1)[1])
        mask_img = Image.open(BytesIO(raw_png))
        assert mask_img.size == (70, 50)
        mask_arr = np.asarray(mask_img)
        assert np.any(mask_arr == 255)


def test_inpaint_preserves_odd_rgba_alpha_and_headers(tmp_path: Path) -> None:
    client, _ = _create_mock_app(tmp_path)
    # Kích thước lẻ 53x37 + kênh Alpha có cả vùng trong suốt và bán trong suốt
    img_bytes, orig_rgb, orig_alpha = _make_png_bytes(53, 37, rgba=True)
    mask_bytes = _make_mask_bytes(53, 37, box=(16, 12, 34, 26))

    with client:
        res = client.post(
            "/api/v1/inpaint",
            headers={"Origin": "http://localhost:5173"},
            files={
                "image": ("odd_rgba.png", img_bytes, "image/png"),
                "mask": ("mask.png", mask_bytes, "image/png"),
            },
            data={"dilation_px": "0", "low_mem_mode": "true"},
        )
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("image/png")
        assert float(res.headers["x-latency-ms"]) >= 0.0
        assert res.headers["x-backend-used"] == "mock"
        assert int(res.headers["x-ram-used-mb"]) > 0
        assert "X-Latency-Ms" in res.headers.get("access-control-expose-headers", "")

        out_img = Image.open(BytesIO(res.content))
        assert out_img.mode == "RGBA"
        assert out_img.size == (53, 37)
        out_arr = np.asarray(out_img)
        assert np.array_equal(out_arr[:, :, 3], orig_alpha)
        # Pixel ngoài mask phải giữ nguyên từng bit so với ảnh gốc
        assert np.array_equal(out_arr[0:10, 0:10, :3], orig_rgb[0:10, 0:10, :])
        # Pixel trong mask đã được tái tạo khác ảnh gốc
        assert not np.array_equal(out_arr[14:24, 18:32, :3], orig_rgb[14:24, 18:32, :])


def test_low_mem_sequential_swap_between_detect_and_inpaint(tmp_path: Path) -> None:
    client, manager = _create_mock_app(tmp_path, low_mem_mode=True)
    img_bytes, _, _ = _make_png_bytes(48, 32)
    mask_bytes = _make_mask_bytes(48, 32)

    with client:
        r_det = client.post("/api/v1/detect", files={"image": ("a.png", img_bytes, "image/png")})
        assert r_det.status_code == 200
        assert manager.loaded_models() == ["florence2"]

        r_inp = client.post(
            "/api/v1/inpaint",
            files={
                "image": ("a.png", img_bytes, "image/png"),
                "mask": ("m.png", mask_bytes, "image/png"),
            },
        )
        assert r_inp.status_code == 200
        # low_mem_mode=True phải unload florence2 trước khi nạp lama
        assert manager.loaded_models() == ["lama"]


def test_validation_and_error_responses(tmp_path: Path) -> None:
    client, _ = _create_mock_app(tmp_path, max_input_size_mb=1)
    img_bytes, _, _ = _make_png_bytes(64, 48)
    wrong_ratio_mask = _make_mask_bytes(64, 16, box=(4, 2, 20, 10))
    valid_mask = _make_mask_bytes(64, 48)

    with client:
        # 1. File giả mạo MIME / magic bytes sai
        r_mime = client.post(
            "/api/v1/detect",
            files={"image": ("fake.png", b"NOT_AN_IMAGE_PAYLOAD", "image/png")},
        )
        assert r_mime.status_code == 415
        assert r_mime.json()["code"] == "UNSUPPORTED_MEDIA_TYPE"

        # 2. Quá dung lượng 1 MB
        oversized = b"\x89PNG\r\n\x1a\n" + (b"0" * (1024 * 1024 + 32))
        r_big = client.post(
            "/api/v1/detect",
            files={"image": ("big.png", oversized, "image/png")},
        )
        assert r_big.status_code == 413
        assert r_big.json()["code"] == "PAYLOAD_TOO_LARGE"

        # 3. Mask lệch tỷ lệ ảnh gốc
        r_mismatch = client.post(
            "/api/v1/inpaint",
            files={
                "image": ("img.png", img_bytes, "image/png"),
                "mask": ("mask.png", wrong_ratio_mask, "image/png"),
            },
        )
        assert r_mismatch.status_code == 400
        assert r_mismatch.json()["code"] == "MASK_DIMENSION_MISMATCH"

        # 4. dilation_px ngoài 0..25
        r_dil = client.post(
            "/api/v1/inpaint",
            files={
                "image": ("img.png", img_bytes, "image/png"),
                "mask": ("mask.png", valid_mask, "image/png"),
            },
            data={"dilation_px": "99"},
        )
        assert r_dil.status_code == 422
        assert r_dil.json()["code"] == "VALIDATION_ERROR"

    # 5. Thiếu trọng số local khi gọi /detect thật
    client_no_weights, _ = _create_mock_app(tmp_path, real_missing_weights=True)
    with client_no_weights:
        r_missing = client_no_weights.post(
            "/api/v1/detect",
            files={"image": ("img.png", img_bytes, "image/png")},
        )
        assert r_missing.status_code == 503
        assert r_missing.json()["code"] == "MODEL_UNAVAILABLE"


def test_concurrency_semaphore_serializes_heavy_jobs(tmp_path: Path) -> None:
    tracker = {"current": 0, "peak": 0}
    client, _ = _create_mock_app(
        tmp_path,
        max_concurrent_jobs=1,
        inpaint_delay_s=0.12,
        active_tracker=tracker,
    )
    img_bytes, _, _ = _make_png_bytes(40, 40)
    mask_bytes = _make_mask_bytes(40, 40, box=(10, 10, 24, 24))

    def _call_inpaint() -> int:
        res = client.post(
            "/api/v1/inpaint",
            files={
                "image": ("img.png", img_bytes, "image/png"),
                "mask": ("mask.png", mask_bytes, "image/png"),
            },
        )
        return res.status_code

    with client:
        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(_call_inpaint)
            f2 = pool.submit(_call_inpaint)
            codes = [f1.result(timeout=15), f2.result(timeout=15)]

    assert codes == [200, 200]
    assert tracker["peak"] == 1


def test_static_frontend_dist_spa_serving(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text("<html><body>AI Watermark Studio</body></html>", encoding="utf-8")
    (assets_dir / "app.js").write_text("console.log('ok');", encoding="utf-8")

    client, _ = _create_mock_app(tmp_path, frontend_dist_dir=dist_dir)
    with client:
        r_root = client.get("/")
        assert r_root.status_code == 200
        assert "AI Watermark Studio" in r_root.text

        r_asset = client.get("/assets/app.js")
        assert r_asset.status_code == 200
        assert "console.log" in r_asset.text

        r_spa = client.get("/editor/workspace")
        assert r_spa.status_code == 200
        assert "AI Watermark Studio" in r_spa.text

        r_api_404 = client.get("/api/v1/does-not-exist")
        assert r_api_404.status_code == 404
        assert r_api_404.json()["code"] == "NOT_FOUND"
