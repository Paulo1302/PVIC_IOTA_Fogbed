import os
import re
import shlex
import subprocess
from typing import Any, Dict, List, Optional

from fogbed_iota.utils import get_logger
from fogbed_iota.utils.parser import extract_json_from_output, tx_digest, tx_looks_successful
from fogbed_iota.models.package import MovePackage
from fogbed_iota.contracts.raw_executor import RawExecutor

logger = get_logger("contracts.manager")


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
        self.executor = RawExecutor(self.client)

        logger.info("SmartContractManager initialized")

    def _get_account(self, sender_alias: str):
        if hasattr(self.accounts, "get_account"):
            return self.accounts.get_account(sender_alias)
        raise AttributeError("Account manager does not provide get_account()")

    def _get_balance(self, sender_alias: str) -> int:
        if hasattr(self.accounts, "get_balance"):
            return int(self.accounts.get_balance(sender_alias))
        return 0

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

        digest = tx_digest(tx_result)
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


    # ==================== Package Management ====================

    def copy_package_to_container(self, local_path: str, package_name: str, debug: bool = False) -> str:
        logger.info(f"Copying package '{package_name}' to container")

        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Local package path not found: {local_path}")

        move_toml = os.path.join(local_path, "Move.toml")
        if not os.path.exists(move_toml):
            raise FileNotFoundError(f"Move.toml not found in {local_path}")

        container_path = f"{self.contracts_dir}/{package_name}"
        self.client.cmd(f"mkdir -p {shlex.quote(container_path)}")

        container_id = self.executor.resolve_container_id()

        tar_cmd = (
            f"tar -C {shlex.quote(local_path)} -cf - . | "
            f"docker exec -i {container_id} tar -C {shlex.quote(container_path)} -xf -"
        )

        tar_result = subprocess.run(tar_cmd, shell=True, check=False)
        if tar_result.returncode != 0:
            logger.warning(f"tar method failed with code {tar_result.returncode}, trying docker cp")
            cp_cmd = f"docker cp {shlex.quote(local_path)}/. {container_id}:{container_path}/"
            cp_result = subprocess.run(cp_cmd, shell=True, check=False)
            if cp_result.returncode != 0:
                raise RuntimeError(f"Failed to copy package (tar exit: {tar_result.returncode}, cp exit: {cp_result.returncode})")

        verify_cmd = f"test -f {shlex.quote(container_path)}/Move.toml && echo 'OK' || echo 'MISSING'"
        verify_result = self.client.cmd(verify_cmd)

        if "MISSING" in verify_result:
            raise RuntimeError(f"Copy reported success but Move.toml not found in container at {container_path}")

        logger.info(f"✅ Package copied to {container_path}")
        return container_path

    def build_package(self, package_path: str, debug: bool = False) -> Dict[str, Any]:
        logger.info(f"Building Move package: {package_path}")
        package_path = package_path.rstrip("/")
        move_toml_path = f"{package_path}/Move.toml"

        check_cmd = f"test -f {shlex.quote(move_toml_path)} && echo 'OK' || echo 'NOT_FOUND'"
        raw_check = self.client.cmd(check_cmd)
        check = raw_check.strip()

        if "OK" not in check or "NOT_FOUND" in check:
            raise FileNotFoundError(f"Move.toml not found in {package_path}.")

        build_cmd = f"cd {shlex.quote(package_path)} && iota move build 2>&1"
        output = self.client.cmd(build_cmd)

        status_cmd = f"cd {shlex.quote(package_path)} && iota move build >/dev/null 2>&1 && echo 'OK' || echo 'FAIL'"
        raw_status = self.client.cmd(status_cmd)
        status = raw_status.strip()

        if "OK" not in status or "FAIL" in status:
            raise RuntimeError(f"Move build failed. Check package syntax.\n{output[:1000]}")

        modules = self.executor.extract_modules_from_build(package_path)

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
        account = self._get_account(sender_alias)
        if not account:
            raise ValueError(f"Account '{sender_alias}' not found.")

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
            raise RuntimeError(f"Insufficient balance for {sender_alias}.")

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
                if isinstance(result_raw, dict) and tx_looks_successful(result_raw):
                    tx_result = result_raw
                elif isinstance(result_raw, dict) and result_raw:
                    logger.warning(f"IotaCLI returned incomplete payload: {result_raw}")
            except Exception as exc:
                wrapper_error = exc
                logger.warning(f"IotaCLI.publish_package failed: {exc}")

        if tx_result is None:
            tx_result = self.executor.run_raw_publish(
                package_path=package_path,
                sender=account.address,
                gas_budget=gas_budget,
                skip_dependency_verification=skip_dependency_verification,
            )

        move_pkg = self._extract_publish_metadata(tx_result, package_path, account.address)
        logger.info(f"✅ Package published! ID: {move_pkg.package_id}")
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
                if isinstance(result, dict) and tx_looks_successful(result):
                    result_raw = result
                elif isinstance(result, dict):
                    logger.warning(f"IotaCLI returned non-success payload: {result}")
            except Exception as exc:
                wrapper_error = exc

        if result_raw is None:
            result_raw = self.executor.run_raw_call(
                package_id=package_id,
                module=module,
                function=function,
                sender=account.address,
                gas_budget=gas_budget,
                type_args=type_args,
                args=args,
            )

        logger.info(f"✅ Function executed: {tx_digest(result_raw)}")
        return result_raw

    def get_object(self, object_id: str) -> Dict[str, Any]:
        if self.cli:
            try:
                result = self.cli.get_object(object_id)
                if isinstance(result, dict):
                    return result
            except Exception:
                pass
        cmd = f"iota client object {shlex.quote(object_id)} --json 2>&1"
        result = self.client.cmd(cmd)
        try:
            return extract_json_from_output(result)
        except Exception:
            return {"object_id": object_id, "raw": result}

    def get_objects(self, address: Optional[str] = None) -> List[Dict[str, Any]]:
        if self.cli:
            try:
                result = self.cli.get_objects(address)
                if isinstance(result, list):
                    return result
            except Exception:
                pass
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
        return list(self.deployed_packages.values())

    def get_package_by_id(self, package_id: str) -> Optional[MovePackage]:
        for pkg in self.deployed_packages.values():
            if pkg.package_id == package_id:
                return pkg
        return None

    # ==================== Compatibility Aliases ====================
    def copyPackageToContainer(self, local_path: str, package_name: str, debug: bool = False) -> str:
        return self.copy_package_to_container(local_path, package_name, debug)

    def buildPackage(self, package_path: str, debug: bool = False) -> Dict[str, Any]:
        return self.build_package(package_path, debug)

    def publishPackage(self, package_path: str, sender_alias: str, gas_budget: int = 100_000_000, skip_dependency_verification: bool = False) -> MovePackage:
        return self.publish_package(package_path, sender_alias, gas_budget, skip_dependency_verification)

    def callFunction(self, package_id: str, module: str, function: str, sender_alias: str, type_args: Optional[List[str]] = None, args: Optional[List[str]] = None, gas_budget: int = 10_000_000) -> Dict[str, Any]:
        return self.call_function(package_id, module, function, sender_alias, type_args, args, gas_budget)

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
