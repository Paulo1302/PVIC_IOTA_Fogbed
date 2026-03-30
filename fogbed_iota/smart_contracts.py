# fogbed_iota/smart_contracts.py

"""
Smart Contract Manager for IOTA 1.15+ Move Packages

Production-ready implementation following IOTA CLI official patterns.
Uses IotaCLI as single source of truth for all blockchain operations.

Key features:
- Robust JSON parsing with regex fallback for mixed output
- Proper UpgradeCap extraction from objectChanges  
- Shell-safe argument escaping with shlex
- Clear separation of concerns (no funding logic)
- Type-safe operations with comprehensive error handling
"""

import json
import os
import re
import shlex
import subprocess
import time
from typing import Dict, List, Optional, Any
from pathlib import Path

from fogbed_iota.utils import get_logger

logger = get_logger('smart_contracts')


def _strip_ansi(text: str) -> str:
    """
    Remove ANSI escape sequences from text.
    
    These sequences (e.g., \x1b[?2004l, \x1b[0m) are used for terminal
    formatting and can interfere with JSON parsing.
    
    Args:
        text: Raw text that may contain ANSI codes
        
    Returns:
        Text with ANSI codes removed
    """
    # Pattern matches all ANSI escape sequences
    ansi_pattern = r'\x1B\[[0-?]*[ -/]*[@-~]'
    return re.sub(ansi_pattern, '', text)


def _extract_json_from_output(output: str) -> Dict[str, Any]:
    """
    Extract JSON object from potentially mixed CLI output.
    
    IOTA CLI often mixes logs (stderr) with JSON (stdout).
    This function robustly extracts the JSON block using regex.
    
    Cleans ANSI escape sequences before parsing to avoid contamination.
    
    Args:
        output: Raw CLI output (may contain logs + JSON + ANSI codes)
        
    Returns:
        Parsed JSON as dict
        
    Raises:
        ValueError: If no valid JSON found
        json.JSONDecodeError: If JSON is malformed
    """
    # Strip ANSI codes first to avoid contamination
    output_clean = _strip_ansi(output).strip()
    
    # Try direct parse first (fast path)
    if output_clean.startswith('{') or output_clean.startswith('['):
        try:
            return json.loads(output_clean)
        except json.JSONDecodeError:
            pass  # Fall through to regex extraction
    
    # Extract JSON block using regex (handles mixed output)
    json_pattern = r'\{(?:[^{}]|(?:\{(?:[^{}]|(?:\{[^{}]*\}))*\}))*\}'
    matches = re.findall(json_pattern, output_clean, re.DOTALL)
    
    if not matches:
        raise ValueError(
            f"No JSON object found in CLI output.\n"
            f"Output preview: {output_clean[:500]}"
        )
    
    # Try to parse each match (largest first)
    matches_sorted = sorted(matches, key=len, reverse=True)
    
    for match in matches_sorted:
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            continue
    
    # If all parsing failed, raise with details
    raise json.JSONDecodeError(
        f"Found JSON-like blocks but all failed to parse",
        matches_sorted[0] if matches_sorted else "",
        0
    )


class MovePackage:
    """
    Represents a published Move package on IOTA blockchain.
    
    Attributes:
        package_id: The package object ID (0x...)
        name: Human-readable package name
        modules: List of module names in the package
        digest: Transaction digest from publish
        publisher: Address that published the package
        upgrade_cap_id: Optional UpgradeCap object ID (for package upgrades)
        version: Package version (for upgrade tracking)
        deployed_at: Unix timestamp of deployment
    """
    
    def __init__(
        self,
        package_id: str,
        name: str,
        modules: List[str],
        digest: str,
        publisher: str,
        upgrade_cap_id: Optional[str] = None,
        version: int = 1
    ):
        self.package_id = package_id
        self.name = name
        self.modules = modules
        self.digest = digest
        self.publisher = publisher
        self.upgrade_cap_id = upgrade_cap_id
        self.version = version
        self.deployed_at = time.time()
    
    def __repr__(self):
        upgradeable = f", upgradeable={bool(self.upgrade_cap_id)}" if self.upgrade_cap_id else ""
        return f"MovePackage(name='{self.name}', id='{self.package_id[:16]}...', v{self.version}{upgradeable})"
    
    def is_upgradeable(self) -> bool:
        """Check if package can be upgraded (has UpgradeCap)"""
        return self.upgrade_cap_id is not None


