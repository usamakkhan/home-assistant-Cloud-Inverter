from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import threading
import time
from typing import Any, Callable, Iterator


class CollectorUnavailable(RuntimeError):
    """Raised when inverter I/O is disabled or reserved for the vendor cloud."""


class CollectorController:
    """Fail-safe owner of inverter polling and the cached telemetry feed.

    Original mode performs no inverter I/O. Cooperative mode captures only
    outside heuristic five-minute quiet windows. Local mode polls directly
    without quiet windows. Both fall back to Original after repeated failures.
    Maintenance mode allows explicit
    diagnostic reads but never starts a background collector.
    """

    MODES = {"original", "local", "cooperative", "maintenance"}
    POLLING_MODES = {"local", "cooperative"}

    def __init__(
        self,
        capture: Callable[[str, int], dict[str, Any]],
        record: Callable[..., dict[str, Any]],
        record_error: Callable[..., dict[str, Any]],
        host: str,
        unit_id: int = 1,
        interval_seconds: int = 180,
        quiet_window_seconds: int = 45,
        failure_limit: int = 2,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._capture = capture
        self._record = record
        self._record_error = record_error
        self._clock = clock
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._capture_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._mode = "original"
        self._generation = 0
        self._host = host
        self._unit_id = unit_id
        self._interval_seconds = self._validate_interval(interval_seconds)
        self._quiet_window_seconds = self._validate_quiet_window(quiet_window_seconds)
        self._failure_limit = max(1, int(failure_limit))
        self._changed_at = self._utc_now()
        self._last_success_at: str | None = None
        self._last_error_at: str | None = None
        self._last_error: str | None = None
        self._fallback_reason: str | None = None
        self._consecutive_failures = 0
        self._capture_count = 0
        self._quiet_skips = 0
        self._cadence_overruns = 0
        self._last_capture_duration_ms: float | None = None
        self._manual_read_active = False
        self._next_due_monotonic: float | None = None

    @staticmethod
    def _validate_interval(value: int) -> int:
        value = int(value)
        if not 10 <= value <= 900:
            raise ValueError("capture interval must be between 10 and 900 seconds")
        return value

    @staticmethod
    def _validate_quiet_window(value: int) -> int:
        value = int(value)
        if not 30 <= value <= 90:
            raise ValueError("cloud quiet window must be between 30 and 90 seconds")
        return value

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, name="cooperative-datalogger", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _cloud_window(self, timestamp: float | None = None) -> tuple[bool, float]:
        timestamp = self._clock() if timestamp is None else timestamp
        phase = timestamp % 300
        quiet = self._quiet_window_seconds
        if phase < quiet:
            return True, quiet - phase
        if phase >= 300 - quiet:
            return True, (300 - phase) + quiet
        return False, 0.0

    def status(self) -> dict[str, Any]:
        quiet_now, safe_in = self._cloud_window()
        with self._lock:
            mode = self._mode
            next_capture_seconds = None
            if mode in self.POLLING_MODES and self._next_due_monotonic is not None:
                next_capture_seconds = max(
                    0, round(self._next_due_monotonic - self._monotonic())
                )
            return {
                "mode": mode,
                "original_path_active": mode == "original",
                "background_polling": mode in self.POLLING_MODES,
                "manual_device_tools": mode == "maintenance",
                "host": self._host,
                "unit_id": self._unit_id,
                "interval_seconds": self._interval_seconds,
                "quiet_window_seconds": self._quiet_window_seconds,
                "cloud_cycle_seconds": 300,
                "quiet_windows_enabled": mode == "cooperative",
                "in_cloud_quiet_window": mode == "cooperative" and quiet_now,
                "safe_window_in_seconds": round(safe_in) if mode == "cooperative" and quiet_now else 0,
                "next_capture_seconds": next_capture_seconds,
                "changed_at": self._changed_at,
                "last_success_at": self._last_success_at,
                "last_error_at": self._last_error_at,
                "last_error": self._last_error,
                "fallback_reason": self._fallback_reason,
                "consecutive_failures": self._consecutive_failures,
                "failure_limit": self._failure_limit,
                "capture_count": self._capture_count,
                "quiet_skips": self._quiet_skips,
                "cadence_overruns": self._cadence_overruns,
                "last_capture_duration_ms": self._last_capture_duration_ms,
                "capture_in_progress": self._capture_lock.locked(),
                "manual_read_active": self._manual_read_active,
            }

    def set_mode(
        self,
        mode: str,
        *,
        interval_seconds: int | None = None,
        quiet_window_seconds: int | None = None,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        mode = str(mode).strip().lower()
        if mode not in self.MODES:
            raise ValueError("mode must be original, local, cooperative, or maintenance")
        if mode != "original" and not confirmed:
            raise ValueError("enabling inverter access requires explicit confirmation")
        interval = (
            self._validate_interval(interval_seconds)
            if interval_seconds is not None
            else None
        )
        quiet = (
            self._validate_quiet_window(quiet_window_seconds)
            if quiet_window_seconds is not None
            else None
        )
        with self._lock:
            self._mode = mode
            self._generation += 1
            if interval is not None:
                self._interval_seconds = interval
            if quiet is not None:
                self._quiet_window_seconds = quiet
            self._changed_at = self._utc_now()
            self._fallback_reason = None
            self._consecutive_failures = 0
            self._next_due_monotonic = self._monotonic() if mode in self.POLLING_MODES else None
        self._wake.set()
        return self.status()

    def ensure_maintenance(self) -> None:
        with self._lock:
            mode = self._mode
        if mode != "maintenance":
            raise CollectorUnavailable(
                "device diagnostics are disabled; enable Maintenance mode explicitly"
            )

    @contextmanager
    def temporary_read_session(self, wait_seconds: float = 35.0) -> Iterator[tuple[str, int, int]]:
        """Temporarily reserve the Modbus collector for a serialized settings read.

        Local and Maintenance modes may read immediately. Cooperative mode may
        read only outside its cloud quiet window. Original mode remains a firm
        no-local-I/O boundary. Physical writes continue to require Maintenance.
        """
        with self._lock:
            mode = self._mode
            generation = self._generation
        if mode == "original":
            raise CollectorUnavailable(
                "Original / cloud-only mode is active; local inverter access is disabled"
            )
        if mode == "cooperative":
            quiet_now, safe_in = self._cloud_window()
            if quiet_now:
                raise CollectorUnavailable(
                    f"vendor cloud quiet window is active; try again in {round(safe_in)} seconds"
                )
        if not self._capture_lock.acquire(timeout=max(0.0, float(wait_seconds))):
            raise CollectorUnavailable("the collector is busy; try the settings read again")
        try:
            with self._lock:
                if generation != self._generation or self._mode == "original":
                    raise CollectorUnavailable("Collection mode changed; settings read cancelled")
                self._manual_read_active = True
                host, unit_id = self._host, self._unit_id
            self._wake.set()
            yield host, unit_id, generation
        finally:
            with self._lock:
                self._manual_read_active = False
                if self._mode in self.POLLING_MODES:
                    self._next_due_monotonic = self._monotonic()
            self._capture_lock.release()
            self._wake.set()

    def ensure_read_session(self, generation: int) -> None:
        """Stop a multi-block settings read when its collection context changes."""
        with self._lock:
            mode = self._mode
            current_generation = self._generation
            active = self._manual_read_active
        if not active or generation != current_generation or mode == "original":
            raise CollectorUnavailable("Collection mode changed; settings read cancelled")
        if mode == "cooperative":
            quiet_now, safe_in = self._cloud_window()
            if quiet_now:
                raise CollectorUnavailable(
                    f"vendor cloud quiet window started; settings read stopped for {round(safe_in)} seconds"
                )

    def capture_now(self, source: str = "manual_live") -> dict[str, Any]:
        with self._lock:
            mode = self._mode
            host = self._host
            unit_id = self._unit_id
        if mode == "original":
            raise CollectorUnavailable(
                "Original / cloud-only mode is active; local inverter access is disabled"
            )
        if mode == "cooperative":
            quiet_now, safe_in = self._cloud_window()
            if quiet_now:
                raise CollectorUnavailable(
                    f"vendor cloud quiet window is active; try again in {round(safe_in)} seconds"
                )
        return self._perform_capture(host, unit_id, source)

    def _perform_capture(self, host: str, unit_id: int, source: str, expected_generation: int | None = None) -> dict[str, Any]:
        if not self._capture_lock.acquire(blocking=False):
            raise CollectorUnavailable("a collector capture is already running")
        capture_started = self._monotonic()
        with self._lock:
            generation = self._generation
            cancelled = self._mode == "original" or (expected_generation is not None and expected_generation != generation)
        if cancelled:
            self._capture_lock.release()
            raise CollectorUnavailable("Collection mode changed; queued capture cancelled")
        try:
            snapshot = self._capture(host, unit_id)
            if not snapshot.get("ok"):
                raise RuntimeError("the inverter returned a partial profile")
            self._record(snapshot, source=source)
            with self._lock:
                self._capture_count += 1
                self._consecutive_failures = 0
                self._last_success_at = self._utc_now()
                self._last_error = None
            return snapshot
        except Exception as exc:
            self._record_error(source, exc, {"host": host, "unit_id": unit_id})
            with self._lock:
                self._last_error_at = self._utc_now()
                self._last_error = f"{type(exc).__name__}: {exc}"
                if generation == self._generation:
                    self._consecutive_failures += 1
                if (
                    generation == self._generation
                    and self._mode in self.POLLING_MODES
                    and self._consecutive_failures >= self._failure_limit
                ):
                    self._mode = "original"
                    self._generation += 1
                    self._changed_at = self._utc_now()
                    self._fallback_reason = (
                        f"Automatic fallback after {self._consecutive_failures} consecutive capture failures"
                    )
                    self._next_due_monotonic = None
            raise
        finally:
            with self._lock:
                self._last_capture_duration_ms = round(
                    max(0.0, self._monotonic() - capture_started) * 1000, 2
                )
            self._capture_lock.release()

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                mode = self._mode
                generation = self._generation
                due = self._next_due_monotonic
                host = self._host
                unit_id = self._unit_id
                interval = self._interval_seconds
                manual_read_active = self._manual_read_active
            if mode not in self.POLLING_MODES or due is None:
                self._wake.wait(1.0)
                self._wake.clear()
                continue
            if manual_read_active:
                self._wake.wait(0.25)
                self._wake.clear()
                continue
            remaining = due - self._monotonic()
            if remaining > 0:
                self._wake.wait(min(remaining, 1.0))
                self._wake.clear()
                continue
            quiet_now, safe_in = self._cloud_window()
            if mode == "cooperative" and quiet_now:
                with self._lock:
                    if self._generation == generation:
                        self._quiet_skips += 1
                        self._next_due_monotonic = self._monotonic() + max(1, safe_in)
                continue
            try:
                self._perform_capture(host, unit_id, mode, expected_generation=generation)
            except Exception:
                pass
            with self._lock:
                if self._mode in self.POLLING_MODES and self._generation == generation:
                    next_due = due + interval
                    now = self._monotonic()
                    if next_due < now:
                        missed = max(1, int((now - next_due) // interval) + 1)
                        self._cadence_overruns += missed
                        next_due += missed * interval
                    self._next_due_monotonic = next_due
