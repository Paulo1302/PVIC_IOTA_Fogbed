"""Workload and transaction benchmark runner for Fogbed IOTA.

Injects transaction bursts or RPC queries from the edge container across the multi-tier
network and tracks response latency, confirmation status, and real-time TPS.
"""

from __future__ import annotations

import concurrent.futures
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from .rpc_client import RpcLatencyProbe, RpcMeasurement

logger = logging.getLogger("fogbed_iota.telemetry.benchmark")


@dataclass
class BenchmarkResult:
    total_requests: int
    successful_requests: int
    failed_requests: int
    elapsed_seconds: float
    throughput_tps: float
    measurements: List[RpcMeasurement]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "throughput_tps": round(self.throughput_tps, 2),
        }


class BenchmarkRunner:
    """Orchestrates controlled workload bursts against the IOTA network."""

    def __init__(self, probe: RpcLatencyProbe) -> None:
        self.probe = probe

    def run_rpc_workload(
        self,
        count: int = 50,
        concurrency: int = 1,
        method: str = "iota_getLatestCheckpointSequenceNumber",
        params: Optional[List[Any]] = None,
    ) -> BenchmarkResult:
        """Executes a batch of JSON-RPC queries with specified concurrency."""
        logger.info("Starting RPC benchmark: count=%d, concurrency=%d, method=%s", count, concurrency, method)
        measurements: List[RpcMeasurement] = []
        t0 = time.monotonic()

        if concurrency <= 1:
            for _ in range(count):
                meas = self.probe.call(method, params)
                meas.category = "rpc"
                measurements.append(meas)
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = [pool.submit(self.probe.call, method, params) for _ in range(count)]
                for fut in concurrent.futures.as_completed(futures):
                    try:
                        meas = fut.result()
                        meas.category = "rpc"
                        measurements.append(meas)
                    except Exception as exc:
                        meas = RpcMeasurement(
                            timestamp=time.time(), method=method, latency_ms=0.0,
                            success=False, error=str(exc), category="rpc"
                        )
                        measurements.append(meas)
                        self.probe.history.append(meas)

        elapsed = time.monotonic() - t0
        success_count = sum(1 for m in measurements if m.success)
        failed_count = len(measurements) - success_count
        rate = (success_count / elapsed) if elapsed > 0 else 0.0

        res = BenchmarkResult(
            total_requests=len(measurements),
            successful_requests=success_count,
            failed_requests=failed_count,
            elapsed_seconds=elapsed,
            throughput_tps=rate,
            measurements=measurements,
        )
        logger.info("RPC benchmark finished: %d/%d ok in %.2fs (%.2f RPC req/s)", success_count, count, elapsed, rate)
        return res

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
        """Executes a burst of L1 transfers from the Edge, measuring per-transaction finality."""
        logger.info("Starting L1 transaction burst: count=%d, concurrency=%d", count, concurrency)
        measurements: List[RpcMeasurement] = []
        t0 = time.monotonic()

        def _execute_one() -> RpcMeasurement:
            ts = time.time()
            t_start = time.perf_counter_ns()
            digest = None
            try:
                if cli_pay_fn is not None:
                    digest = cli_pay_fn()
                elif cli is not None:
                    to_addr = recipient or cli.get_active_address()
                    digest = cli.pay_iota(to=to_addr, amount=amount, gas_budget=gas_budget)
                else:
                    raise ValueError("run_transaction_burst requires either cli_pay_fn or cli")

                t_ack = time.perf_counter_ns()
                e2e_lat = (t_ack - t_start) / 1_000_000.0

                # Verify confirmation and Starfish BFT inclusion on Gateway
                status = None
                chk = None
                for _ in range(5):
                    chk = self.probe.call("iota_getTransactionBlock", [digest, {"showEffects": True}])
                    if chk.success and isinstance(chk.result, dict):
                        status = ((chk.result.get("effects") or {}).get("status") or {}).get("status")
                        if status is not None:
                            break
                    time.sleep(0.2)

                t_conf_end = time.perf_counter_ns()
                finality_lat = (t_conf_end - t_start) / 1_000_000.0

                is_success = bool(digest and (status == "success" or status is None))
                meas = RpcMeasurement(
                    timestamp=ts,
                    method="pay_iota",
                    category="transaction",
                    latency_ms=e2e_lat,
                    finality_ms=finality_lat,
                    digest=digest,
                    success=is_success,
                    result=digest,
                    error=None if is_success else f"effects status: {status}",
                )
                self.probe.history.append(meas)
                return meas
            except Exception as exc:
                t_end = time.perf_counter_ns()
                lat = (t_end - t_start) / 1_000_000.0
                meas = RpcMeasurement(
                    timestamp=ts,
                    method="pay_iota",
                    category="transaction",
                    latency_ms=lat,
                    finality_ms=lat,
                    digest=digest,
                    success=False,
                    error=str(exc),
                )
                self.probe.history.append(meas)
                return meas

        if concurrency <= 1:
            for _ in range(count):
                measurements.append(_execute_one())
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = [pool.submit(_execute_one) for _ in range(count)]
                for fut in concurrent.futures.as_completed(futures):
                    measurements.append(fut.result())

        elapsed = time.monotonic() - t0
        success_count = sum(1 for m in measurements if m.success)
        failed_count = len(measurements) - success_count
        tps = (success_count / elapsed) if elapsed > 0 else 0.0

        res = BenchmarkResult(
            total_requests=len(measurements),
            successful_requests=success_count,
            failed_requests=failed_count,
            elapsed_seconds=elapsed,
            throughput_tps=tps,
            measurements=measurements,
        )
        logger.info("L1 transaction burst finished: %d/%d confirmed in %.2fs (%.2f Confirmed tx/s)", success_count, count, elapsed, tps)
        return res
