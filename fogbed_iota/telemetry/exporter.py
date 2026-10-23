"""Metrics aggregator, statistical analyzer, and CSV/JSON exporter.

Calculates quantiles (p50, p90, p95, p99), averages, and throughput rates,
and outputs structured reports for academic and experimental analysis.
"""

from __future__ import annotations

import csv
import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .docker_monitor import ContainerSample
from .prometheus_scraper import NodeMetricsSnapshot
from .rpc_client import RpcMeasurement

logger = logging.getLogger("fogbed_iota.telemetry.exporter")


def calculate_quantiles(values: Sequence[float]) -> Dict[str, float]:
    """Calculates min, max, mean, stddev, p50, p90, p95, p99 for a list of floats."""
    if not values:
        return {
            "count": 0,
            "min": 0.0,
            "p50": 0.0,
            "p90": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "max": 0.0,
            "mean": 0.0,
            "stddev": 0.0,
        }

    s = sorted(values)
    n = len(s)
    mean_val = sum(s) / n
    variance = sum((x - mean_val) ** 2 for x in s) / n if n > 1 else 0.0
    stddev_val = math.sqrt(variance)

    def _quantile(q: float) -> float:
        if n == 1:
            return s[0]
        pos = q * (n - 1)
        base = int(pos)
        rest = pos - base
        if base + 1 < n:
            return s[base] + rest * (s[base + 1] - s[base])
        return s[base]

    return {
        "count": n,
        "min": round(s[0], 3),
        "p50": round(_quantile(0.50), 3),
        "p90": round(_quantile(0.90), 3),
        "p95": round(_quantile(0.95), 3),
        "p99": round(_quantile(0.99), 3),
        "max": round(s[-1], 3),
        "mean": round(mean_val, 3),
        "stddev": round(stddev_val, 3),
    }


