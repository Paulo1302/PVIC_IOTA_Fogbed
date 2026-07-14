import os
import shlex
import subprocess
from typing import Any, Dict, List, Optional

from fogbed_iota.utils import get_logger
from fogbed_iota.utils.parser import extract_json_from_output, tx_looks_successful, tx_error

logger = get_logger("contracts.raw_executor")

class RawExecutor:
    """Helper to run raw docker commands for contracts when IotaCLI fails or is not available."""
    
    def __init__(self, client_container):
        self.client = client_container

    def resolve_container_id(self) -> str:
        try:
            cmd = f"docker ps --filter 'name={self.client.name}' --format '{{{{.ID}}}}'"
            container_id = subprocess.check_output(cmd, shell=True, text=True).strip()
            if container_id:
                return container_id
        except Exception:
            pass
        return f"mn.{self.client.name}"

    def extract_modules_from_build(self, package_path: str) -> List[str]:
        cmd = f"find {shlex.quote(package_path)}/build -name '*.mv' -exec basename {{}} .mv \\; 2>/dev/null || true"
        result = self.client.cmd(cmd)
        return [m.strip() for m in result.splitlines() if m.strip()]

    def run_raw_publish(
        self,
        package_path: str,
        sender: str,
        gas_budget: int,
        skip_dependency_verification: bool = False,
    ) -> Dict[str, Any]:
        cmd = (
            f"cd {shlex.quote(package_path)} && "
            f"iota client publish "
            f"--sender {shlex.quote(sender)} "
            f"--gas-budget {gas_budget} "
            f"--json"
        )

        if skip_dependency_verification:
            cmd += " --skip-dependency-verification"

        cmd += " 2>&1"

        logger.debug(f"Executing raw publish: {cmd}")
        raw = self.client.cmd(cmd)
        tx_result = extract_json_from_output(raw)

        if not tx_looks_successful(tx_result):
            raise RuntimeError(f"Publish transaction failed: {tx_error(tx_result) or tx_result}")

        return tx_result

    def run_raw_call(
        self,
        package_id: str,
        module: str,
        function: str,
        sender: str,
        gas_budget: int,
        type_args: Optional[List[str]] = None,
        args: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        cmd = (
            f"iota client call "
            f"--package {shlex.quote(package_id)} "
            f"--module {shlex.quote(module)} "
            f"--function {shlex.quote(function)} "
            f"--sender {shlex.quote(sender)} "
            f"--gas-budget {gas_budget} "
            f"--json"
        )

        for targ in type_args or []:
            cmd += f" --type-args {shlex.quote(targ)}"

        for arg in args or []:
            cmd += f" --args {shlex.quote(arg)}"

        cmd += " 2>&1"

        logger.debug(f"Executing raw call: {cmd}")
        raw = self.client.cmd(cmd)
        tx_result = extract_json_from_output(raw)

        if not tx_looks_successful(tx_result):
            raise RuntimeError(f"Transaction failed: {tx_error(tx_result) or tx_result}")

        return tx_result
