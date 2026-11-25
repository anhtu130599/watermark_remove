from __future__ import annotations

import faulthandler
import os
import sys

_MAX_HARD_TIMEOUT_SECONDS = 540  # Luôn nhỏ hơn ngưỡng 10 phút (600s) của người dùng
_DEFAULT_HARD_TIMEOUT_SECONDS = 300


def pytest_configure(config) -> None:
    """Kích hoạt watchdog cấp C để tự dừng và in stack trace nếu test treo quá ngưỡng."""
    raw_val = os.getenv("PYTEST_HARD_TIMEOUT_SECONDS", str(_DEFAULT_HARD_TIMEOUT_SECONDS))
    try:
        timeout_s = int(raw_val)
    except ValueError:
        timeout_s = _DEFAULT_HARD_TIMEOUT_SECONDS

    timeout_s = max(10, min(timeout_s, _MAX_HARD_TIMEOUT_SECONDS))
    faulthandler.dump_traceback_later(timeout_s, exit=True, file=sys.stderr)


def pytest_unconfigure(config) -> None:
    """Hủy watchdog khi pytest kết thúc bình thường."""
    faulthandler.cancel_dump_traceback_later()