class TelemetryReport:
    """Consolidated telemetry results ready for serialization."""

    def __init__(
        self,
        metadata: Dict[str, Any],
        docker_samples: Sequence[ContainerSample],
        prometheus_snapshots: Sequence[NodeMetricsSnapshot],
        rpc_measurements: Sequence[RpcMeasurement],
    ) -> None:
        self.metadata = metadata
        self.docker_samples = list(docker_samples)
        self.prometheus_snapshots = list(prometheus_snapshots)
        self.rpc_measurements = list(rpc_measurements)

    def summary(self) -> Dict[str, Any]:
        """Computes statistical summaries separating RPC queries from L1 transactions."""
        rpc_items = [m for m in self.rpc_measurements if m.category == "rpc"]
        tx_items = [m for m in self.rpc_measurements if m.category == "transaction"]

        # 1. RPC Read queries
        rpc_latencies = [m.latency_ms for m in rpc_items if m.success]
        rpc_stats = calculate_quantiles(rpc_latencies)
        rpc_success = sum(1 for m in rpc_items if m.success)
        rpc_total = len(rpc_items)
        if len(rpc_items) >= 2:
            dt_rpc = rpc_items[-1].timestamp - rpc_items[0].timestamp
            rpc_req_per_sec = round(rpc_success / dt_rpc, 2) if dt_rpc > 0 else 0.0
        else:
            rpc_req_per_sec = 0.0

        # 2. L1 Write Transactions (Confirmed tx/s & Finality)
        tx_latencies = [m.latency_ms for m in tx_items if m.success]
        tx_stats = calculate_quantiles(tx_latencies)
        tx_finalities = [m.finality_ms for m in tx_items if m.success and m.finality_ms is not None]
        tx_finality_stats = calculate_quantiles(tx_finalities)
        tx_success = sum(1 for m in tx_items if m.success)
        tx_total = len(tx_items)
        if len(tx_items) >= 2:
            dt_tx = tx_items[-1].timestamp - tx_items[0].timestamp
            confirmed_tps = round(tx_success / dt_tx, 2) if dt_tx > 0 else 0.0
        else:
            confirmed_tps = 0.0

        # Docker CPU and Memory by container
        containers_stats: Dict[str, Any] = {}
        all_containers = sorted(set(s.container_name for s in self.docker_samples))
        for c in all_containers:
            c_samples = [s for s in self.docker_samples if s.container_name == c]
            cpus = [s.cpu_percent for s in c_samples]
            mems = [s.memory_used_mb for s in c_samples]
            containers_stats[c] = {
                "cpu_percent": calculate_quantiles(cpus),
                "memory_used_mb": calculate_quantiles(mems),
            }

        # BFT Consensus finality stats from Prometheus snapshots (fallback/node perspective)
        prom_bft_latencies = [
            s.tx_orchestrator_wait_for_finality_latency_avg_ms
            for s in self.prometheus_snapshots
            if s.tx_orchestrator_wait_for_finality_latency_avg_ms is not None
        ]
        prom_bft_stats = calculate_quantiles(prom_bft_latencies)

        # Throughput from Prometheus node snapshots (delta total_transaction_effects)
        node_tps = 0.0
        if len(self.prometheus_snapshots) >= 2:
            s_first = self.prometheus_snapshots[0]
            s_last = self.prometheus_snapshots[-1]
            dt = s_last.timestamp - s_first.timestamp
            if dt > 0 and s_last.total_transaction_effects is not None and s_first.total_transaction_effects is not None:
                d_eff = s_last.total_transaction_effects - s_first.total_transaction_effects
                node_tps = max(0.0, d_eff / dt)

        # Fallback to combined latency if no category set
        all_latencies = [m.latency_ms for m in self.rpc_measurements if m.success]

        return {
            "metadata": self.metadata,
            "e2e_latency_ms": calculate_quantiles(all_latencies),
            "rpc_queries": {
                "total": rpc_total,
                "success": rpc_success,
                "throughput_rpc_req_sec": rpc_req_per_sec,
                "latency_ms": rpc_stats,
            },
            "l1_transactions": {
                "total": tx_total,
                "confirmed": tx_success,
                "failed": tx_total - tx_success,
                "confirmed_tps": confirmed_tps,
                "e2e_latency_ms": tx_stats,
                "bft_finality_ms": tx_finality_stats,
            },
            "throughput": {
                "avg_tps": round(node_tps, 2),
                "confirmed_tps": confirmed_tps,
                "rpc_req_sec": rpc_req_per_sec,
            },
            "bft_finality_ms": tx_finality_stats if tx_finalities else prom_bft_stats,
            "resource_usage": containers_stats,
            "rpc_calls_total": len(self.rpc_measurements),
            "rpc_calls_success": sum(1 for m in self.rpc_measurements if m.success),
        }

    def export_json(self, output_path: Path) -> Path:
        """Exports the full telemetry report and timeseries to a JSON file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "summary": self.summary(),
            "timeseries": {
                "docker": [s.to_dict() for s in self.docker_samples],
                "prometheus": [s.to_dict() for s in self.prometheus_snapshots],
                "rpc": [m.to_dict() for m in self.rpc_measurements],
            },
        }
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("Exported telemetry JSON report to: %s", output_path)
        return output_path

    def export_csvs(self, output_dir: Path) -> List[Path]:
        """Exports separate CSV files for resources, transactions, and Prometheus snapshots."""
        output_dir.mkdir(parents=True, exist_ok=True)
        exported: List[Path] = []

        # 1. Resources CSV
        p_res = output_dir / "timeseries_resources.csv"
        with open(p_res, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "timestamp", "container", "cpu_percent", "memory_used_mb",
                "memory_limit_mb", "memory_percent", "net_rx_bytes", "net_tx_bytes",
                "block_read_bytes", "block_write_bytes", "pids",
            ])
            for s in self.docker_samples:
                w.writerow([
                    f"{s.timestamp:.3f}", s.container_name, f"{s.cpu_percent:.2f}",
                    f"{s.memory_used_mb:.2f}", f"{s.memory_limit_mb:.2f}", f"{s.memory_percent:.2f}",
                    f"{s.net_rx_bytes:.0f}", f"{s.net_tx_bytes:.0f}",
                    f"{s.block_read_bytes:.0f}", f"{s.block_write_bytes:.0f}", s.pids,
                ])
        exported.append(p_res)

        # 2. Transactions & RPC CSV
        p_rpc = output_dir / "transactions_e2e.csv"
        with open(p_rpc, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "category", "method", "digest", "latency_ms", "finality_ms", "success", "error"])
            for m in self.rpc_measurements:
                w.writerow([
                    f"{m.timestamp:.3f}", m.category, m.method, m.digest or "",
                    f"{m.latency_ms:.3f}", f"{m.finality_ms:.3f}" if m.finality_ms is not None else "",
                    m.success, m.error or "",
                ])
        exported.append(p_rpc)

        # 3. Prometheus Node Snapshots CSV
        p_prom = output_dir / "prometheus_nodes.csv"
        with open(p_prom, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "timestamp", "endpoint", "total_transaction_effects", "total_transaction_certificates",
                "execution_driver_executed_transactions", "last_executed_checkpoint",
                "tx_orchestrator_request_latency_avg_ms", "tx_orchestrator_wait_for_finality_latency_avg_ms",
                "checkpoint_exec_latency_avg_ms", "consensus_leader_round", "connected_peers", "uptime_seconds",
            ])
            for s in self.prometheus_snapshots:
                w.writerow([
                    f"{s.timestamp:.3f}", s.endpoint, s.total_transaction_effects, s.total_transaction_certificates,
                    s.execution_driver_executed_transactions, s.last_executed_checkpoint,
                    s.tx_orchestrator_request_latency_avg_ms, s.tx_orchestrator_wait_for_finality_latency_avg_ms,
                    s.checkpoint_exec_latency_avg_ms, s.consensus_leader_round, s.connected_peers, s.uptime_seconds,
                ])
        exported.append(p_prom)

        logger.info("Exported %d CSV reports to: %s", len(exported), output_dir)
        return exported

    def format_terminal_summary(self) -> str:
        """Renders an executive summary table for terminal logging."""
        summ = self.summary()
        rpc = summ["rpc_queries"]
        tx = summ["l1_transactions"]
        bft = summ["bft_finality_ms"]
        res = summ["resource_usage"]

        rpc_lat = rpc["latency_ms"]
        tx_lat = tx["e2e_latency_ms"]
        tx_bft = tx["bft_finality_ms"]

        lines = [
            "=" * 70,
            "             IOTA FOGBED - RELATÓRIO DE TELEMETRIA & MÉTRICAS",
            "=" * 70,
        ]

        # 1. RPC Read queries section
        if rpc["total"] > 0:
            lines.extend([
                "1. CONSULTAS RPC (Carga de Leitura):",
                f"  • Requisições : {rpc['success']} / {rpc['total']} com sucesso ({(rpc['success']/rpc['total']*100 if rpc['total'] else 0):.1f}%)",
                f"  • Vazão       : {rpc['throughput_rpc_req_sec']:.2f} RPC req/s",
                f"  • Latência Fim a Fim :",
                f"      Min : {rpc_lat['min']} ms | Média : {rpc_lat['mean']} ms | Max : {rpc_lat['max']} ms",
                f"      p50 : {rpc_lat['p50']} ms | p90 : {rpc_lat['p90']} ms | p95 : {rpc_lat['p95']} ms | p99 : {rpc_lat['p99']} ms",
                "-" * 70,
            ])

        # 2. L1 Write transactions section
        if tx["total"] > 0:
            lines.extend([
                "2. TRANSAÇÕES L1 / PTB (Carga de Escrita & Consenso Starfish):",
                f"  • Transações  : {tx['confirmed']} / {tx['total']} confirmadas ({(tx['confirmed']/tx['total']*100 if tx['total'] else 0):.1f}%)",
                f"  • Vazão (TPS) : {tx['confirmed_tps']:.2f} Confirmed tx/s",
                f"  • Latência de Confirmação :",
                f"      Min : {tx_lat['min']} ms | Média : {tx_lat['mean']} ms | Max : {tx_lat['max']} ms",
                f"      p50 : {tx_lat['p50']} ms | p90 : {tx_lat['p90']} ms | p95 : {tx_lat['p95']} ms | p99 : {tx_lat['p99']} ms",
                f"  • Finalidade BFT por Transação :",
                f"      p50 : {tx_bft['p50']} ms | p90 : {tx_bft['p90']} ms | p95 : {tx_bft['p95']} ms | Média : {tx_bft['mean']} ms",
                "-" * 70,
            ])
        elif bft["count"] > 0:
            lines.extend([
                "2. TEMPO DE CONSENSO BFT (Starfish Quorum Finality via Prometheus):",
                f"  p50 : {bft['p50']} ms | p95 : {bft['p95']} ms | Média : {bft['mean']} ms",
                "-" * 70,
            ])

        # 3. Resources section
        lines.append("3. CONSUMO DE RECURSOS POR CONTÊINER (Pico / Médio):")
        for name, data in res.items():
            cpu_p50 = data["cpu_percent"]["p50"]
            cpu_max = data["cpu_percent"]["max"]
            mem_p50 = data["memory_used_mb"]["p50"]
            mem_max = data["memory_used_mb"]["max"]
            lines.append(f"  • {name:<16}: CPU p50={cpu_p50:>5.1f}% (max {cpu_max:>5.1f}%) | RAM p50={mem_p50:>6.1f}MB (max {mem_max:>6.1f}MB)")
        lines.append("=" * 70)
        return "\n".join(lines)
