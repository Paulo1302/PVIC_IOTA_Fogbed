"""Unit tests for the fogbed_iota.telemetry module."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from fogbed_iota.telemetry.benchmark import BenchmarkResult, BenchmarkRunner
from fogbed_iota.telemetry.docker_monitor import (
    ContainerSample,
    DockerMonitor,
    parse_bytes,
    parse_pair,
    parse_percentage,
)
from fogbed_iota.telemetry.exporter import TelemetryReport, calculate_quantiles
from fogbed_iota.telemetry.prometheus_scraper import (
    NodeMetricsSnapshot,
    PrometheusScraper,
    parse_prometheus_text,
)
from fogbed_iota.telemetry.rpc_client import RpcLatencyProbe, RpcMeasurement
from fogbed_iota.telemetry import TelemetrySession


SAMPLE_DOCKER_STATS = (
    '{"BlockIO":"10MB / 20MB","CPUPerc":"25.50%","Container":"mn.gateway",'
    '"ID":"caccf04a13fc","MemPerc":"2.50%","MemUsage":"512MiB / 16GiB","Name":"mn.gateway",'
    '"NetIO":"1.5MB / 2.5MB","PIDs":"12"}\n'
    '{"BlockIO":"0B / 0B","CPUPerc":"45.00%","Container":"mn.iota1",'
    '"ID":"ab1234567890","MemPerc":"3.20%","MemUsage":"600MiB / 16GiB","Name":"mn.iota1",'
    '"NetIO":"500KiB / 800KiB","PIDs":"15"}\n'
)

SAMPLE_PROMETHEUS_METRICS = """# HELP total_transaction_effects Total number of transaction effects produced
# TYPE total_transaction_effects counter
total_transaction_effects 15420
# HELP total_transaction_certificates Total number of transaction certificates handled
# TYPE total_transaction_certificates counter
total_transaction_certificates 15410
# HELP last_executed_checkpoint Last executed checkpoint
# TYPE last_executed_checkpoint gauge
last_executed_checkpoint 120
# HELP last_executed_checkpoint_timestamp_ms Last executed checkpoint timestamp ms
# TYPE last_executed_checkpoint_timestamp_ms gauge
last_executed_checkpoint_timestamp_ms 1792780000000
# HELP tx_orchestrator_request_latency Time spent in processing one Transaction Orchestrator request
# TYPE tx_orchestrator_request_latency histogram
tx_orchestrator_request_latency_sum 12.5
tx_orchestrator_request_latency_count 100
# HELP tx_orchestrator_wait_for_finality_latency Time spent in waiting for one Transaction Orchestrator request gets finalized
# TYPE tx_orchestrator_wait_for_finality_latency histogram
tx_orchestrator_wait_for_finality_latency_sum 3.5
tx_orchestrator_wait_for_finality_latency_count 100
# HELP iota_network_peers The number of connected peers.
# TYPE iota_network_peers gauge
iota_network_peers 4
# HELP uptime uptime of the node service in seconds
# TYPE uptime counter
uptime 3600
"""


class TestDockerMonitor(unittest.TestCase):
    def test_parse_helpers(self):
        self.assertEqual(parse_bytes("1024B"), 1024.0)
        self.assertEqual(parse_bytes("1KiB"), 1024.0)
        self.assertEqual(parse_bytes("2MiB"), 2 * 1024 * 1024.0)
        self.assertEqual(parse_bytes("1GiB"), 1024 * 1024 * 1024.0)
        self.assertEqual(parse_bytes("invalid"), 0.0)

        self.assertEqual(parse_percentage("12.5%"), 12.5)
        self.assertEqual(parse_percentage("0.0%"), 0.0)
        self.assertEqual(parse_percentage("invalid"), 0.0)

        r, w = parse_pair("512MiB / 16GiB")
        self.assertEqual(r, 512 * 1024 * 1024.0)
        self.assertEqual(w, 16 * 1024 * 1024 * 1024.0)

    def test_sample_now_parses_json(self):
        def fake_exec(containers):
            return SAMPLE_DOCKER_STATS

        monitor = DockerMonitor(containers=["mn.gateway", "mn.iota1"], executor=fake_exec)
        samples = monitor.sample_now()
        self.assertEqual(len(samples), 2)

        gw = [s for s in samples if s.container_name == "mn.gateway"][0]
        self.assertEqual(gw.cpu_percent, 25.50)
        self.assertEqual(gw.memory_used_mb, 512.0)
        self.assertEqual(gw.memory_percent, 2.50)
        self.assertEqual(gw.pids, 12)

        iota1 = [s for s in samples if s.container_name == "mn.iota1"][0]
        self.assertEqual(iota1.cpu_percent, 45.00)
        self.assertEqual(iota1.memory_used_mb, 600.0)

    def test_monitor_lifecycle(self):
        monitor = DockerMonitor(containers=["c1"], interval_seconds=0.2, executor=lambda c: SAMPLE_DOCKER_STATS)
        with monitor:
            self.assertTrue(monitor._thread.is_alive())
        self.assertFalse(monitor._thread is not None and monitor._thread.is_alive())
        self.assertGreaterEqual(len(monitor.get_samples()), 1)


class TestPrometheusScraper(unittest.TestCase):
    def test_parse_prometheus_text(self):
        families = parse_prometheus_text(SAMPLE_PROMETHEUS_METRICS)
        self.assertIn("total_transaction_effects", families)
        self.assertEqual(families["total_transaction_effects"].scalar_value(), 15420.0)
        self.assertIn("last_executed_checkpoint", families)
        self.assertEqual(families["last_executed_checkpoint"].scalar_value(), 120.0)

    def test_scraper_snapshot(self):
        scraper = PrometheusScraper(
            endpoints=["http://fake:9184/metrics"],
            fetcher=lambda u: SAMPLE_PROMETHEUS_METRICS,
        )
        snap = scraper.scrape_endpoint("http://fake:9184/metrics")
        self.assertIsNotNone(snap)
        self.assertEqual(snap.total_transaction_effects, 15420.0)
        self.assertEqual(snap.last_executed_checkpoint, 120)
        self.assertEqual(snap.connected_peers, 4)
        self.assertEqual(snap.uptime_seconds, 3600.0)
        # 12.5s / 100 count = 0.125s = 125.0 ms
        self.assertEqual(snap.tx_orchestrator_request_latency_avg_ms, 125.0)
        # 3.5s / 100 count = 0.035s = 35.0 ms
        self.assertEqual(snap.tx_orchestrator_wait_for_finality_latency_avg_ms, 35.0)


class TestRpcLatencyProbe(unittest.TestCase):
    def test_rpc_success(self):
        def fake_transport(url, payload, timeout):
            return 200, json.dumps({"jsonrpc": "2.0", "result": "test_chain_id", "id": 1})

        probe = RpcLatencyProbe("http://127.0.0.1:9000", transport=fake_transport)
        res = probe.call("iota_getChainIdentifier")
        self.assertTrue(res.success)
        self.assertEqual(res.result, "test_chain_id")
        self.assertGreater(res.latency_ms, 0.0)
        self.assertEqual(probe.get_chain_identifier(), "test_chain_id")

    def test_rpc_error(self):
        def fake_transport(url, payload, timeout):
            return 200, json.dumps({"jsonrpc": "2.0", "error": {"code": -32601, "message": "Method not found"}, "id": 1})

        probe = RpcLatencyProbe("http://127.0.0.1:9000", transport=fake_transport)
        res = probe.call("unknown_method")
        self.assertFalse(res.success)
        self.assertIn("Method not found", res.error)


class TestExporter(unittest.TestCase):
    def test_calculate_quantiles(self):
        empty = calculate_quantiles([])
        self.assertEqual(empty["count"], 0)
        self.assertEqual(empty["p50"], 0.0)

        vals = [10.0, 20.0, 30.0, 40.0, 50.0]
        q = calculate_quantiles(vals)
        self.assertEqual(q["count"], 5)
        self.assertEqual(q["min"], 10.0)
        self.assertEqual(q["max"], 50.0)
        self.assertEqual(q["mean"], 30.0)
        self.assertEqual(q["p50"], 30.0)

    def test_telemetry_report_export(self):
        now = 1700000000.0
        doc_samples = [
            ContainerSample(
                timestamp=now, container_name="mn.gw", cpu_percent=20.0, memory_used_mb=300.0,
                memory_limit_mb=4000.0, memory_percent=7.5, net_rx_bytes=1000, net_tx_bytes=2000,
                block_read_bytes=0, block_write_bytes=500, pids=10,
            ),
            ContainerSample(
                timestamp=now + 1, container_name="mn.gw", cpu_percent=30.0, memory_used_mb=320.0,
                memory_limit_mb=4000.0, memory_percent=8.0, net_rx_bytes=2000, net_tx_bytes=4000,
                block_read_bytes=0, block_write_bytes=1000, pids=10,
            ),
        ]
        prom_snaps = [
            NodeMetricsSnapshot(timestamp=now, endpoint="ep1", total_transaction_effects=100.0),
            NodeMetricsSnapshot(timestamp=now + 2, endpoint="ep1", total_transaction_effects=120.0),
        ]
        rpc_meas = [
            RpcMeasurement(timestamp=now, method="test", latency_ms=150.0, success=True),
            RpcMeasurement(timestamp=now + 1, method="test", latency_ms=170.0, success=True),
        ]

        report = TelemetryReport(
            metadata={"test": "run1"},
            docker_samples=doc_samples,
            prometheus_snapshots=prom_snaps,
            rpc_measurements=rpc_meas,
        )

        summ = report.summary()
        self.assertEqual(summ["rpc_calls_total"], 2)
        self.assertEqual(summ["rpc_calls_success"], 2)
        self.assertEqual(summ["e2e_latency_ms"]["p50"], 160.0)
        self.assertEqual(summ["throughput"]["avg_tps"], 10.0)  # (120-100)/2 = 10 TPS
        self.assertEqual(summ["rpc_queries"]["total"], 2)
        self.assertEqual(summ["rpc_queries"]["throughput_rpc_req_sec"], 2.0)

        with tempfile.TemporaryDirectory() as td:
            out_p = Path(td)
            json_file = report.export_json(out_p / "rep.json")
            self.assertTrue(json_file.is_file())
            csv_files = report.export_csvs(out_p)
            self.assertEqual(len(csv_files), 3)
            for f in csv_files:
                self.assertTrue(f.is_file())

        text_summary = report.format_terminal_summary()
        self.assertIn("RELATÓRIO DE TELEMETRIA", text_summary)
        self.assertIn("CONSULTAS RPC", text_summary)


class TestBenchmarkRunner(unittest.TestCase):
    def test_run_rpc_workload(self):
        def fake_transport(url, payload, timeout):
            return 200, json.dumps({"jsonrpc": "2.0", "result": 42, "id": 1})

        probe = RpcLatencyProbe("http://127.0.0.1:9000", transport=fake_transport)
        runner = BenchmarkRunner(probe)
        res = runner.run_rpc_workload(count=10, concurrency=2)
        self.assertEqual(res.total_requests, 10)
        self.assertEqual(res.successful_requests, 10)
        self.assertEqual(res.failed_requests, 0)
        self.assertGreater(res.throughput_tps, 0.0)

    def test_run_transaction_burst(self):
        def fake_transport(url, payload, timeout):
            # iota_getTransactionBlock mock response with effects
            return 200, json.dumps({
                "jsonrpc": "2.0",
                "result": {
                    "digest": "5gXj...",
                    "effects": {"status": {"status": "success"}}
                },
                "id": 1
            })

        probe = RpcLatencyProbe("http://127.0.0.1:9000", transport=fake_transport)
        runner = BenchmarkRunner(probe)
        res = runner.run_transaction_burst(
            cli_pay_fn=lambda: "5gXjTxDigest123",
            count=5,
            concurrency=1,
        )
        self.assertEqual(res.total_requests, 5)
        self.assertEqual(res.successful_requests, 5)
        self.assertEqual(res.failed_requests, 0)
        tx_meas = [m for m in probe.history if m.category == "transaction"]
        self.assertEqual(len(tx_meas), 5)
        self.assertEqual(tx_meas[0].category, "transaction")
        self.assertIsNotNone(tx_meas[0].finality_ms)


class TestTelemetrySession(unittest.TestCase):
    def test_session_lifecycle_and_workload_kwargs(self):
        def fake_transport(url, payload, timeout):
            return 200, json.dumps({"jsonrpc": "2.0", "result": 100, "id": 1})

        with tempfile.TemporaryDirectory() as td:
            session = TelemetrySession(
                containers=["c1"],
                gateway_rpc="http://127.0.0.1:9000",
                output_dir=td,
            )
            session.rpc_probe._custom_transport = fake_transport
            session.docker_monitor._executor = lambda c: SAMPLE_DOCKER_STATS
            session.prometheus_scraper._fetcher = lambda u: SAMPLE_PROMETHEUS_METRICS

            with session:
                res = session.run_rpc_workload(count=5, concurrency=2, method="custom_method")
                self.assertEqual(res.total_requests, 5)
                self.assertEqual(res.successful_requests, 5)

            # Idempotent stop
            rep = session.stop()
            self.assertIsNotNone(rep)
            self.assertTrue((Path(td) / "telemetry_report.json").is_file())


if __name__ == "__main__":
    unittest.main()
