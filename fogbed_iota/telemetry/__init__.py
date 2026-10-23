"""Telemetry, performance metrics, and benchmarking system for Fogbed IOTA.

Captures End-to-End Latency, Throughput (TPS), BFT Consensus finality, and Container
resource consumption (CPU, RAM, I/O) on IOTA v1.33.1 multi-tier networks.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from .benchmark import BenchmarkResult, BenchmarkRunner
from .docker_monitor import ContainerSample, DockerMonitor
from .exporter import TelemetryReport, calculate_quantiles
from .prometheus_scraper import MetricFamily, NodeMetricsSnapshot, PrometheusScraper
from .rpc_client import RpcLatencyProbe, RpcMeasurement

logger = logging.getLogger("fogbed_iota.telemetry")


class TelemetrySession:
    """Unified session manager orchestrating Docker, Prometheus, and RPC telemetry.

    Example:
        with TelemetrySession(containers=["mn.gateway", "mn.iota1"], gateway_rpc="http://10.0.0.5:9000",
                              prometheus_endpoints=["http://localhost:9184/metrics"],
                              output_dir="results/run_1") as session:
            session.run_rpc_workload(count=50, concurrency=2)

        # Reports automatically generated in results/run_1/
    """

    def __init__(
        self,
        containers: Optional[Sequence[str]] = None,
        gateway_rpc: Optional[str] = None,
        prometheus_endpoints: Optional[Sequence[str]] = None,
        output_dir: Optional[Union[str, Path]] = None,
        sample_interval: float = 0.5,
        network: Optional[Any] = None,
        source_container: Optional[str] = None,
    ) -> None:
        self.output_dir = Path(output_dir or f"results/telemetry_{int(time.time())}")
        self.sample_interval = sample_interval

        # Normalize source container if provided (e.g. 'client' -> 'mn.client')
        self.source_container = (
            source_container
            if (not source_container or source_container.startswith("mn."))
            else f"mn.{source_container}"
        )

        # Auto-detect from IotaNetwork instance if provided
        c_names = list(containers) if containers else []
        rpc_url = gateway_rpc
        prom_urls = list(prometheus_endpoints) if prometheus_endpoints else []

        if network is not None:
            if not c_names:
                c_names = [f"mn.{s.name}" for s in network.node_specs.values()]
                if network.client_container is not None:
                    c_names.append(f"mn.{network.client_container.name}")
            if not rpc_url:
                # If querying from inside an edge container, route via internal Mininet IP
                if self.source_container:
                    rpc_url = network.get_rpc_url(host=False) or "http://10.0.0.5:9000"
                else:
                    rpc_url = network.get_rpc_url(host=True) or network.get_rpc_url(host=False) or "http://127.0.0.1:9000"
            if not prom_urls:
                m_url = network.get_metrics_url(host=True) or network.get_metrics_url(host=False)
                if m_url:
                    prom_urls.append(m_url)

        self.containers = c_names
        self.gateway_rpc = rpc_url or "http://127.0.0.1:9000"
        self.prometheus_endpoints = prom_urls or ["http://127.0.0.1:9184/metrics"]

        self.docker_monitor = DockerMonitor(self.containers, interval_seconds=self.sample_interval)
        self.prometheus_scraper = PrometheusScraper(self.prometheus_endpoints, interval_seconds=self.sample_interval)
        self.rpc_probe = RpcLatencyProbe(self.gateway_rpc, container_source=self.source_container)
        self.benchmark_runner = BenchmarkRunner(self.rpc_probe)
        self.start_time: float = 0.0
        self.end_time: float = 0.0
        self.report: Optional[TelemetryReport] = None

    def start(self) -> None:
        """Starts background monitoring."""
        self.start_time = time.time()
        self.docker_monitor.start()
        self.prometheus_scraper.start()
        logger.info("TelemetrySession started (output_dir: %s)", self.output_dir)

    def stop(self) -> TelemetryReport:
        """Stops background monitoring, builds final report, and writes artifacts."""
        if self.report is not None:
            return self.report

        self.end_time = time.time()
        self.docker_monitor.stop()
        self.prometheus_scraper.stop()

        meta = {
            "network": "iota-fogbed",
            "iota_version": "1.33.1-97b1057f8de0",
            "protocol_version": 37,
            "timestamp_start": self.start_time,
            "timestamp_end": self.end_time,
            "duration_seconds": round(self.end_time - self.start_time, 2),
            "containers": self.containers,
            "gateway_rpc": self.gateway_rpc,
            "prometheus_endpoints": self.prometheus_endpoints,
        }

        report = TelemetryReport(
            metadata=meta,
            docker_samples=self.docker_monitor.get_samples(),
            prometheus_snapshots=self.prometheus_scraper.get_snapshots(),
            rpc_measurements=self.rpc_probe.history,
        )

        # Export reports
        self.output_dir.mkdir(parents=True, exist_ok=True)
        report.export_json(self.output_dir / "telemetry_report.json")
        report.export_csvs(self.output_dir)
        self.report = report
        logger.info("TelemetrySession complete.\n%s", report.format_terminal_summary())
        return report

    def run_rpc_workload(
        self,
        count: int = 50,
        concurrency: int = 1,
        method: str = "iota_getLatestCheckpointSequenceNumber",
        params: Optional[List[Any]] = None,
        **kwargs: Any,
    ) -> BenchmarkResult:
        """Convenience wrapper for running RPC benchmarks."""
        return self.benchmark_runner.run_rpc_workload(
            count=count, concurrency=concurrency, method=method, params=params, **kwargs
        )

    def run_transaction_burst(
        self,
        cli_pay_fn: Optional[Callable[[], str]] = None,
        count: int = 20,
        concurrency: int = 1,
        cli: Optional[Any] = None,
        recipient: Optional[str] = None,
        amount: int = 1_000,
        gas_budget: int = 10_000_000,
    ) -> BenchmarkResult:
        """Convenience wrapper for running transaction bursts."""
        return self.benchmark_runner.run_transaction_burst(
            cli_pay_fn=cli_pay_fn,
            count=count,
            concurrency=concurrency,
            cli=cli,
            recipient=recipient,
            amount=amount,
            gas_budget=gas_budget,
        )

    def __enter__(self) -> "TelemetrySession":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()


__all__ = [
    "BenchmarkResult",
    "BenchmarkRunner",
    "ContainerSample",
    "DockerMonitor",
    "MetricFamily",
    "NodeMetricsSnapshot",
    "PrometheusScraper",
    "RpcLatencyProbe",
    "RpcMeasurement",
    "TelemetryReport",
    "TelemetrySession",
    "calculate_quantiles",
]
