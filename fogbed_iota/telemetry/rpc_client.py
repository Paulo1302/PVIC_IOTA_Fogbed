"""JSON-RPC client and End-to-End latency probe for Fogbed IOTA nodes.

Measures precise request/response latencies (in milliseconds) from either the host
or from inside an emulated edge container crossing the multi-tier switches.
"""

from __future__ import annotations

import json
import logging
import shlex
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("fogbed_iota.telemetry.rpc_client")


@dataclass
class RpcMeasurement:
    """Record of a single JSON-RPC execution or L1 transaction measurement."""

    timestamp: float
    method: str
    latency_ms: float
    success: bool
    result: Any = None
    error: Optional[str] = None
    category: str = "rpc"  # "rpc" (query) or "transaction" (write / PTB)
    finality_ms: Optional[float] = None
    digest: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "method": self.method,
            "category": self.category,
            "latency_ms": round(self.latency_ms, 3),
            "finality_ms": round(self.finality_ms, 3) if self.finality_ms is not None else None,
            "digest": self.digest,
            "success": self.success,
            "error": self.error,
        }


def default_http_poster(url: str, payload_bytes: bytes, timeout: float = 10.0) -> Tuple[int, str]:
    """Posts JSON payload via urllib and returns (status_code, response_body)."""
    req = urllib.request.Request(
        url,
        data=payload_bytes,
        headers={"Content-Type": "application/json", "User-Agent": "fogbed-rpc-probe/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return exc.code, body
    except Exception as exc:
        return 0, str(exc)


def container_curl_poster(container: str, url: str, payload_bytes: bytes, timeout: int = 10) -> Tuple[int, str]:
    """Executes curl inside a Mininet container crossing the emulated link hierarchy."""
    payload_str = payload_bytes.decode("utf-8", errors="replace")
    cmd = [
        "docker", "exec", container,
        "curl", "-s", "-m", str(timeout),
        "-X", "POST", url,
        "-H", "Content-Type: application/json",
        "-d", payload_str,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
        if proc.returncode == 0:
            return 200, proc.stdout
        return 0, proc.stderr or proc.stdout
    except Exception as exc:
        return 0, str(exc)


class RpcLatencyProbe:
    """Client for querying IOTA JSON-RPC and tracking End-to-End latency."""

    def __init__(
        self,
        rpc_url: str,
        container_source: Optional[str] = None,
        transport: Optional[Callable[[str, bytes, float], Tuple[int, str]]] = None,
    ) -> None:
        self.rpc_url = rpc_url
        self.container_source = container_source
        self._custom_transport = transport
        self.history: List[RpcMeasurement] = []

    def _post(self, payload: bytes, timeout: float = 10.0) -> Tuple[int, str]:
        if self._custom_transport is not None:
            return self._custom_transport(self.rpc_url, payload, timeout)
        if self.container_source:
            return container_curl_poster(self.container_source, self.rpc_url, payload, int(timeout))
        return default_http_poster(self.rpc_url, payload, timeout)

    def call(self, method: str, params: Optional[List[Any]] = None, timeout: float = 10.0) -> RpcMeasurement:
        """Executes a JSON-RPC method, measuring latency with nanosecond precision."""
        req_id = int(time.time() * 1000) % 1_000_000
        payload = json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or []}).encode("utf-8")

        t_start = time.perf_counter_ns()
        code, raw_resp = self._post(payload, timeout=timeout)
        t_end = time.perf_counter_ns()

        now = time.time()
        latency_ms = (t_end - t_start) / 1_000_000.0

        if code != 200 or not raw_resp:
            meas = RpcMeasurement(
                timestamp=now, method=method, latency_ms=latency_ms, success=False, error=f"HTTP {code}: {raw_resp[:120]}"
            )
            self.history.append(meas)
            return meas

        try:
            parsed = json.loads(raw_resp)
        except json.JSONDecodeError as exc:
            meas = RpcMeasurement(
                timestamp=now, method=method, latency_ms=latency_ms, success=False, error=f"JSON parse error: {exc}"
            )
            self.history.append(meas)
            return meas

        if "error" in parsed:
            err_msg = str(parsed["error"])
            meas = RpcMeasurement(timestamp=now, method=method, latency_ms=latency_ms, success=False, error=err_msg)
            self.history.append(meas)
            return meas

        result = parsed.get("result")
        meas = RpcMeasurement(timestamp=now, method=method, latency_ms=latency_ms, success=True, result=result)
        self.history.append(meas)
        return meas

    # Convenience wrappers
    def get_chain_identifier(self) -> Optional[str]:
        m = self.call("iota_getChainIdentifier")
        return str(m.result) if m.success and m.result else None

    def get_total_transaction_blocks(self) -> Optional[int]:
        m = self.call("iota_getTotalTransactionBlocks")
        if m.success and m.result is not None:
            try:
                return int(m.result)
            except ValueError:
                return None
        return None

    def get_latest_checkpoint_sequence_number(self) -> Optional[int]:
        m = self.call("iota_getLatestCheckpointSequenceNumber")
        if m.success and m.result is not None:
            try:
                return int(m.result)
            except ValueError:
                return None
        return None

    def get_checkpoint(self, checkpoint_id: int) -> Optional[Dict[str, Any]]:
        m = self.call("iota_getCheckpoint", [str(checkpoint_id)])
        return m.result if m.success and isinstance(m.result, dict) else None

    def clear(self) -> None:
        self.history.clear()
