from __future__ import annotations

import gc
import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from backend.app.engines.base import EngineError, IAiEngine
from backend.app.engines.florence_detector import (
    FLORENCE_TASK_TOKEN,
    FlorenceDetector,
    extract_raw_bboxes,
    sanitize_bboxes,
)
from backend.app.engines.memory_manager import (
    MemoryManager,
    get_memory_manager,
    reset_memory_manager,
)


class _DummyWeightBlob:
    """Đối tượng giữ tham chiếu yếu để kiểm chứng unload giải phóng bộ nhớ thật."""

    def __init__(self, tag: str) -> None:
        self.tag = tag


class _DummyEngine(IAiEngine):
    def __init__(self, name: str, events: list[str], weight_refs: dict[str, weakref.ref[Any]]) -> None:
        super().__init__(name=name, estimated_ram_mb=900)
        self._events = events
        self._weight_refs = weight_refs
        self._payload: _DummyWeightBlob | None = None
        self.load_count = 0

    def load(self, backend: str = "auto") -> None:
        with self._lock:
            self.load_count += 1
            self._events.append(f"load:{self.name}")
            blob = _DummyWeightBlob(self.name)
            self._payload = blob
            self._weight_refs[self.name] = weakref.ref(blob)
            self._backend_used = f"mock:{backend}"
            self._is_loaded = True
            self.touch()

    def _release_resources(self) -> None:
        self._events.append(f"unload:{self.name}")
        self._payload = None

    def predict(self, *args: Any, **kwargs: Any) -> Any:
        return {"ok": True}


def test_sanitize_bboxes_clamps_filters_and_deduplicates() -> None:
    raw = [
        [-12.4, 5.2, 48.1, 30.8],       # clamp âm -> [0, 5, 49, 31]
        [150.0, 80.0, 120.0, 60.0],    # đảo ngược tọa độ & vượt biên W=140 -> [120, 60, 140, 80]
        [10.0, 10.0, 10.4, 10.4],      # suy biến < 2px -> loại
        [0.0, 0.0, 138.0, 99.0],       # phủ > 85% ảnh 140x100 -> loại false-positive
        [-12.1, 5.4, 48.5, 30.6],      # trùng với box đầu sau chuẩn hóa -> khử trùng lặp
        [float("nan"), 1.0, 20.0, 20.0],
    ]
    cleaned = sanitize_bboxes(raw, width=140, height=100, max_area_ratio=0.85, min_side_px=2)
    assert cleaned == [
        [0, 5, 49, 31],
        [120, 60, 140, 80],
    ]


def test_extract_raw_bboxes_supports_dict_and_polygons() -> None:
    dict_result = {
        FLORENCE_TASK_TOKEN: {
            "bboxes": [[10.0, 15.0, 55.0, 35.0]],
            "bboxes_labels": ["watermark"],
        }
    }
    assert extract_raw_bboxes(dict_result) == [[10.0, 15.0, 55.0, 35.0]]

    poly_result = {
        FLORENCE_TASK_TOKEN: {
            "bboxes": [],
            "polygons": [[[12.0, 20.0, 42.0, 20.0, 42.0, 38.0, 12.0, 38.0]]],
        }
    }
    assert extract_raw_bboxes(poly_result) == [[12.0, 20.0, 42.0, 38.0]]


def test_florence_detector_mock_detect_to_mask_and_unload() -> None:
    seen_prompts: list[str] = []

    def _mock_runner(rgb_uint8: np.ndarray, full_prompt: str) -> list[list[float]]:
        seen_prompts.append(full_prompt)
        assert rgb_uint8.shape == (80, 120, 3)
        return [[10.2, 20.0, 40.0, 35.0], [0.0, 0.0, 118.0, 78.0]]  # box thứ 2 quá to sẽ bị lọc

    detector = FlorenceDetector(runner_override=_mock_runner)
    img = np.zeros((80, 120, 3), dtype=np.uint8)

    result = detector.predict(img, prompt="logo, watermark")
    assert detector.is_loaded is True
    assert detector.backend_used == "mock:override"
    assert seen_prompts == [f"{FLORENCE_TASK_TOKEN}logo, watermark"]
    assert result["bboxes"] == [[10, 20, 40, 35]]

    mask = result["mask"]
    assert mask.shape == (80, 120)
    assert mask.dtype == np.uint8
    assert set(np.unique(mask).tolist()).issubset({0, 255})
    assert int(mask[25, 25]) == 255
    assert int(mask[5, 5]) == 0

    detector.unload()
    assert detector.is_loaded is False
    assert detector.backend_used == "unloaded"


