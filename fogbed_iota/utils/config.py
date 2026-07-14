import os
import shutil
import glob
import re
from typing import List

from fogbed_iota.utils import get_logger
from fogbed_iota.models.iota_node import IotaNode

logger = get_logger('config')


def patch_genesis_network_yaml(network_yaml: str, validators: List[IotaNode]) -> None:
    import yaml as _yaml
    with open(network_yaml, "r") as f:
        content = f.read()
    
    try:
        data = _yaml.safe_load(content)
    except Exception as e:
        logger.warning(f"Could not parse network.yaml as YAML: {e}")
        return
    
    validator_configs = data.get("validator_configs", [])
    if not validator_configs:
        logger.warning("No validator_configs found in network.yaml")
        return
    
    for i, (cfg, node) in enumerate(zip(validator_configs, validators)):
        old_net_addr = cfg.get("network-address", "")
        if old_net_addr and "127.0.0.1" in old_net_addr:
            port_match = re.search(r'/tcp/(\d+)', old_net_addr)
            port = port_match.group(1) if port_match else "8080"
            cfg["network-address"] = f"/ip4/{node.ip_addr}/tcp/{port}/http"
            logger.debug(f"Validator {i}: network-address {old_net_addr} → {cfg['network-address']}")
        
        p2p = cfg.get("p2p-config", {})
        if p2p:
            p2p["listen-address"] = f"0.0.0.0:{node.p2p_port}"
            p2p["external-address"] = f"/ip4/{node.ip_addr}/udp/{node.p2p_port}/quic"
    
    with open(network_yaml, "w") as f:
        _yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
    
    logger.info(f"✅ network.yaml patched for {len(validators)} validators")


def patch_validator_yaml(source: str, dest: str, node: IotaNode, all_validators: List[IotaNode]) -> None:
    logger.debug(f"Patching validator YAML: {source} → {dest}")
    with open(source, "r") as f:
        lines = f.readlines()
    new_lines: List[str] = []
    for line in lines:
        if "db-path:" in line:
            indent = " " * (len(line) - len(line.lstrip()))
            new_lines.append(f'{indent}db-path: "/app/db"\n')
        elif "genesis-file-location:" in line:
            indent = " " * (len(line) - len(line.lstrip()))
            new_lines.append(f'{indent}genesis-file-location: "/custom_config/genesis.blob"\n')
        elif "network-address:" in line:
            indent = " " * (len(line) - len(line.lstrip()))
            port_match = re.search(r'/tcp/(\d+)', line)
            if port_match:
                net_port = port_match.group(1)
            else:
                net_port = str(2000 + all_validators.index(node) * 10)
            new_lines.append(f"{indent}network-address: /ip4/0.0.0.0/tcp/{net_port}/http\n")
        elif "metrics-address:" in line:
            indent = " " * (len(line) - len(line.lstrip()))
            new_lines.append(f'{indent}metrics-address: "0.0.0.0:9184"\n')
        elif "listen-address:" in line and "p2p" not in line.lower():
            indent = " " * (len(line) - len(line.lstrip()))
            new_lines.append(f'{indent}listen-address: "0.0.0.0:{node.p2p_port}"\n')
        elif "external-address:" in line:
            indent = " " * (len(line) - len(line.lstrip()))
            new_lines.append(f'{indent}external-address: /ip4/{node.ip_addr}/udp/{node.p2p_port}/quic\n')
        elif any(k in line for k in ["pruning-period", "num-epochs-to-retain"]):
            continue
        else:
            new_lines.append(line)
    with open(dest, "w") as f:
        f.writelines(new_lines)
    logger.debug(f"✅ Validator YAML patched for {node.name}")


def extract_peer_ids(genesis_dir: str) -> List[str]:
    peer_ids = []
    fullnode_yaml = os.path.join(genesis_dir, "fullnode.yaml")
    if os.path.exists(fullnode_yaml):
        with open(fullnode_yaml, "r") as f:
            content = f.read()
        matches = re.findall(r'peer-id:\s*([a-f0-9]{64})', content)
        if matches:
            logger.debug(f"Extracted {len(matches)} peer-ids from fullnode.yaml")
            return matches
    logger.warning("⚠️  Could not extract peer-ids from fullnode.yaml, seed-peers will lack peer-id")
    return []


def create_gateway_config(source: str, dest: str, gateway: IotaNode, validators: List[IotaNode], genesis_dir: str) -> None:
    logger.debug(f"Creating gateway(fullnode) config: {dest}")
    
    peer_ids = extract_peer_ids(genesis_dir)
    
    lines = [
        "---",
        'db-path: "/app/db"',
        "network-address: /ip4/0.0.0.0/tcp/8080/http",
        'metrics-address: "0.0.0.0:9184"',
        "",
        'json-rpc-address: "0.0.0.0:9000"',
        "",
        "genesis:",
        '  genesis-file-location: "/custom_config/genesis.blob"',
        "",
        "p2p-config:",
        f'  listen-address: "0.0.0.0:{gateway.p2p_port}"',
        f"  external-address: /ip4/{gateway.ip_addr}/udp/{gateway.p2p_port}/quic",
        "  seed-peers:",
    ]
    
    for i, v in enumerate(validators):
        if i < len(peer_ids):
            lines.append(f"    - peer-id: {peer_ids[i]}")
            lines.append(f"      address: /ip4/{v.ip_addr}/udp/{v.p2p_port}/quic")
        else:
            lines.append(f"    - address: /ip4/{v.ip_addr}/udp/{v.p2p_port}/quic")
            
    with open(dest, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
        
    logger.debug("✅ Gateway(fullnode) config created with UDP peer addresses")


def prepare_configs(nodes: List[IotaNode], genesis_dir: str, live_data_dir: str) -> None:
    logger.info("Preparing YAML configurations")
    
    yaml_files = sorted(glob.glob(os.path.join(genesis_dir, "**", "*.y*ml"), recursive=True))
    logger.debug(f"Found YAMLs: {[os.path.basename(f) for f in yaml_files]}")
    
    validator_yamls = []
    for f in yaml_files:
        base = os.path.basename(f).lower()
        if any(skip in base for skip in ["client", "iota_config", "fullnode", "network"]):
            continue
        validator_yamls.append(f)
        
    validators = [n for n in nodes if n.role == "validator"]
    if not validator_yamls:
        raise RuntimeError(f"No validator templates found in {genesis_dir}. Check genesis generation.")
        
    for i, node in enumerate(validators):
        template = validator_yamls[i % len(validator_yamls)]
        logger.debug(f"Using template {os.path.basename(template)} for {node.name}")
        
        node_dir = f"{live_data_dir}/{node.name}"
        os.makedirs(node_dir, exist_ok=True)
        shutil.copy(f"{genesis_dir}/genesis.blob", f"{node_dir}/genesis.blob")
        patch_validator_yaml(template, f"{node_dir}/validator.yaml", node, validators)
        
    fullnodes = [n for n in nodes if n.role == "fullnode"]
    if fullnodes:
        fullnode_yaml = next((f for f in yaml_files if "fullnode" in os.path.basename(f).lower()), validator_yamls[0])
        gateway = fullnodes[0]
        gw_dir = f"{live_data_dir}/{gateway.name}"
        os.makedirs(gw_dir, exist_ok=True)
        shutil.copy(f"{genesis_dir}/genesis.blob", f"{gw_dir}/genesis.blob")
        create_gateway_config(fullnode_yaml, f"{gw_dir}/validator.yaml", gateway, validators, genesis_dir)
        
    logger.info("✅ All configurations prepared")
