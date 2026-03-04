# fogbed_iota/client/cli.py

"""
Wrapper Python para comandos IOTA CLI
Centraliza e simplifica operações CLI do IOTA
"""

import json
import re
import time
from typing import Dict, List, Optional, Any

from fogbed_iota.utils import get_logger
from fogbed_iota.client.exceptions import (
    IotaClientException,
    TransactionFailedException,
)

logger = get_logger("cli")


class IotaCLI:
    def __init__(self, container, network: str = "localnet"):
        self.container = container
        self.network = network
        self._verify_cli_available()
        logger.info(f"IotaCLI initialized for network: {network}")

    def _verify_cli_available(self) -> bool:
        try:
            result = self.container.cmd("which iota")
            if "iota" in result:
                return True
            logger.warning("⚠️ IOTA CLI not found in PATH")
            return False
        except Exception as e:
            logger.error(f"Failed to verify CLI: {e}")
            return False

    def _execute(self, command: str, timeout: int = 30, capture_json: bool = False):
        full_cmd = f"timeout {timeout} {command}"
        try:
            result = self.container.cmd(full_cmd)

            if ("error" in result.lower() or "failed" in result.lower()) and ("timeout" not in result.lower()):
                logger.warning(f"Command may have failed: {result[:250]}")

            if capture_json:
                m = re.search(r"\{.+\}", result, re.DOTALL)
                if m:
                    try:
                        return json.loads(m.group(0))
                    except json.JSONDecodeError:
                        return result

            return result
        except Exception as e:
            raise IotaClientException(f"CLI command failed: {e}")

    # -------- Wallet --------

    def get_active_address(self) -> Optional[str]:
        out = self._execute("iota client active-address")
        m = re.search(r"(0x[a-fA-F0-9]{64})", out)
        return m.group(1) if m else None

    def switch_address(self, address: str) -> bool:
        out = self._execute(f"iota client switch --address {address}")
        return ("switched" in out.lower()) or ("active" in out.lower())

    # -------- Gas / Coins --------

    def get_gas(self, address: Optional[str] = None) -> List[Dict[str, Any]]:
        cmd = "iota client gas"
        if address:
            cmd += f" {address}"
        out = self._execute(cmd)

        coins: List[Dict[str, Any]] = []
        for line in out.splitlines():
            if "0x" not in line:
                continue
            parts = [p.strip() for p in line.split("│") if p.strip()]
            if len(parts) < 2:
                continue

            coin_id = None
            balance = None
            for part in parts:
                if part.startswith("0x") and len(part) >= 10:
                    coin_id = part
                elif part.isdigit():
                    balance = int(part)

            if coin_id and balance is not None:
                coins.append({"object_id": coin_id, "balance": balance})

        return coins

    def get_reference_gas_price(self) -> int:
        # v1.15.0 não tem `gas-price`; o próprio CLI sugere `gas`
        out = self._execute("iota client gas")
        m = re.search(r"(\d+)", out)
        return int(m.group(1)) if m else 1000

    # -------- Objects --------

    def get_object(self, object_id: str) -> Dict[str, Any]:
        out = self._execute(f"iota client object {object_id}")
        if out.strip().startswith("{"):
            try:
                return json.loads(out)
            except Exception:
                pass
        return {"object_id": object_id, "raw": out}

    def get_objects(self, address: Optional[str] = None) -> List[Dict[str, Any]]:
        cmd = "iota client objects"
        if address:
            cmd += f" {address}"
        out = self._execute(cmd, timeout=60)

        objs: List[Dict[str, Any]] = []
        for line in out.splitlines():
            m = re.search(r"(0x[a-fA-F0-9]+)", line)
            if m:
                objs.append({"object_id": m.group(1), "raw_line": line.strip()})
        return objs

    # -------- Transfers (corrigido p/ 1.15) --------

    def transfer_object(
        self,
        to: str,
        object_id: str,
        gas_budget: int = 10_000_000,
        sender: Optional[str] = None,
    ) -> str:
        """
        `iota client transfer` transfere OBJETO (não valor).
        """
        cmd = f"iota client transfer --to {to} --object-id {object_id} --gas-budget {gas_budget}"

        original = None
        if sender:
            original = self.get_active_address()
            self.switch_address(sender)

        try:
            out = self._execute(cmd, timeout=60)
            m = re.search(r"Transaction Digest:\s*([A-Za-z0-9]+)", out)
            if not m:
                raise TransactionFailedException(f"transfer_object failed: {out[:400]}")
            return m.group(1)
        finally:
            if sender and original:
                self.switch_address(original)

    def pay_iota(
        self,
        to: str,
        amount: int,
        gas_budget: int = 10_000_000,
        sender: Optional[str] = None,
        input_coin: Optional[str] = None,
    ) -> str:
        """
        Envia IOTA (MIST) por valor: `iota client pay-iota`.
        """
        cmd = f"iota client pay-iota --recipients {to} --amounts {amount} --gas-budget {gas_budget}"
        if input_coin:
            cmd += f" --input-coins {input_coin}"

        original = None
        if sender:
            original = self.get_active_address()
            self.switch_address(sender)

        try:
            out = self._execute(cmd, timeout=90)
            m = re.search(r"Transaction Digest:\s*([A-Za-z0-9]+)", out)
            if not m:
                raise TransactionFailedException(f"pay_iota failed: {out[:500]}")
            return m.group(1)
        finally:
            if sender and original:
                self.switch_address(original)

    # -------- Faucet --------

    def faucet_request(self, address: Optional[str] = None, max_retries: int = 3) -> bool:
        target = address or self.get_active_address()
        if not target:
            return False

        for attempt in range(max_retries):
            out = self._execute(f"iota client faucet --address {target}", timeout=45)
            if "success" in out.lower() or "transferred" in out.lower():
                return True
            time.sleep(2)

        return False

    # -------- Move --------

    def move_build(self, package_path: str) -> bool:
        out = self._execute(f"iota move build --path {package_path}", timeout=120)
        return ("build successful" in out.lower()) or ("success" in out.lower())

    def publish_package(self, package_path: str, gas_budget: int = 100_000_000, sender: Optional[str] = None) -> Dict[str, Any]:
        cmd = f"iota client publish {package_path} --gas-budget {gas_budget}"

        original = None
        if sender:
            original = self.get_active_address()
            self.switch_address(sender)

        try:
            out = self._execute(cmd, timeout=180)
            data = {"raw": out}
            pm = re.search(r"Package ID:\s*(0x[a-fA-F0-9]+)", out)
            dm = re.search(r"Transaction Digest:\s*([A-Za-z0-9]+)", out)
            if pm:
                data["package_id"] = pm.group(1)
            if dm:
                data["digest"] = dm.group(1)
            return data
        finally:
            if sender and original:
                self.switch_address(original)

    def call_function(
        self,
        package: str,
        module: str,
        function: str,
        args: Optional[List[str]] = None,
        type_args: Optional[List[str]] = None,
        gas_budget: int = 10_000_000,
        sender: Optional[str] = None,
    ) -> Dict[str, Any]:
        cmd = f"iota client call --package {package} --module {module} --function {function}"

        if args:
            cmd += " --args " + " ".join(str(a) for a in args)
        if type_args:
            cmd += " --type-args " + " ".join(type_args)

        cmd += f" --gas-budget {gas_budget}"

        original = None
        if sender:
            original = self.get_active_address()
            self.switch_address(sender)

        try:
            out = self._execute(cmd, timeout=90)
            data = {"raw": out}
            dm = re.search(r"Transaction Digest:\s*([A-Za-z0-9]+)", out)
            if dm:
                data["digest"] = dm.group(1)
            if "Status : Success" in out or "Status: Success" in out:
                data["status"] = "success"
            elif "Status : Failure" in out or "Status: Failure" in out:
                data["status"] = "failure"
            return data
        finally:
            if sender and original:
                self.switch_address(original)

    def ensure_managed_address(self) -> str:
        out = self.run("iota client addresses")
        if "No managed addresses" in out:
            self.run("iota client new-address ed25519")
            out = self.run("iota client addresses")

        # parse do primeiro 0x...
        m = re.search(r"(0x[a-fA-F0-9]{64})", out)
        if not m:
            raise RuntimeError(f"Could not get managed address from:\n{out}")
        return m.group(1)
