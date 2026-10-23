"""Prometheus metrics scraper and parser for IOTA v1.33.1 nodes.

Fetches and extracts consensus, transaction, and checkpoint metrics exposed on port :9184.
Supports direct HTTP requests, docker exec curl fallbacks, and injectable fetchers.
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("fogbed_iota.telemetry.prometheus")

_METRIC_LINE_RE = re.compile(
    r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{([^}]*)\})?\s+([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|NaN|[+-]?Inf)\s*(?:\d+)?$"
)
_LABEL_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)=(?:"([^"\\]*(?:\\.[^"\\]*)*)"|([^,]+))')


@dataclass
class MetricFamily:
    name: str
    help_text: str = ""
    type_name: str = "untyped"
    samples: List[Tuple[Dict[str, str], float]] = field(default_factory=list)

    def scalar_value(self) -> Optional[float]:
        """Returns the scalar value if exactly one sample without labels, or the first sample value."""
        if not self.samples:
            return None
        return self.samples[0][1]

    def value_by_labels(self, labels: Dict[str, str]) -> Optional[float]:
        for lbls, val in self.samples:
            if all(lbls.get(k) == v for k, v in labels.items()):
                return val
        return None


def parse_prometheus_text(text: str) -> Dict[str, MetricFamily]:
    """Parses standard Prometheus text exposition format into MetricFamily objects."""
    families: Dict[str, MetricFamily] = {}
    current_help = ""
    current_type = "untyped"

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("# HELP "):
            parts = line[7:].split(None, 1)
            if parts:
                name = parts[0]
                current_help = parts[1] if len(parts) > 1 else ""
                if name not in families:
                    families[name] = MetricFamily(name=name, help_text=current_help)
                else:
                    families[name].help_text = current_help
            continue

        if line.startswith("# TYPE "):
            parts = line[7:].split()
            if len(parts) >= 2:
                name, current_type = parts[0], parts[1].lower()
                if name not in families:
                    families[name] = MetricFamily(name=name, type_name=current_type)
                else:
                    families[name].type_name = current_type
            continue

        if line.startswith("#"):
            continue

        m = _METRIC_LINE_RE.match(line)
        if not m:
            continue

        name, label_str, val_str = m.group(1), m.group(2), m.group(3)
        try:
            val = float(val_str)
        except ValueError:
            continue

        labels: Dict[str, str] = {}
        if label_str:
            for lm in _LABEL_RE.finditer(label_str):
                k = lm.group(1)
                v = lm.group(2) if lm.group(2) is not None else lm.group(3)
                labels[k] = v or ""

        # Store under exact metric line name
        if name not in families:
            families[name] = MetricFamily(name=name, help_text=current_help, type_name=current_type)
        families[name].samples.append((labels, val))

        # Also store under base family name if different (e.g. for histogram base)
        for suffix in ("_sum", "_count", "_total", "_bucket"):
            if name.endswith(suffix):
                base = name[:-len(suffix)]
                if base not in families:
                    families[base] = MetricFamily(name=base, help_text=current_help, type_name="histogram")
                m_labels = dict(labels)
                m_labels["__suffix__"] = suffix
                families[base].samples.append((m_labels, val))
                break

    return families


@dataclass
class NodeMetricsSnapshot:
    """Parsed high-level metrics for a specific node at a given timestamp."""

    timestamp: float
    endpoint: str
    total_transaction_effects: Optional[float] = None
    total_transaction_certificates: Optional[float] = None
    execution_driver_executed_transactions: Optional[float] = None
    last_executed_checkpoint: Optional[int] = None
    last_executed_checkpoint_timestamp_ms: Optional[int] = None
    checkpoint_exec_sync_tps: Optional[float] = None
    tx_orchestrator_request_latency_avg_ms: Optional[float] = None
    tx_orchestrator_wait_for_finality_latency_avg_ms: Optional[float] = None
    tx_orchestrator_local_execution_latency_avg_ms: Optional[float] = None
    tx_orchestrator_wait_for_finality_finished: Optional[float] = None
    checkpoint_exec_latency_avg_ms: Optional[float] = None
    consensus_leader_round: Optional[int] = None
    connected_peers: Optional[int] = None
    uptime_seconds: Optional[float] = None
    raw_families: Dict[str, MetricFamily] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "endpoint": self.endpoint,
            "total_transaction_effects": self.total_transaction_effects,
            "total_transaction_certificates": self.total_transaction_certificates,
            "execution_driver_executed_transactions": self.execution_driver_executed_transactions,
            "last_executed_checkpoint": self.last_executed_checkpoint,
            "last_executed_checkpoint_timestamp_ms": self.last_executed_checkpoint_timestamp_ms,
            "checkpoint_exec_sync_tps": self.checkpoint_exec_sync_tps,
            "tx_orchestrator_request_latency_avg_ms": self.tx_orchestrator_request_latency_avg_ms,
            "tx_orchestrator_wait_for_finality_latency_avg_ms": self.tx_orchestrator_wait_for_finality_latency_avg_ms,
            "tx_orchestrator_local_execution_latency_avg_ms": self.tx_orchestrator_local_execution_latency_avg_ms,
            "tx_orchestrator_wait_for_finality_finished": self.tx_orchestrator_wait_for_finality_finished,
            "checkpoint_exec_latency_avg_ms": self.checkpoint_exec_latency_avg_ms,
            "consensus_leader_round": self.consensus_leader_round,
            "connected_peers": self.connected_peers,
            "uptime_seconds": self.uptime_seconds,
        }


def default_http_fetcher(url: str, timeout: float = 3.0) -> str:
    """Fetches metrics text via standard HTTP GET."""
    req = urllib.request.Request(url, headers={"User-Agent": "fogbed-telemetry/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        logger.debug("default_http_fetcher failed for %s: %s", url, exc)
        return ""


def docker_exec_curl_fetcher(container: str, url: str, timeout: int = 5) -> str:
    """Fallback fetcher running curl inside a Mininet container."""
    cmd = ["docker", "exec", container, "curl", "-s", "-m", str(timeout), url]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
        if proc.returncode == 0:
            return proc.stdout
        return ""
    except Exception as exc:
        logger.debug("docker_exec_curl_fetcher failed for %s: %s", container, exc)
        return ""


class PrometheusScraper:
    """Periodically scrapes Prometheus endpoints from IOTA nodes."""

    def __init__(
        self,
        endpoints: Sequence[str],
        interval_seconds: float = 1.0,
        fetcher: Optional[Callable[[str], str]] = None,
    ) -> None:
        self.endpoints = list(endpoints)
        self.interval = max(0.2, interval_seconds)
        self._fetcher = fetcher or default_http_fetcher
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._snapshots: List[NodeMetricsSnapshot] = []
        self._lock = threading.Lock()

    def scrape_endpoint(self, endpoint: str) -> Optional[NodeMetricsSnapshot]:
        now = time.time()
        text = self._fetcher(endpoint)
        if not text:
            return None
        families = parse_prometheus_text(text)

        def _val(name: str) -> Optional[float]:
            fam = families.get(name)
            return fam.scalar_value() if fam else None

        def _avg_latency_ms(name: str) -> Optional[float]:
            fam_sum = families.get(f"{name}_sum")
            fam_count = families.get(f"{name}_count")
            s_sum = fam_sum.scalar_value() if fam_sum else None
            s_count = fam_count.scalar_value() if fam_count else None
            if s_sum is not None and s_count is not None and s_count > 0:
                return round((s_sum / s_count) * 1000.0, 3)
            return None

        chk_raw = _val("last_executed_checkpoint")
        ts_raw = _val("last_executed_checkpoint_timestamp_ms")
        round_raw = _val("consensus_handler_leader_round")
        peers_raw = _val("iota_network_peers")

        snap = NodeMetricsSnapshot(
            timestamp=now,
            endpoint=endpoint,
            total_transaction_effects=_val("total_transaction_effects"),
            total_transaction_certificates=_val("total_transaction_certificates"),
            execution_driver_executed_transactions=_val("execution_driver_executed_transactions"),
            last_executed_checkpoint=int(chk_raw) if chk_raw is not None else None,
            last_executed_checkpoint_timestamp_ms=int(ts_raw) if ts_raw is not None else None,
            checkpoint_exec_sync_tps=_val("checkpoint_exec_sync_tps"),
            tx_orchestrator_request_latency_avg_ms=_avg_latency_ms("tx_orchestrator_request_latency"),
            tx_orchestrator_wait_for_finality_latency_avg_ms=_avg_latency_ms("tx_orchestrator_wait_for_finality_latency"),
            tx_orchestrator_local_execution_latency_avg_ms=_avg_latency_ms("tx_orchestrator_local_execution_latency"),
            tx_orchestrator_wait_for_finality_finished=_val("tx_orchestrator_wait_for_finality_finished"),
            checkpoint_exec_latency_avg_ms=_avg_latency_ms("checkpoint_exec_latency"),
            consensus_leader_round=int(round_raw) if round_raw is not None else None,
            connected_peers=int(peers_raw) if peers_raw is not None else None,
            uptime_seconds=_val("uptime"),
            raw_families=families,
        )

        with self._lock:
            self._snapshots.append(snap)
        return snap

    def sample_now(self) -> List[NodeMetricsSnapshot]:
        snaps = []
        for ep in self.endpoints:
            s = self.scrape_endpoint(ep)
            if s is not None:
                snaps.append(s)
        return snaps

    def _run(self) -> None:
        while not self._stop_event.is_set():
            t0 = time.monotonic()
            try:
                self.sample_now()
            except Exception as exc:
                logger.error("Exception in Prometheus scraping loop: %s", exc)
            elapsed = time.monotonic() - t0
            sleep_t = max(0.05, self.interval - elapsed)
            self._stop_event.wait(sleep_t)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="PrometheusScraper", daemon=True)
        self._thread.start()
        logger.info("PrometheusScraper started for endpoints: %s", self.endpoints)

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=5.0)
        self._thread = None
        logger.info("PrometheusScraper stopped. Total snapshots collected: %d", len(self._snapshots))

    def get_snapshots(self) -> List[NodeMetricsSnapshot]:
        with self._lock:
            return list(self._snapshots)

    def clear(self) -> None:
        with self._lock:
            self._snapshots.clear()

    def __enter__(self) -> "PrometheusScraper":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()
