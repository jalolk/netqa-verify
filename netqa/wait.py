from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")


class WaitTimeout(AssertionError):
    pass


def wait_until(
    predicate: Callable[[], bool],
    timeout: float = 60.0,
    interval: float = 1.0,
    description: str = "condition",
) -> float:
    deadline = time.monotonic() + timeout
    started = time.monotonic()
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            if predicate():
                return time.monotonic() - started
        except Exception as exc:
            last_error = exc
        time.sleep(interval)

    suffix = f" (last error: {last_error})" if last_error else ""
    raise WaitTimeout(f"timed out after {timeout:.0f}s waiting for {description}{suffix}")


def wait_for_value(
    supplier: Callable[[], T],
    predicate: Callable[[T], bool],
    timeout: float = 60.0,
    interval: float = 1.0,
    description: str = "value",
) -> T:
    deadline = time.monotonic() + timeout
    latest: T | None = None
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            latest = supplier()
            if predicate(latest):
                return latest
        except Exception as exc:
            last_error = exc
        time.sleep(interval)

    detail = f"last value: {latest!r}" if last_error is None else f"last error: {last_error}"
    raise WaitTimeout(f"timed out after {timeout:.0f}s waiting for {description} ({detail})")