def test_florence_detector_validation_and_missing_weights(tmp_path: Path) -> None:
    detector = FlorenceDetector(models_dir=tmp_path, allow_hub_download=False)

    with pytest.raises(EngineError) as bad_req:
        detector.detect(np.zeros((32, 32), dtype=np.uint8))
    assert bad_req.value.status_code == 400
    assert bad_req.value.code == "BAD_REQUEST"

    with pytest.raises(EngineError) as missing:
        detector.detect(np.zeros((32, 32, 3), dtype=np.uint8))
    assert missing.value.status_code == 503
    assert missing.value.code == "MODEL_UNAVAILABLE"


def test_memory_manager_low_mem_sequential_swap_releases_refs() -> None:
    events: list[str] = []
    weight_refs: dict[str, weakref.ref[Any]] = {}
    manager = MemoryManager(low_mem_mode=True, auto_unload_seconds=180)
    florence = _DummyEngine("florence2", events, weight_refs)
    lama = _DummyEngine("lama", events, weight_refs)
    manager.register_engine(florence)
    manager.register_engine(lama)

    manager.acquire("florence2")
    assert manager.loaded_models() == ["florence2"]
    assert weight_refs["florence2"]() is not None

    # Trong low_mem_mode=True: nạp lama phải unload florence2 trước khi load lama
    manager.acquire("lama")
    gc.collect()
    assert manager.loaded_models() == ["lama"]
    assert events == ["load:florence2", "unload:florence2", "load:lama"]
    assert weight_refs["florence2"]() is None
    assert weight_refs["lama"]() is not None

    # Khi tắt low_mem_mode: cho phép nạp song song cả 2 engine
    manager.acquire("florence2", low_mem_mode=False)
    assert set(manager.loaded_models()) == {"florence2", "lama"}


def test_memory_manager_auto_unload_expiry_and_lease_protection() -> None:
    events: list[str] = []
    weight_refs: dict[str, weakref.ref[Any]] = {}
    manager = MemoryManager(low_mem_mode=True, auto_unload_seconds=60)
    florence = _DummyEngine("florence2", events, weight_refs)
    manager.register_engine(florence)

    with manager.lease("florence2") as eng:
        assert eng.is_loaded is True
        # Trong thời gian lease hoạt động, dù clock nhảy xa cũng không bị auto-unload giữa chừng
        assert manager.cleanup_expired(now=eng.last_used_at + 999.0) == []
        assert eng.is_loaded is True

    # Chưa quá hạn 60s -> vẫn giữ trong RAM
    assert manager.cleanup_expired(now=florence.last_used_at + 30.0) == []
    assert florence.is_loaded is True

    # Quá hạn 60s -> tự động giải phóng
    unloaded = manager.cleanup_expired(now=florence.last_used_at + 61.0)
    assert unloaded == ["florence2"]
    assert florence.is_loaded is False


def test_memory_manager_thread_safe_lazy_load_and_snapshot() -> None:
    events: list[str] = []
    weight_refs: dict[str, weakref.ref[Any]] = {}
    manager = MemoryManager(low_mem_mode=True, auto_unload_seconds=180)
    florence = _DummyEngine("florence2", events, weight_refs)
    manager.register_engine(florence)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: manager.acquire("florence2"), range(8)))

    assert all(r is florence for r in results)
    assert florence.load_count == 1

    snapshot = manager.get_memory_snapshot()
    assert snapshot["loaded_models"] == ["florence2"]
    assert snapshot["total_ram_mb"] > 0
    assert snapshot["process_rss_mb"] > 0

    assert manager.unload_all() == ["florence2"]
    assert manager.loaded_models() == []

    # Kiểm tra singleton module đăng ký đủ cả florence2 và lama
    reset_memory_manager()
    singleton = get_memory_manager()
    assert singleton.get_engine("florence2").name == "florence2"
    assert singleton.get_engine("lama").name == "lama"
    reset_memory_manager()
