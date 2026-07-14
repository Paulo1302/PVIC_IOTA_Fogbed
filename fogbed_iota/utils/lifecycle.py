import os
import time
import json
from typing import List

from fogbed_iota.utils import get_logger
from fogbed_iota.models.iota_node import IotaNode

logger = get_logger('lifecycle')


def debug_runtime_ip(node: IotaNode) -> None:
    out = node.cmd("sh -lc \"ip -4 addr show | grep -oE '10\\.0\\.0\\.[0-9]+' | head -n1 || true\"").strip()
    logger.debug(f"Node {node.name} (role={node.role}, expected_ip={node.ip_addr}, runtime_ip={out})")


def wait_node_process(node: IotaNode, timeout: int = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        out = node.cmd("sh -lc 'test -f /var/log/iota/iota-node.pid && ps -p $(cat /var/log/iota/iota-node.pid) >/dev/null 2>&1 && echo OK || echo NOK'")
        if "OK" in out:
            logger.debug(f"✅ Process started on {node.name}")
            return
        time.sleep(1)
    tail = node.cmd("sh -lc 'tail -n 200 /var/log/iota/iota-node.log 2>/dev/null || true'")
    raise RuntimeError(f"iota-node failed to start on {node.name}. Last log:\n{tail}")


def wait_port_open(node: IotaNode, port: int, timeout: int = 90) -> None:
    deadline = time.time() + timeout
    check_tool = node.cmd("command -v ss >/dev/null 2>&1 && echo ss || echo netstat").strip()
    if check_tool == "ss":
        check_cmd = f"ss -lnt | grep -q ':{port}'"
    else:
        check_cmd = f"netstat -lnt | grep -q ':{port}'"
    logger.debug(f"Waiting for port {port} on {node.name} using {check_tool}")
    while time.time() < deadline:
        out = node.cmd(f"sh -lc '{check_cmd} && echo OK || echo NOK'")
        if "OK" in out:
            logger.debug(f"✅ Port {port} open on {node.name}")
            return
        time.sleep(2)
    tail = node.cmd("sh -lc 'tail -n 220 /var/log/iota/iota-node.log 2>/dev/null || true'")
    raise RuntimeError(f"Port {port} did not open on {node.name} within {timeout}s. Last log:\n{tail}")


def inject_and_start_node(node: IotaNode, live_data_dir: str) -> None:
    src_dir = f"{live_data_dir}/{node.name}"
    if not os.path.exists(src_dir):
        raise RuntimeError(f"Config directory missing for {node.name}: {src_dir}")
    logger.info(f"Booting node: {node.name} (role={node.role}, ip={node.ip_addr})")
    node.cmd("mkdir -p /custom_config")
    cmd = f"docker cp {src_dir}/. mn.{node.name}:/custom_config/"
    rc = os.system(cmd)
    if rc != 0:
        raise RuntimeError(f"docker cp failed for {node.name} (exit code {rc})")
    logger.debug(f"Successfully copied {src_dir} to mn.{node.name}:/custom_config/")
    node.cmd("sh -lc 'ls -la /custom_config && echo --- && head -n 80 /custom_config/validator.yaml'")
    debug_runtime_ip(node)
    time.sleep(1)
    node.cmd(node.get_config_command())
    wait_node_process(node, timeout=30)


def inject_and_boot(nodes: List[IotaNode], live_data_dir: str) -> None:
    logger.info("Injecting configs and booting nodes")
    validators = [n for n in nodes if n.role == "validator"]
    fullnodes = [n for n in nodes if n.role == "fullnode"]
    
    logger.info(f"Starting {len(validators)} validators sequentially...")
    for i, node in enumerate(validators):
        inject_and_start_node(node, live_data_dir)
        if i < len(validators) - 1:
            logger.debug(f"Waiting 8s before starting next validator...")
            time.sleep(8)
            
    if validators:
        logger.info("Waiting 15s for validator network to stabilize...")
        time.sleep(15)
        
    logger.info(f"Starting {len(fullnodes)} fullnodes...")
    for node in fullnodes:
        inject_and_start_node(node, live_data_dir)
        wait_port_open(node, 9000, timeout=90)
        
    logger.info("✅ All nodes booted successfully")


def wait_for_network_ready(nodes: List[IotaNode], timeout: int = 90) -> None:
    logger.info("Waiting for network consensus...")
    gateway = next((n for n in nodes if n.role == "fullnode"), None)
    if not gateway:
        logger.warning("No gateway found, skipping RPC health check")
        return
        
    deadline = time.time() + timeout
    rpc_url = f"http://{gateway.ip_addr}:{gateway.rpc_port}"
    while time.time() < deadline:
        try:
            result = gateway.cmd(f'curl -s -X POST {rpc_url} -H "Content-Type: application/json" -d \'{{' + '"jsonrpc":"2.0","method":"iota_getTotalTransactionBlocks","params":[],"id":1}}\' 2>/dev/null || echo FAIL')
            if "FAIL" not in result and "error" not in result.lower():
                try:
                    data = json.loads(result)
                    if "result" in data:
                        logger.info(f"✅ RPC responding: {data}")
                        return
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            logger.debug(f"RPC check failed: {e}")
        time.sleep(3)
        
    logger.warning(f"⚠️ RPC did not respond within {timeout}s, proceeding anyway...")