class SmartContractManager:
    """
    Production-ready manager for Move smart contracts on IOTA 1.15+.
    
    This manager follows IOTA's official CLI patterns and uses IotaCLI
    as the single source of truth for all blockchain operations.
    
    Key design principles:
    - Uses IotaCLI for all CLI operations (consistency)
    - Robust JSON parsing with regex fallback
    - Shell-safe argument escaping  
    - No funding logic (separation of concerns)
    - Clear error messages with actionable suggestions
    """
    
    def __init__(self, cli_or_container, account_manager):
        """
        Initialize the smart contract manager.
        
        Args:
            cli_or_container: IotaCLI instance (preferred) or Container (legacy)
            account_manager: AccountManager for account lookups
        """
        # Support both IotaCLI (new) and Container (legacy)
        from fogbed_iota.client.cli import IotaCLI
        
        if isinstance(cli_or_container, IotaCLI):
            self.cli = cli_or_container
            self.client = cli_or_container.container
        else:
            # Legacy: container passed directly
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
    
    # ==================== Package Management ====================
    
    def copy_package_to_container(self, local_path: str, package_name: str, debug: bool = False) -> str:
        """
        Copy a Move package from host to container using robust method.
        
        Uses tar + docker exec instead of docker cp for better compatibility
        with remote Docker hosts and SSH tunnels.
        
        Args:
            local_path: Local filesystem path to package (containing Move.toml)
            package_name: Name for the directory in container
            debug: If True, print verbose debugging information
            
        Returns:
            Container path to the copied package
        """
        logger.info(f"Copying package '{package_name}' to container")
        
        # Validate local path
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Local package path not found: {local_path}")
        
        # Validate Move.toml exists
        move_toml = os.path.join(local_path, "Move.toml")
        if not os.path.exists(move_toml):
            raise FileNotFoundError(f"Move.toml not found in {local_path}")
        
        if debug:
            print(f"🔍 DEBUG: Local path: {local_path}")
            print(f"🔍 DEBUG: Move.toml exists: {os.path.exists(move_toml)}")
            print(f"🔍 DEBUG: Local files:")
            for root, dirs, files in os.walk(local_path):
                for f in files:
                    print(f"   - {os.path.join(root, f)}")
        
        container_path = f"{self.contracts_dir}/{package_name}"
        
        # Create directory in container
        self.client.cmd(f"mkdir -p {container_path}")
        
        # Get container name/ID robustly
        try:
            container_id_cmd = f"docker ps --filter 'name={self.client.name}' --format '{{{{.ID}}}}'"
            container_id = subprocess.check_output(container_id_cmd, shell=True, text=True).strip()
            if not container_id:
                container_id = f"mn.{self.client.name}"
                if debug:
                    print(f"🔍 DEBUG: Using fallback container ID: {container_id}")
        except Exception as e:
            container_id = f"mn.{self.client.name}"
            if debug:
                print(f"🔍 DEBUG: Container lookup failed: {e}")
                print(f"🔍 DEBUG: Using fallback: {container_id}")
        
        if debug:
            print(f"🔍 DEBUG: Container ID: {container_id}")
            print(f"🔍 DEBUG: Container path: {container_path}")
        
        # Copy using tar (most robust for remote Docker)
        tar_cmd = (
            f"tar -C {shlex.quote(local_path)} -cf - . | "
            f"docker exec -i {container_id} tar -C {container_path} -xf -"
        )
        
        if debug:
            print(f"🔍 DEBUG: Tar command: {tar_cmd}")
        
        result = os.system(tar_cmd)
        
        if result != 0:
            # Fallback to docker cp
            logger.warning(f"tar method failed with code {result}, trying docker cp")
            if debug:
                print(f"🔍 DEBUG: Tar failed with exit code: {result}")
            
            cp_cmd = f"docker cp {shlex.quote(local_path)}/. {container_id}:{container_path}/"
            if debug:
                print(f"🔍 DEBUG: Docker cp command: {cp_cmd}")
            
            result = os.system(cp_cmd)
            
            if result != 0:
                error_msg = f"Failed to copy package (tar exit: {result}, cp exit: {result})"
                logger.error(error_msg)
                if debug:
                    print(f"🔍 DEBUG: Both methods failed!")
                raise RuntimeError(error_msg)
        
        # Verify copy succeeded
        verify_cmd = f"test -f {container_path}/Move.toml && echo 'OK' || echo 'MISSING'"
        verify_result = self.client.cmd(verify_cmd)
        
        if "MISSING" in verify_result:
            raise RuntimeError(f"Copy reported success but Move.toml not found in container at {container_path}")
        
        logger.info(f"✅ Package copied to {container_path}")
        return container_path
    
    def build_package(self, package_path: str, debug: bool = False) -> Dict[str, Any]:
        """
        Build a Move package using `iota move build`.
        
        Args:
            package_path: Path to package INSIDE container
            debug: If True, print verbose debugging information
            
        Returns:
            Dict with build information
        """
        logger.info(f"Building Move package: {package_path}")
        
        # Normalize path (remove trailing slashes)
        package_path = package_path.rstrip("/")
        move_toml_path = f"{package_path}/Move.toml"
        
        if debug:
            print(f"🔍 DEBUG: Normalized package_path: {package_path}")
            print(f"🔍 DEBUG: Move.toml path: {move_toml_path}")
            print(f"🔍 DEBUG: Listing package directory:")
            ls_output = self.client.cmd(f"ls -la {shlex.quote(package_path)}/ || echo 'DIR_NOT_FOUND'")
            print(ls_output)
        
        # Verify Move.toml exists with quoted path
        check_cmd = f"test -f {shlex.quote(move_toml_path)} && echo 'OK' || echo 'NOT_FOUND'"
        raw_check = self.client.cmd(check_cmd)
        check = raw_check.strip()
        
        if debug:
            print(f"🔍 DEBUG: Move.toml check command: {check_cmd}")
            print(f"🔍 DEBUG: Raw check output: {raw_check!r}")
            print(f"🔍 DEBUG: Stripped check output: {check!r}")
        
        # Use 'in' operator for robustness against whitespace/newlines
        if 'OK' not in check or 'NOT_FOUND' in check:
            # Extra debug before failing
            logger.error(f"Move.toml verification failed at {move_toml_path}")
            if debug:
                print("🔍 DEBUG: Listing /contracts structure:")
                print(self.client.cmd("ls -R /contracts/"))
                print("🔍 DEBUG: Direct test with ls:")
                print(self.client.cmd(f"ls -la {shlex.quote(move_toml_path)} || echo 'FILE NOT FOUND'"))
            raise FileNotFoundError(
                f"Move.toml not found in {package_path}. "
                f"Ensure package structure is correct. (check result: {check!r})"
            )
        
        if debug:
            print("✅ DEBUG: Move.toml verified successfully!")
        
        # Build (removed --dump-bytecode-as-base64 - not standard)
        build_cmd = f"cd {shlex.quote(package_path)} && iota move build 2>&1"
        
        if debug:
            print(f"🔍 DEBUG: Build command: {build_cmd}")
        
        output = self.client.cmd(build_cmd)
        
        if debug:
            print(f"🔍 DEBUG: Build output:\n{output[:500]}")
        
        # Check return code via exit status (more reliable than text matching)
        status_cmd = f"cd {shlex.quote(package_path)} && iota move build >/dev/null 2>&1 && echo 'OK' || echo 'FAIL'"
        raw_status = self.client.cmd(status_cmd)
        status = raw_status.strip()
        
        if debug:
            print(f"🔍 DEBUG: Build status raw: {raw_status!r}")
            print(f"🔍 DEBUG: Build status stripped: {status!r}")
        
        # Use 'in' operator for robustness
        if 'OK' not in status or 'FAIL' in status:
            logger.error(f"Build failed:\n{output}")
            raise RuntimeError(f"Move build failed. Check package syntax.\n{output[:500]}")
        
        logger.info("✅ Build completed successfully")
        
        # Extract modules by listing .mv files
        modules = self._extract_modules_from_build(package_path)
        
        return {
            'success': True,
            'package_path': package_path,
            'build_path': f"{package_path}/build",
            'modules': modules,
            'output': output
        }
    
    def publish_package(
        self,
        package_path: str,
        sender_alias: str,
        gas_budget: int = 100_000_000,
        skip_dependency_verification: bool = False
    ) -> MovePackage:
        """
        Publish a Move package to IOTA blockchain (v1.15+ compatible).
        
        Uses IotaCLI if available, falls back to raw commands.
        Properly extracts packageId and UpgradeCap from objectChanges.
        
        Args:
            package_path: Path to package in container
            sender_alias: Account alias that pays for gas
            gas_budget: Gas budget in MIST
            skip_dependency_verification: Skip dependency checks
            
        Returns:
            MovePackage with packageId, modules, and UpgradeCap
        """
        logger.info(f"📦 Publishing Move package: {os.path.basename(package_path)}")
        logger.info(f"   Sender: {sender_alias}")
        logger.info(f"   Gas budget: {gas_budget:,} MIST")
        
        # Verify account
        account = self.accounts.get_account(sender_alias)
        if not account:
            available = list(self.accounts.accounts.keys())
            raise ValueError(
                f"Account '{sender_alias}' not found. "
                f"Available: {available}"
            )
        
        # Check balance using CLI if available
        if self.cli:
            try:
                coins = self.cli.get_gas(account.address)
                balance = sum(c.get('balance', 0) for c in coins)
            except:
                balance = self.accounts.get_balance(sender_alias)
        else:
            balance = self.accounts.get_balance(sender_alias)
        
        if balance < gas_budget:
            raise RuntimeError(
                f"❌ Insufficient balance for {sender_alias}\n"
                f"   Current: {balance:,} MIST ({balance/1e9:.4f} IOTA)\n"
                f"   Required: {gas_budget:,} MIST ({gas_budget/1e9:.4f} IOTA)\n"
                f"   Please fund the account first."
            )
        
        # Use IotaCLI if available, otherwise raw command
        if self.cli:
            logger.info("🚀 Publishing via IotaCLI (timeout: 600s)...")
            result_raw = self.cli.publish_package(
                package_path=package_path,
                gas_budget=gas_budget,
                sender=account.address
            )
            
            logger.debug(f"📥 IotaCLI returned type: {type(result_raw)}")
            logger.debug(f"📥 IotaCLI keys: {result_raw.keys() if isinstance(result_raw, dict) else 'N/A'}")
            
            # IotaCLI returns dict - use directly, no need to stringify and reparse
            if isinstance(result_raw, dict):
                # Extract the actual transaction result
                tx_result = result_raw.get('raw', result_raw)
                logger.debug(f"📥 tx_result type: {type(tx_result)}")
                
                if not isinstance(tx_result, dict):
                    # If raw is string, parse it
                    logger.info("📝 Parsing string output from CLI...")
                    tx_result = _extract_json_from_output(str(tx_result))
                else:
                    logger.info("✅ CLI returned dict directly - no parsing needed")
            else:
                # Fallback: parse string output
                logger.info("📝 Parsing string output from CLI...")
                tx_result = _extract_json_from_output(str(result_raw))
        else:
            # Raw command execution
            logger.info("🚀 Publishing via raw container command...")
            cmd = (
                f"cd {package_path} && "
                f"iota client publish "
                f"--gas-budget {gas_budget} "
                f"--json"
            )
            
            if skip_dependency_verification:
                cmd += " --skip-dependency-verification"
            
            logger.debug(f"Executing: {cmd}")
            result = self.client.cmd(cmd)
            
            # Parse JSON robustly
            try:
                tx_result = _extract_json_from_output(result)
            except (ValueError, json.JSONDecodeError) as e:
                logger.error(f"❌ Failed to parse publish result")
                logger.error(f"Raw output:\n{result[:1000]}")
                raise RuntimeError(f"Publish output parsing failed: {e}")
        
        # Verify transaction status
        effects = tx_result.get('effects', {})
        status = effects.get('status', {})
        
        if isinstance(status, dict):
            status_value = status.get('status')
            error_msg = status.get('error')
        else:
            status_value = status
            error_msg = None
        
        if status_value != 'success':
            raise RuntimeError(
                f"❌ Publish transaction failed: {error_msg or 'Unknown error'}"
            )
        
        # Extract from objectChanges (IOTA 1.15 format)
        object_changes = tx_result.get('objectChanges', [])
        
        if not object_changes:
            raise RuntimeError("No objectChanges in transaction result")
        
        # Find published package
        published_changes = [c for c in object_changes if c.get('type') == 'published']
        
        if not published_changes:
            raise RuntimeError(
                f"No 'published' objectChange found. "
                f"Changes: {[c.get('type') for c in object_changes]}"
            )
        
        package_change = published_changes[0]
        package_id = package_change.get('packageId')
        modules = package_change.get('modules', [])
        
        if not package_id:
            raise RuntimeError("packageId not found in published change")
        
        # Extract UpgradeCap (CRITICAL: check for "package::UpgradeCap")
        upgrade_cap_id = None
        
        for change in object_changes:
            if change.get('type') == 'created':
                object_type = change.get('objectType', '')
                # IOTA 1.15 format: "0x2::package::UpgradeCap"
                if 'package::UpgradeCap' in object_type:
                    upgrade_cap_id = change.get('objectId')
                    logger.info(f"   ✅ Found UpgradeCap: {upgrade_cap_id}")
                    break
        
        if not upgrade_cap_id:
            logger.warning("   ⚠️  No UpgradeCap - package is IMMUTABLE")
        
        # Extract digest
        digest = tx_result.get('digest', effects.get('transactionDigest', 'unknown'))
        
        # Create MovePackage
        package_name = os.path.basename(package_path.rstrip('/'))
        
        move_pkg = MovePackage(
            package_id=package_id,
            name=package_name,
            modules=modules,
            digest=digest,
            publisher=account.address,
            upgrade_cap_id=upgrade_cap_id,
            version=1
        )
        
        self.deployed_packages[package_name] = move_pkg
        
        logger.info(f"✅ Package published!")
        logger.info(f"   Package ID: {package_id}")
        logger.info(f"   Transaction: {digest}")
        logger.info(f"   Modules: {', '.join(modules) if modules else 'N/A'}")
        logger.info(f"   Upgradeable: {'Yes' if upgrade_cap_id else 'No'}")
        
        return move_pkg
    
    def call_function(
        self,
        package_id: str,
        module: str,
        function: str,
        sender_alias: str,
        type_args: Optional[List[str]] = None,
        args: Optional[List[str]] = None,
        gas_budget: int = 10_000_000
    ) -> Dict[str, Any]:
        """
        Call a public Move function (IOTA 1.15+ compatible).
        
        Uses IotaCLI if available for proper argument escaping.
        
        Args:
            package_id: Package ID (0x...)
            module: Module name
            function: Function name
            sender_alias: Account that executes
            type_args: Generic type arguments
            args: Function arguments
            gas_budget: Gas budget in MIST
            
        Returns:
            Dict with transaction result
        """
        logger.info(f"📞 Calling: {package_id}::{module}::{function}")
        
        # Verify account
        account = self.accounts.get_account(sender_alias)
        if not account:
            raise ValueError(f"Account '{sender_alias}' not found")
        
        # Use IotaCLI if available (handles escaping properly)
        if self.cli:
            result_raw = self.cli.call_function(
                package=package_id,
                module=module,
                function=function,
                args=args,
                type_args=type_args,
                gas_budget=gas_budget,
                sender=account.address
            )
            
            # Check status
            status = result_raw.get('status', 'unknown')
            if status != 'success':
                raise RuntimeError(f"Transaction failed: {result_raw.get('error', 'Unknown')}")
            
            logger.info(f"✅ Function executed: {result_raw.get('digest', 'N/A')}")
            return result_raw
        
        # Fallback: raw command with proper escaping
        cmd = (
            f"iota client call "
            f"--package {package_id} "
            f"--module {module} "
            f"--function {function} "
            f"--gas-budget {gas_budget} "
            f"--json"
        )
        
        # Add type arguments
        if type_args:
            for targ in type_args:
                cmd += f" --type-args {shlex.quote(targ)}"
        
        # Add function arguments (CRITICAL: use shlex.quote)
        if args:
            for arg in args:
                cmd += f" --args {shlex.quote(arg)}"
        
        logger.debug(f"Executing: {cmd}")
        result = self.client.cmd(cmd)
        
        # Parse JSON robustly
        try:
            tx_result = _extract_json_from_output(result)
        except (ValueError, json.JSONDecodeError) as e:
            logger.error(f"❌ Failed to parse call result")
            logger.error(f"Raw output:\n{result[:1000]}")
            raise RuntimeError(f"Call output parsing failed: {e}")
        
        # Check status
        effects = tx_result.get('effects', {})
        status = effects.get('status', {})
        
        if isinstance(status, dict):
            status_value = status.get('status')
            error_msg = status.get('error')
        else:
            status_value = status
            error_msg = None
        
        if status_value != 'success':
            raise RuntimeError(f"Transaction failed: {error_msg or 'Unknown error'}")
        
        digest = tx_result.get('digest', effects.get('transactionDigest', 'N/A'))
        logger.info(f"✅ Function executed: {digest}")
        
        return tx_result
    
    def get_object(self, object_id: str) -> Dict[str, Any]:
        """Fetch an object from blockchain."""
        logger.debug(f"Fetching object: {object_id}")
        
        if self.cli:
            return self.cli.get_object(object_id)
        
        cmd = f"iota client object {object_id} --json"
        result = self.client.cmd(cmd)
        
        try:
            return _extract_json_from_output(result)
        except:
            return {"object_id": object_id, "raw": result}
    
    def get_objects(self, address: Optional[str] = None) -> List[Dict[str, Any]]:
        """List objects owned by address."""
        if self.cli:
            return self.cli.get_objects(address)
        
        cmd = f"iota client objects"
        if address:
            cmd += f" {address}"
        
        result = self.client.cmd(cmd)
        
        # Parse output (text-based)
        objs = []
        for line in result.splitlines():
            m = re.search(r'(0x[a-fA-F0-9]+)', line)
            if m:
                objs.append({"object_id": m.group(1)})
        return objs
    
    # ==================== Package Registry ====================
    
    def get_package_info(self, package_name: str) -> Optional[MovePackage]:
        """Get deployed package by name."""
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
    
    # ==================== Private Helpers ====================
    
    def _extract_modules_from_build(self, package_path: str) -> List[str]:
        """Extract list of compiled modules from build directory."""
        cmd = f"find {package_path}/build -name '*.mv' -exec basename {{}} .mv \\; 2>/dev/null || true"
        result = self.client.cmd(cmd)
        modules = [m.strip() for m in result.split('\n') if m.strip()]
        return modules
