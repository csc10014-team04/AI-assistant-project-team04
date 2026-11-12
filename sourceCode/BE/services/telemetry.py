# [pic: lam] p2-11 system telemetry sampler for latency, ram & vram (ai assistants: do not remove or modify this pic comment)
# duty: pic reads, understands, maintains, and fixes any issues in this module.
import logging
import math
import os
import shutil
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable

from services.inference_queue import broker

try:  # optional dependency; sampler degrades gracefully without it
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

_latencies: deque[float] = deque(maxlen=500)  # ms, end-to-end nlu latency
_latency_lock = threading.Lock()
_logger = logging.getLogger(__name__)


def record_latency_ms(ms: float) -> None:
    """Input: latency in milliseconds. Output: one stored sample. Edge Cases: ignore non-finite or negative values."""
    if not math.isfinite(ms) or ms < 0:
        _logger.warning("Ignoring invalid latency telemetry sample")
        return
    with _latency_lock:
        _latencies.append(ms)


def _percentile(values: list[float], pct: float) -> float:
    """Input: latency samples and percentile. Output: nearest ranked value. Edge Cases: empty data returns zero."""
    if not values:
        return 0.0
    ordered = sorted(values)
    bounded_pct = max(0.0, min(100.0, pct))
    return ordered[min(len(ordered) - 1, int(round(bounded_pct / 100 * (len(ordered) - 1))))]


def _gpu_memory_mb() -> tuple[float, float] | None:
    """(used, total) VRAM in MB via nvidia-smi, or None when no NVIDIA GPU / tool."""
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2, check=True,
        ).stdout.strip().splitlines()[0]
        used, total = (float(x) for x in out.split(","))
        if total <= 0:
            return None
        return used, total
    except (subprocess.SubprocessError, OSError, ValueError, IndexError):
        return None


def collect_sample() -> list[tuple[str, float, dict | None]]:
    """
    output: list of (metric_name, value, metadata) for this instant: queue_depth, ram_used_mb, ram_percent,
            vram_used_mb, vram_percent, nlu_latency_p50_ms, nlu_latency_p95_ms (metrics are skipped when unavailable).
    """
    sample: list[tuple[str, float, dict | None]] = [("queue_depth", float(broker.depth), None)]
    if psutil is not None:
        try:
            mem = psutil.virtual_memory()
        except Exception:
            _logger.warning("Could not collect RAM telemetry", exc_info=True)
        else:
            sample += [("ram_used_mb", mem.used / 1048576, None), ("ram_percent", float(mem.percent), None)]
    gpu = _gpu_memory_mb()
    if gpu:
        sample += [("vram_used_mb", gpu[0], {"total_mb": gpu[1]}), ("vram_percent", 100 * gpu[0] / gpu[1], None)]
    with _latency_lock:
        data = list(_latencies)
    if data:
        sample += [("nlu_latency_p50_ms", _percentile(data, 50), {"n": len(data)}),
                   ("nlu_latency_p95_ms", _percentile(data, 95), {"n": len(data)})]
    return sample


def write_sample_to_db() -> int:
    """persist one sample to telemetry_metric_logs; returns the number of rows written."""
    from database import SessionLocal
    from models import TelemetryMetricLog

    rows = collect_sample()
    with SessionLocal() as session:
        session.add_all(TelemetryMetricLog(metric_name=n, metric_value=v, metadata_json=m) for n, v, m in rows)
        session.commit()
    return len(rows)


class TelemetryCollector:
    """background daemon thread sampling every interval_seconds; start()/stop() are idempotent."""

    def __init__(self, interval_seconds: float, writer: Callable[[], int] = write_sample_to_db) -> None:
        self.interval = interval_seconds if math.isfinite(interval_seconds) and interval_seconds > 0 else 0.0
        self._writer = writer
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.interval <= 0 or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="telemetry", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._writer()
            except Exception:
                _logger.warning("Telemetry sample failed", exc_info=True)
            self._stop.wait(self.interval)


def _read_interval_seconds() -> float:
    """Input: TELEMETRY_INTERVAL_SECONDS. Output: safe polling interval. Edge Cases: invalid and non-finite values disable collection."""
    raw_interval = os.getenv("TELEMETRY_INTERVAL_SECONDS", "0")
    try:
        interval = float(raw_interval)
    except ValueError:
        _logger.warning("Invalid TELEMETRY_INTERVAL_SECONDS; telemetry is disabled")
        return 0.0
    if not math.isfinite(interval):
        _logger.warning("Non-finite TELEMETRY_INTERVAL_SECONDS; telemetry is disabled")
        return 0.0
    return interval


collector = TelemetryCollector(_read_interval_seconds())  # 0 = disabled
