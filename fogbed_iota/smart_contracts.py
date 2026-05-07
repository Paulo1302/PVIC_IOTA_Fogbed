# fogbed_iota/smart_contracts.py

"""
Smart Contract Manager for IOTA 1.15+ Move Packages.

Principais correcoes:
- parsing robusto de JSON contaminado por logs/ANSI
- publish_package com fallback raw quando o wrapper falha ou retorna payload incompleto
- call_function com fallback raw quando o wrapper retorna {} ou payload inconsistente
- uso explicito de sender nas transacoes raw
- extracao mais robusta de packageId / UpgradeCap / digest
- aliases de compatibilidade para codigo legado
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
from typing import Any, Dict, List, Optional

from fogbed_iota.utils import get_logger

logger = get_logger("smart_contracts")


def _strip_ansi(text: str) -> str:
    if not text:
        return ""
    ansi_pattern = r"\x1B\[[0-?]*[ -/]*[@-~]"
    return re.sub(ansi_pattern, "", text)


def _extract_json_from_output(output: str) -> Dict[str, Any]:
    output_clean = _strip_ansi(output)

    clean_lines: List[str] = []
    for line in output_clean.splitlines():
        stripped = line.strip()

        if re.match(r"^\d{4}-\d{2}-\d{2}T", stripped):
            continue
        if stripped.startswith(("[note]", "FETCHING", "Cloning", "Updating", "Compiling")):
            continue
        if stripped.startswith(("DEBUG", "INFO", "WARNING", "ERROR")):
            continue

        clean_lines.append(line)

    output_clean = "\n".join(clean_lines).strip()

    if output_clean.startswith("{") or output_clean.startswith("["):
        try:
            data = json.loads(output_clean)
            if isinstance(data, dict):
                return data
            raise ValueError(f"Expected JSON object, got {type(data).__name__}")
        except json.JSONDecodeError:
            pass

    decoder = json.JSONDecoder()
    for pos, ch in enumerate(output_clean):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(output_clean, pos)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue

    raise ValueError(
        "No JSON object found in CLI output.\n"
        f"Output preview: {output_clean[:800]}"
    )


def _tx_digest(tx: Dict[str, Any]) -> str:
    effects = tx.get("effects") or {}
    return tx.get("digest") or effects.get("transactionDigest") or "unknown"


def _tx_error(tx: Dict[str, Any]) -> Optional[str]:
    if not isinstance(tx, dict):
        return str(tx)

    if tx.get("error"):
        return str(tx["error"])

    effects = tx.get("effects") or {}
    status = effects.get("status") or {}

    if isinstance(status, dict) and status.get("error"):
        return str(status["error"])

    return None


def _tx_looks_successful(tx: Dict[str, Any]) -> bool:
    if not isinstance(tx, dict) or not tx:
        return False

    effects = tx.get("effects") or {}
    status = effects.get("status") or {}
    top_status = tx.get("status")
    error_msg = _tx_error(tx)

    if isinstance(status, dict):
        effects_status = status.get("status")
    else:
        effects_status = str(status) if status else ""

    digest = tx.get("digest") or effects.get("transactionDigest")

    return any(
        [
            top_status == "success",
            effects_status == "success",
            bool(tx.get("confirmedLocalExecution")),
            "objectChanges" in tx,
            "balanceChanges" in tx,
            bool(digest) and not error_msg,
        ]
    )


class MovePackage:
    """
    Represents a published Move package on IOTA blockchain.
    """

    def __init__(
        self,
        package_id: str,
        name: str,
        modules: List[str],
        digest: str,
        publisher: str,
        upgrade_cap_id: Optional[str] = None,
        version: int = 1,
    ):
        self.package_id = package_id
        self.name = name
        self.modules = modules
        self.digest = digest
        self.publisher = publisher
        self.upgrade_cap_id = upgrade_cap_id
        self.version = version
        self.deployed_at = time.time()

    def __repr__(self) -> str:
        upgradeable = f", upgradeable={bool(self.upgrade_cap_id)}" if self.upgrade_cap_id else ""
        return f"MovePackage(name='{self.name}', id='{self.package_id[:16]}...', v{self.version}{upgradeable})"

    def is_upgradeable(self) -> bool:
        return self.upgrade_cap_id is not None


class SmartContractManager:
    """
    Production-ready manager for Move smart contracts on IOTA 1.15+.
    """

    def __init__(self, cli_or_container, account_manager):
        from fogbed_iota.client.cli import IotaCLI

        if isinstance(cli_or_container, IotaCLI):
            self.cli = cli_or_container
            self.client = cli_or_container.container
        else:
            self.client = cli_or_container
            self.cli = None
            logger.warning(
                "SmartContractManager initialized with raw container. "
                "Consider passing IotaCLI for better integration."
            )

        self.accounts = account_manager
        self.deployed_packages: Dict[str, MovePackage] = {}
        self.contracts_dir = "/contracts"

        logger.info("SmartContractManager initialized")

    def _get_account(self, sender_alias: str):
        if hasattr(self.accounts, "get_account"):
            return self.accounts.get_account(sender_alias)
        raise AttributeError("Account manager does not provide get_account()")

    def _get_balance(self, sender_alias: str) -> int:
        if hasattr(self.accounts, "get_balance"):
            return int(self.accounts.get_balance(sender_alias))
        return 0

    def _resolve_container_id(self) -> str:
        try:
            cmd = f"docker ps --filter 'name={self.client.name}' --format '{{{{.ID}}}}'"
            container_id = subprocess.check_output(cmd, shell=True, text=True).strip()
            if container_id:
                return container_id
        except Exception:
            pass
        return f"mn.{self.client.name}"

    def _extract_modules_from_build(self, package_path: str) -> List[str]:
        cmd = f"find {shlex.quote(package_path)}/build -name '*.mv' -exec basename {{}} .mv \\; 2>/dev/null || true"
        result = self.client.cmd(cmd)
        return [m.strip() for m in result.splitlines() if m.strip()]

    def _extract_publish_metadata(
        self, tx_result: Dict[str, Any], package_path: str, publisher: str
    ) -> MovePackage:
        object_changes = tx_result.get("objectChanges", []) or []

        if not object_changes:
            raise RuntimeError(f"No objectChanges in transaction result: {tx_result}")

        published_changes = [c for c in object_changes if c.get("type") == "published"]
        if not published_changes:
            raise RuntimeError(
                "No 'published' objectChange found. "
                f"Changes: {[c.get('type') for c in object_changes]}"
            )

        package_change = published_changes[0]
        package_id = package_change.get("packageId")
        modules = package_change.get("modules", []) or []

        if not package_id:
            raise RuntimeError(f"packageId not found in published change: {package_change}")

        upgrade_cap_id = None
        for change in object_changes:
            if change.get("type") != "created":
                continue
            object_type = change.get("objectType", "") or ""
            if "package::UpgradeCap" in object_type:
                upgrade_cap_id = change.get("objectId")
                break

        digest = _tx_digest(tx_result)
        package_name = os.path.basename(package_path.rstrip("/"))

        move_pkg = MovePackage(
            package_id=package_id,
            name=package_name,
            modules=modules,
            digest=digest,
            publisher=publisher,
            upgrade_cap_id=upgrade_cap_id,
            version=1,
        )

        self.deployed_packages[package_name] = move_pkg
        return move_pkg

    def _run_raw_publish(
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
        tx_result = _extract_json_from_output(raw)

        if not _tx_looks_successful(tx_result):
            raise RuntimeError(f"Publish transaction failed: {_tx_error(tx_result) or tx_result}")

        return tx_result

    def _run_raw_call(
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
        tx_result = _extract_json_from_output(raw)

        if not _tx_looks_successful(tx_result):
            raise RuntimeError(f"Transaction failed: {_tx_error(tx_result) or tx_result}")

        return tx_result

    # ==================== Package Management ====================

    def copy_package_to_container(self, local_path: str, package_name: str, debug: bool = False) -> str:
        logger.info(f"Copying package '{package_name}' to container")

        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Local package path not found: {local_path}")

        move_toml = os.path.join(local_path, "Move.toml")
        if not os.path.exists(move_toml):
            raise FileNotFoundError(f"Move.toml not found in {local_path}")

        if debug:
            print(f"🔍 DEBUG: Local path: {local_path}")
            print(f"🔍 DEBUG: Move.toml exists: {os.path.exists(move_toml)}")
            print("🔍 DEBUG: Local files:")
            for root, _, files in os.walk(local_path):
                for file_name in files:
                    print(f"   - {os.path.join(root, file_name)}")

        container_path = f"{self.contracts_dir}/{package_name}"
        self.client.cmd(f"mkdir -p {shlex.quote(container_path)}")

        container_id = self._resolve_container_id()

        if debug:
            print(f"🔍 DEBUG: Container ID: {container_id}")
            print(f"🔍 DEBUG: Container path: {container_path}")

        tar_cmd = (
            f"tar -C {shlex.quote(local_path)} -cf - . | "
            f"docker exec -i {container_id} tar -C {shlex.quote(container_path)} -xf -"
        )

        if debug:
            print(f"🔍 DEBUG: Tar command: {tar_cmd}")

        tar_result = subprocess.run(tar_cmd, shell=True, check=False)
        if tar_result.returncode != 0:
            logger.warning(f"tar method failed with code {tar_result.returncode}, trying docker cp")

            cp_cmd = f"docker cp {shlex.quote(local_path)}/. {container_id}:{container_path}/"
            if debug:
                print(f"🔍 DEBUG: Docker cp command: {cp_cmd}")

            cp_result = subprocess.run(cp_cmd, shell=True, check=False)
            if cp_result.returncode != 0:
                raise RuntimeError(
                    "Failed to copy package "
                    f"(tar exit: {tar_result.returncode}, cp exit: {cp_result.returncode})"
                )

        verify_cmd = f"test -f {shlex.quote(container_path)}/Move.toml && echo 'OK' || echo 'MISSING'"
        verify_result = self.client.cmd(verify_cmd)

        if "MISSING" in verify_result:
            raise RuntimeError(
                f"Copy reported success but Move.toml not found in container at {container_path}"
            )

        logger.info(f"✅ Package copied to {container_path}")
        return container_path

    def build_package(self, package_path: str, debug: bool = False) -> Dict[str, Any]:
        logger.info(f"Building Move package: {package_path}")

        package_path = package_path.rstrip("/")
        move_toml_path = f"{package_path}/Move.toml"

        if debug:
            print(f"🔍 DEBUG: Normalized package_path: {package_path}")
            print(f"🔍 DEBUG: Move.toml path: {move_toml_path}")
            print("🔍 DEBUG: Listing package directory:")
            print(self.client.cmd(f"ls -la {shlex.quote(package_path)} || echo 'DIR_NOT_FOUND'"))

        check_cmd = f"test -f {shlex.quote(move_toml_path)} && echo 'OK' || echo 'NOT_FOUND'"
        raw_check = self.client.cmd(check_cmd)
        check = raw_check.strip()

        if debug:
            print(f"🔍 DEBUG: Move.toml check command: {check_cmd}")
            print(f"🔍 DEBUG: Raw check output: {raw_check!r}")
            print(f"🔍 DEBUG: Stripped check output: {check!r}")

        if "OK" not in check or "NOT_FOUND" in check:
            raise FileNotFoundError(
                f"Move.toml not found in {package_path}. "
                f"Ensure package structure is correct. (check result: {check!r})"
            )

        build_cmd = f"cd {shlex.quote(package_path)} && iota move build 2>&1"
        if debug:
            print(f"🔍 DEBUG: Build command: {build_cmd}")

        output = self.client.cmd(build_cmd)

        if debug:
            print(f"🔍 DEBUG: Build output:\n{output[:1000]}")

        status_cmd = (
            f"cd {shlex.quote(package_path)} && "
            f"iota move build >/dev/null 2>&1 && echo 'OK' || echo 'FAIL'"
        )
        raw_status = self.client.cmd(status_cmd)
        status = raw_status.strip()

        if debug:
            print(f"🔍 DEBUG: Build status raw: {raw_status!r}")
            print(f"🔍 DEBUG: Build status stripped: {status!r}")

        if "OK" not in status or "FAIL" in status:
            raise RuntimeError(f"Move build failed. Check package syntax.\n{output[:1000]}")

        modules = self._extract_modules_from_build(package_path)

        logger.info("✅ Build completed successfully")
        return {
            "success": True,
            "package_path": package_path,
            "build_path": f"{package_path}/build",
            "modules": modules,
            "output": output,
        }

    def publish_package(
        self,
        package_path: str,
        sender_alias: str,
        gas_budget: int = 100_000_000,
        skip_dependency_verification: bool = False,
    ) -> MovePackage:
        logger.info(f"📦 Publishing Move package: {os.path.basename(package_path)}")
        logger.info(f" Sender: {sender_alias}")
        logger.info(f" Gas budget: {gas_budget:,} MIST")

        account = self._get_account(sender_alias)
        if not account:
            available = list(getattr(self.accounts, "accounts", {}).keys())
            raise ValueError(f"Account '{sender_alias}' not found. Available: {available}")

        balance = 0
        if self.cli:
            try:
                coins = self.cli.get_gas(account.address)
                balance = sum(int(c.get("balance", 0)) for c in coins)
            except Exception:
                balance = self._get_balance(sender_alias)
        else:
            balance = self._get_balance(sender_alias)

        if balance and balance < gas_budget:
            raise RuntimeError(
                f"Insufficient balance for {sender_alias}. "
                f"Current: {balance:,} MIST ({balance/1e9:.4f} IOTA), "
                f"required: {gas_budget:,} MIST ({gas_budget/1e9:.4f} IOTA)."
            )

        tx_result: Optional[Dict[str, Any]] = None
        wrapper_error: Optional[Exception] = None

        if self.cli:
            try:
                logger.info("🚀 Publishing via IotaCLI...")
                result_raw = self.cli.publish_package(
                    package_path=package_path,
                    gas_budget=gas_budget,
                    sender=account.address,
                )

                if isinstance(result_raw, dict) and _tx_looks_successful(result_raw):
                    tx_result = result_raw
                elif isinstance(result_raw, dict) and result_raw:
                    logger.warning(f"IotaCLI.publish_package returned incomplete payload: {result_raw}")
                else:
                    logger.warning(f"IotaCLI.publish_package returned empty/non-dict payload: {result_raw}")

            except Exception as exc:
                wrapper_error = exc
                logger.warning(f"IotaCLI.publish_package failed: {exc}")

        if tx_result is None:
            if wrapper_error:
                logger.warning("Falling back to raw publish after wrapper exception")
            else:
                logger.warning("Falling back to raw publish after incomplete wrapper payload")

            tx_result = self._run_raw_publish(
                package_path=package_path,
                sender=account.address,
                gas_budget=gas_budget,
                skip_dependency_verification=skip_dependency_verification,
            )

        move_pkg = self._extract_publish_metadata(tx_result, package_path, account.address)

        logger.info("✅ Package published!")
        logger.info(f" Package ID: {move_pkg.package_id}")
        logger.info(f" Transaction: {move_pkg.digest}")
        logger.info(f" Modules: {', '.join(move_pkg.modules) if move_pkg.modules else 'N/A'}")
        logger.info(f" Upgradeable: {'Yes' if move_pkg.upgrade_cap_id else 'No'}")

        return move_pkg

    def call_function(
        self,
        package_id: str,
        module: str,
        function: str,
        sender_alias: str,
        type_args: Optional[List[str]] = None,
        args: Optional[List[str]] = None,
        gas_budget: int = 10_000_000,
    ) -> Dict[str, Any]:
        logger.info(f"📞 Calling: {package_id}::{module}::{function}")

        account = self._get_account(sender_alias)
        if not account:
            raise ValueError(f"Account '{sender_alias}' not found")

        result_raw: Optional[Dict[str, Any]] = None
        wrapper_error: Optional[Exception] = None

        if self.cli:
            try:
                result = self.cli.call_function(
                    package=package_id,
                    module=module,
                    function=function,
                    args=args,
                    type_args=type_args,
                    gas_budget=gas_budget,
                    sender=account.address,
                )

                if isinstance(result, dict) and _tx_looks_successful(result):
                    result_raw = result
                elif isinstance(result, dict):
                    logger.warning(
                        f"IotaCLI.call_function returned non-success payload: {result}"
                    )
                else:
                    logger.warning(
                        f"IotaCLI.call_function returned non-dict payload: {result}"
                    )

            except Exception as exc:
                wrapper_error = exc
                logger.warning(f"IotaCLI.call_function failed directly: {exc}")

        if result_raw is None:
            if wrapper_error:
                logger.warning("Retrying call via raw container command after wrapper exception")
            else:
                logger.warning("Retrying call via raw container command after empty/incomplete wrapper payload")

            result_raw = self._run_raw_call(
                package_id=package_id,
                module=module,
                function=function,
                sender=account.address,
                gas_budget=gas_budget,
                type_args=type_args,
                args=args,
            )

        logger.info(f"✅ Function executed: {_tx_digest(result_raw)}")
        return result_raw

    def get_object(self, object_id: str) -> Dict[str, Any]:
        logger.debug(f"Fetching object: {object_id}")

        if self.cli:
            try:
                result = self.cli.get_object(object_id)
                if isinstance(result, dict):
                    return result
            except Exception as exc:
                logger.warning(f"IotaCLI.get_object failed, using raw fallback: {exc}")

        cmd = f"iota client object {shlex.quote(object_id)} --json 2>&1"
        result = self.client.cmd(cmd)

        try:
            return _extract_json_from_output(result)
        except Exception:
            return {"object_id": object_id, "raw": result}

    def get_objects(self, address: Optional[str] = None) -> List[Dict[str, Any]]:
        if self.cli:
            try:
                result = self.cli.get_objects(address)
                if isinstance(result, list):
                    return result
            except Exception as exc:
                logger.warning(f"IotaCLI.get_objects failed, using raw fallback: {exc}")

        cmd = "iota client objects"
        if address:
            cmd += f" {shlex.quote(address)}"

        result = self.client.cmd(cmd)
        objs: List[Dict[str, Any]] = []

        for line in result.splitlines():
            match = re.search(r"(0x[a-fA-F0-9]+)", line)
            if match:
                objs.append({"object_id": match.group(1)})

        return objs

    # ==================== Package Registry ====================

    def get_package_info(self, package_name: str) -> Optional[MovePackage]:
        return self.deployed_packages.get(package_name)

    def list_deployed_packages(self) -> List[MovePackage]:
        """List all packages deployed in this session."""
        return list(self.deployed_packages.values())

    def get_package_by_id(self, package_id: str) -> Optional[MovePackage]:
        """Find a deployed package by its package ID."""
        for pkg in self.deployed_packages.values():
            if pkg.package_id == package_id:
                return pkg
        return None

    # ==================== Compatibility Aliases ====================

    def copyPackageToContainer(self, local_path: str, package_name: str, debug: bool = False) -> str:
        return self.copy_package_to_container(local_path, package_name, debug)

    def buildPackage(self, package_path: str, debug: bool = False) -> Dict[str, Any]:
        return self.build_package(package_path, debug)

    def publishPackage(
        self,
        package_path: str,
        sender_alias: str,
        gas_budget: int = 100_000_000,
        skip_dependency_verification: bool = False,
    ) -> MovePackage:
        return self.publish_package(
            package_path=package_path,
            sender_alias=sender_alias,
            gas_budget=gas_budget,
            skip_dependency_verification=skip_dependency_verification,
        )

    def callFunction(
        self,
        package_id: str,
        module: str,
        function: str,
        sender_alias: str,
        type_args: Optional[List[str]] = None,
        args: Optional[List[str]] = None,
        gas_budget: int = 10_000_000,
    ) -> Dict[str, Any]:
        return self.call_function(
            package_id=package_id,
            module=module,
            function=function,
            sender_alias=sender_alias,
            type_args=type_args,
            args=args,
            gas_budget=gas_budget,
        )

    def getObject(self, object_id: str) -> Dict[str, Any]:
        return self.get_object(object_id)

    def getObjects(self, address: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.get_objects(address)

    def getPackageInfo(self, package_name: str) -> Optional[MovePackage]:
        return self.get_package_info(package_name)

    def listDeployedPackages(self) -> List[MovePackage]:
        return self.list_deployed_packages()

    def getPackageById(self, package_id: str) -> Optional[MovePackage]:
        return self.get_package_by_id(package_id)
    
    