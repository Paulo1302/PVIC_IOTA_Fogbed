import os
import shutil
import subprocess
import time
import re
from typing import List

from fogbed_iota.utils import get_logger
from fogbed_iota.models.iota_node import IotaNode

logger = get_logger('genesis')
MIN_IOTA_VERSION = "1.15.0"


def compare_versions(v1: str, v2: str) -> int:
    parts1 = [int(x) for x in v1.split(".")]
    parts2 = [int(x) for x in v2.split(".")]
    for i in range(max(len(parts1), len(parts2))):
        p1 = parts1[i] if i < len(parts1) else 0
        p2 = parts2[i] if i < len(parts2) else 0
        if p1 < p2:
            return -1
        elif p1 > p2:
            return 1
    return 0


def validate_binary_version(binary_path: str) -> str:
    result = subprocess.run([binary_path, "--version"], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Binary test failed: {result.stderr}")
    version_match = re.search(r"v?(\d+\.\d+\.\d+)", result.stdout)
    if version_match:
        version = version_match.group(1)
        logger.info(f"✅ IOTA binary version: {version}")
        if compare_versions(version, MIN_IOTA_VERSION) < 0:
            raise RuntimeError(f"IOTA version {version} is below minimum required {MIN_IOTA_VERSION}.")
        return version
    else:
        logger.warning(f"⚠️  Could not parse version from: {result.stdout}")
        return "unknown"


def ensure_iota_binary(image: str, current_path: str = None) -> str:
    if current_path:
        return current_path
    
    iota_path = shutil.which("iota")
    if iota_path and os.access(iota_path, os.X_OK):
        logger.info(f"✅ Found iota binary in PATH: {iota_path}")
        validate_binary_version(iota_path)
        return iota_path
        
    logger.warning("⚠️ iota binary not found in PATH")
    logger.info(f"Extracting binary from image: {image}")
    
    temp_bin_dir = "/tmp/fogbed_iota_bin"
    os.makedirs(temp_bin_dir, exist_ok=True)
    
    result = subprocess.run(["docker", "create", image], capture_output=True, text=True, check=True)
    container_id = result.stdout.strip()
    iota_temp_path = f"{temp_bin_dir}/iota"
    
    try:
        subprocess.run(["docker", "cp", f"{container_id}:/usr/local/bin/iota", iota_temp_path], check=True, capture_output=True)
    finally:
        try:
            subprocess.run(["docker", "rm", "-f", container_id], check=True, capture_output=True)
        except Exception:
            logger.debug(f"Failed to remove temporary container: {container_id}")
            
    os.chmod(iota_temp_path, 0o755)
    validate_binary_version(iota_temp_path)
    return iota_temp_path


def generate_genesis(validators: List[IotaNode], genesis_dir: str, iota_binary: str) -> None:
    if not validators:
        raise RuntimeError("At least one validator required for genesis generation")
        
    logger.info(f"Generating genesis for {len(validators)} validators")

    benchmark_ips = [v.ip_addr for v in validators]
    chain_start_ms = str(int(time.time() * 1000))
    
    cmd = [
        iota_binary, "genesis",
        "--working-dir", genesis_dir,
        "--force",
        "--committee-size", str(len(validators)),
        "--benchmark-ips", *benchmark_ips,
        "--chain-start-timestamp-ms", chain_start_ms,
        "--epoch-duration-ms", "86400000",
    ]
    
    logger.debug(f"Genesis command: {' '.join(cmd)}")
    subprocess.run(cmd, capture_output=True, text=True, check=True)

    genesis_blob = os.path.join(genesis_dir, "genesis.blob")
    network_yaml = os.path.join(genesis_dir, "network.yaml")
    
    if not os.path.exists(genesis_blob):
        raise RuntimeError(f"Genesis blob not created at {genesis_blob}")
    if not os.path.exists(network_yaml):
        raise RuntimeError(f"network.yaml not created at {network_yaml}")

    with open(network_yaml, "r", encoding="utf-8") as f:
        network_content = f.read()
    if "/ip4/127.0.0.1/" in network_content:
        raise RuntimeError(
            "Generated network.yaml still contains localhost committee addresses; "
            "consensus will stall. Check genesis --benchmark-ips support."
        )

    logger.info("✅ Genesis generated successfully with benchmark IPs")
