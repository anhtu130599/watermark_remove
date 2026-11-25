from __future__ import annotations

import gc
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

import psutil

from backend.app.config import get_settings
from backend.app.engines.base import EngineError, IAiEngine, normalize_requested_backend
from backend.app.engines.florence_detector import FlorenceDetector
from backend.app.engines.lama_inpainter import LamaInpainter


class MemoryManager:
    """Điều phối tải/giải phóng AI Engine giúp máy 16 GB RAM không bị tràn bộ nhớ."""

    def __init__(
        self,
        low_mem_mode: bool | None = None,
        auto_unload_seconds: int | None = None,
    ) -> None:
        settings = get_settings()
        self.low_mem_mode: bool = settings.low_mem_mode if low_mem_mode is None else bool(low_mem_mode)
        self.auto_unload_seconds: int = (
            settings.auto_unload_seconds if auto_unload_seconds is None else int(auto_unload_seconds)
        )
        self._lock = threading.RLock()
        self._engines: dict[str, IAiEngine] = {}
        self._active_counts: dict[str, int] = {}
        self._stop_event = threading.Event()
        self._reaper_thread: threading.Thread | None = None

    def register_engine(self, engine: IAiEngine) -> None:
        """Đăng ký một engine theo `engine.name`."""
        with self._lock:
            self._engines[engine.name] = engine
            self._active_counts.setdefault(engine.name, 0)

    def get_engine(self, name: str) -> IAiEngine:
        """Lấy engine đã đăng ký hoặc ném EngineError 404 nếu không tồn tại."""
        with self._lock:
            if name not in self._engines:
                raise EngineError(f"Engine '{name}' chưa được đăng ký.", status_code=404, code="NOT_FOUND")
            return self._engines[name]

    def loaded_models(self) -> list[str]:
        """Trả về danh sách tên các engine hiện đang nằm trong RAM/VRAM."""
        with self._lock:
            return [name for name, engine in self._engines.items() if engine.is_loaded]

    def acquire(
        self,
        name: str,
        backend: str = "auto",
        low_mem_mode: bool | None = None,
    ) -> IAiEngine:
        """Nạp lười engine đích; nếu `low_mem_mode=True` sẽ unload engine khác trước khi nạp."""
        with self._lock:
            self.cleanup_expired()
            target = self.get_engine(name)
            effective_low_mem = self.low_mem_mode if low_mem_mode is None else bool(low_mem_mode)

            if effective_low_mem:
                for other_name, other_engine in self._engines.items():
                    if other_name == name:
                        continue
                    if other_engine.is_loaded and self._active_counts.get(other_name, 0) == 0:
                        other_engine.unload()

            norm_backend = normalize_requested_backend(backend)
            needs_reload = (
                not target.is_loaded
                or (
                    norm_backend != "auto"
                    and target.backend_used != "mock:override"
                    and norm_backend != target.backend_used
                )
            )
            if needs_reload:
                target.load(backend=backend)

            target.touch()
            return target

    @contextmanager
    def lease(
        self,
        name: str,
        backend: str = "auto",
        low_mem_mode: bool | None = None,
    ) -> Iterator[IAiEngine]:
        """Giữ engine an toàn trong suốt thời gian suy luận, chống auto-unload giữa chừng."""
        with self._lock:
            engine = self.acquire(name=name, backend=backend, low_mem_mode=low_mem_mode)
            self._active_counts[name] = self._active_counts.get(name, 0) + 1
        try:
            yield engine
        finally:
            with self._lock:
                self._active_counts[name] = max(0, self._active_counts.get(name, 1) - 1)
                engine.touch()

    def cleanup_expired(self, now: float | None = None) -> list[str]:
        """Tự động giải phóng các engine nhàn rỗi quá `auto_unload_seconds`."""
        with self._lock:
            if self.auto_unload_seconds <= 0:
                return []
            current = time.monotonic() if now is None else float(now)
            unloaded: list[str] = []
            for name, engine in self._engines.items():
                if not engine.is_loaded:
                    continue
                if self._active_counts.get(name, 0) > 0:
                    continue
                if engine.last_used_at > 0.0 and (current - engine.last_used_at) >= self.auto_unload_seconds:
                    engine.unload()
                    unloaded.append(name)
            return unloaded

    def unload_engine(self, name: str) -> bool:
        """Giải phóng một engine cụ thể nếu đang nạp và không bận suy luận."""
        with self._lock:
            engine = self.get_engine(name)
            if not engine.is_loaded or self._active_counts.get(name, 0) > 0:
                return False
            engine.unload()
            return True

    def unload_all(self) -> list[str]:
        """Giải phóng toàn bộ AI model đang chiếm RAM/VRAM."""
        with self._lock:
            unloaded: list[str] = []
            for name, engine in self._engines.items():
                if engine.is_loaded and self._active_counts.get(name, 0) == 0:
                    engine.unload()
                    unloaded.append(name)
            gc.collect()
            return unloaded

    def get_memory_snapshot(self) -> dict[str, Any]:
        """Đọc thống kê RAM thực tế của tiến trình và toàn hệ thống."""
        with self._lock:
            loaded = self.loaded_models()
            low_mem = self.low_mem_mode

        try:
            vm = psutil.virtual_memory()
            proc_rss_mb = int(round(psutil.Process().memory_info().rss / (1024 * 1024)))
            total_ram_mb = int(round(vm.total / (1024 * 1024)))
            available_ram_mb = int(round(vm.available / (1024 * 1024)))
            used_percent = float(vm.percent)
        except Exception:
            proc_rss_mb = 0
            total_ram_mb = 0
            available_ram_mb = 0
            used_percent = 0.0

        return {
            "process_rss_mb": proc_rss_mb,
            "total_ram_mb": total_ram_mb,
            "available_ram_mb": available_ram_mb,
            "used_percent": used_percent,
            "loaded_models": loaded,
            "low_mem_mode": low_mem,
        }

    def start_reaper(self, interval_seconds: float = 15.0) -> None:
        """Bật luồng nền kiểm tra định kỳ `auto_unload_seconds`."""
        with self._lock:
            if self._reaper_thread is not None and self._reaper_thread.is_alive():
                return
            self._stop_event.clear()

            def _loop() -> None:
                while not self._stop_event.wait(interval_seconds):
                    try:
                        self.cleanup_expired()
                    except Exception:
                        pass

            self._reaper_thread = threading.Thread(
                target=_loop,
                name="ai-memory-reaper",
                daemon=True,
            )
            self._reaper_thread.start()

    def stop_reaper(self) -> None:
        """Dừng luồng nền reaper gọn gàng."""
        self._stop_event.set()
        thread = self._reaper_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._reaper_thread = None


_MANAGER_LOCK = threading.Lock()
_MEMORY_MANAGER: MemoryManager | None = None


def get_memory_manager() -> MemoryManager:
    """Trả về Singleton MemoryManager đã đăng ký sẵn Florence-2 và LaMa."""
    global _MEMORY_MANAGER
    with _MANAGER_LOCK:
        if _MEMORY_MANAGER is None:
            manager = MemoryManager()
            manager.register_engine(FlorenceDetector())
            manager.register_engine(LamaInpainter())
            _MEMORY_MANAGER = manager
        return _MEMORY_MANAGER


def reset_memory_manager() -> None:
    """Dọn dẹp và đặt lại Singleton MemoryManager (phục vụ kiểm thử)."""
    global _MEMORY_MANAGER
    with _MANAGER_LOCK:
        if _MEMORY_MANAGER is not None:
            _MEMORY_MANAGER.stop_reaper()
            _MEMORY_MANAGER.unload_all()
            _MEMORY_MANAGER = None
