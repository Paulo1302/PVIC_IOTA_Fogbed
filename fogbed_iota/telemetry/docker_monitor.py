"""Docker resource consumption monitor for Fogbed IOTA nodes.

Samples CPU %, Memory (MB, %), Network I/O, and Block I/O for emulated containers
periodically using the Docker Engine stats mechanism in a background daemon thread.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("fogbed_iota.telemetry.docker_monitor")

_UNIT_MULTIPLIERS = {
    "b": 1,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "tb": 1000**4,
}


def parse_bytes(val: str) -> float:
    """Parses a Docker stat human string (e.g. '876KiB', '15.41GiB', '0B') into bytes."""
    s = val.strip().lower()
    m = re.match(r"^([\d.]+)\s*([a-z]+)$", s)
    if not m:
        try:
            return float(s)
        except ValueError:
            return 0.0
    num = float(m.group(1))
    unit = m.group(2)
    mult = _UNIT_MULTIPLIERS.get(unit, 1)
    return num * mult


def parse_percentage(val: str) -> float:
    """Parses a percentage string like '12.34%' into float 12.34."""
    s = val.strip().rstrip("%").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_pair(val: str, delimiter: str = "/") -> Tuple[float, float]:
    """Parses 'X / Y' strings like '526B / 84B' into (x_bytes, y_bytes)."""
    parts = val.split(delimiter)
    if len(parts) == 2:
        return parse_bytes(parts[0]), parse_bytes(parts[1])
    return 0.0, 0.0


@dataclass
class ContainerSample:
    """A single snapshot of a container's resource usage at a given time."""

    timestamp: float
    container_name: str
    cpu_percent: float
    memory_used_mb: float
    memory_limit_mb: float
    memory_percent: float
    net_rx_bytes: float
    net_tx_bytes: float
    block_read_bytes: float
    block_write_bytes: float
    pids: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "container": self.container_name,
            "cpu_percent": self.cpu_percent,
            "memory_used_mb": round(self.memory_used_mb, 2),
            "memory_limit_mb": round(self.memory_limit_mb, 2),
            "memory_percent": round(self.memory_percent, 2),
            "net_rx_bytes": self.net_rx_bytes,
            "net_tx_bytes": self.net_tx_bytes,
            "block_read_bytes": self.block_read_bytes,
            "block_write_bytes": self.block_write_bytes,
            "pids": self.pids,
        }


def validate_containers(containers: Sequence[str]) -> List[str]:
    """Filters containers to those currently running in Docker, resolving mn. prefixes and checking PIDs."""
    valid: List[str] = []
    for c in containers:
        candidates = [c]
        if not c.startswith("mn."):
            candidates.append(f"mn.{c}")
        elif c.startswith("mn."):
            candidates.append(c[3:])

        found = None
        for cand in candidates:
            cmd = ["docker", "inspect", "-f", "{{.State.Running}}|{{.State.Pid}}|{{.Id}}", cand]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if proc.returncode == 0 and "true" in proc.stdout.lower():
                    parts = proc.stdout.strip().split("|")
                    pid = parts[1] if len(parts) > 1 else "?"
                    found = cand
                    logger.debug("Validated container %s (running=True, pid=%s)", cand, pid)
                    break
                else:
                    logger.debug("Container %s is not running (output=%s)", cand, proc.stdout.strip())
            except Exception as exc:
                logger.debug("Cannot inspect container %s: %s", cand, exc)

        if found:
            valid.append(found)
        else:
            valid.append(c)
    return valid


def default_docker_stats_executor(containers: Sequence[str], timeout: int = 5) -> str:
    """Invokes docker stats --no-stream --format '{{json .}}' <containers>."""
    if not containers:
        return ""
    cmd = ["docker", "stats", "--no-stream", "--format", "{{json .}}", *containers]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode == 0:
            return proc.stdout
        logger.warning("docker stats returned code %d: %s", proc.returncode, proc.stderr.strip())
        return ""
    except Exception as exc:
        logger.warning("failed to execute docker stats: %s", exc)
        return ""


class DockerMonitor:
    """Asynchronous background sampler for container resource metrics."""

    def __init__(
        self,
        containers: Sequence[str],
        interval_seconds: float = 0.5,
        executor: Optional[Callable[[Sequence[str]], str]] = None,
    ) -> None:
        self.containers = list(containers)
        self.interval = max(0.1, interval_seconds)
        self._executor = executor or default_docker_stats_executor
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._samples: List[ContainerSample] = []
        self._lock = threading.Lock()

    def start(self) -> None:
        """Starts background sampling thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        if self._executor == default_docker_stats_executor:
            self.containers = validate_containers(self.containers)
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="DockerMonitor", daemon=True)
        self._thread.start()
        logger.info("DockerMonitor started for containers: %s (interval=%.2fs)", self.containers, self.interval)

    def stop(self) -> None:
        """Stops the sampling thread and waits for termination."""
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=5.0)
        self._thread = None
        logger.info("DockerMonitor stopped. Total samples collected: %d", len(self._samples))

    def sample_now(self) -> List[ContainerSample]:
        """Performs a synchronous single sample of all monitored containers."""
        now = time.time()
        raw = self._executor(self.containers)
        if not raw:
            return []
        samples = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            name = data.get("Name") or data.get("Container") or ""
            cpu = parse_percentage(data.get("CPUPerc", "0%"))
            mem_used_b, mem_lim_b = parse_pair(data.get("MemUsage", "0B / 0B"))
            mem_pct = parse_percentage(data.get("MemPerc", "0%"))
            net_rx, net_tx = parse_pair(data.get("NetIO", "0B / 0B"))
            blk_r, blk_w = parse_pair(data.get("BlockIO", "0B / 0B"))
            try:
                pids = int(data.get("PIDs", 0))
            except ValueError:
                pids = 0

            sample = ContainerSample(
                timestamp=now,
                container_name=name,
                cpu_percent=cpu,
                memory_used_mb=mem_used_b / (1024 * 1024),
                memory_limit_mb=mem_lim_b / (1024 * 1024),
                memory_percent=mem_pct,
                net_rx_bytes=net_rx,
                net_tx_bytes=net_tx,
                block_read_bytes=blk_r,
                block_write_bytes=blk_w,
                pids=pids,
            )
            samples.append(sample)

        with self._lock:
            self._samples.extend(samples)
        return samples

    def _run(self) -> None:
        while not self._stop_event.is_set():
            start_t = time.monotonic()
            try:
                self.sample_now()
            except Exception as exc:
                logger.error("Exception during docker stats sampling: %s", exc)
            elapsed = time.monotonic() - start_t
            sleep_time = max(0.05, self.interval - elapsed)
            self._stop_event.wait(sleep_time)

    def get_samples(self) -> List[ContainerSample]:
        """Returns a copy of all collected samples."""
        with self._lock:
            return list(self._samples)

    def clear(self) -> None:
        """Clears all accumulated samples."""
        with self._lock:
            self._samples.clear()

    def __enter__(self) -> "DockerMonitor":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()
