"""Step 2 of the two-step genesis: generation and artifact materialization for IOTA v1.33.1.

Takes a prepared Committee (Step 1) and:
1. Invokes `iota-localnet genesis --from-config <genesis-config.yaml> --working-dir <workdir> --force`
   either inside the pinned `iota-dev:latest` Docker image or via local binaries in `docker/bins`.
2. Verifies the single shared `genesis.blob` is created and captures its SHA256 checksum.
3. Generates per-validator and per-gateway `validator.yaml` configurations strictly adhering to
   the IOTA v1.33.1 NodeConfig schema:
     - `network-address: /ip4/0.0.0.0/tcp/<port>/http`
     - `p2p-config:`
         `listen-address: 0.0.0.0:<p2p_port>`
         `external-address: /ip4/<virtual_ip>/udp/<p2p_port>/quic`
         `seed-peers:` multiaddr list with peer-ids
     - `genesis:`
         `genesis-file-location: <dest_dir>/genesis.blob`
4. Validates that NO loopback or unspecified IP is present in externally announced addresses.
5. Injects artifacts into container target directories.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml

from .committee import Committee, CommitteeNode
from .errors import ConfigValidationError, GenesisError, ToolError
from .netaddr import parse_multiaddr, validate_announced
from .release import load_release
from .schema import (
    CONSENSUS_CONFIG_KEYS,
    NODE_CONFIG_KEYS,
    P2P_CONFIG_KEYS,
    REQUIRED_FULLNODE_KEYS,
    REQUIRED_VALIDATOR_KEYS,
    SEED_PEER_KEYS,
)
from .tools import ToolRunner

logger = logging.getLogger("fogbed_iota.genesis.builder")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class NodeArtifacts:
    """Artifacts materialized for a single node."""
    name: str
    role: str
    config_dir: Path
    validator_yaml: Path
    genesis_blob: Path
    node_metadata: Path
    genesis_blob_sha256: str


@dataclass
class GenesisArtifacts:
    """Complete set of generated network artifacts."""
    output_dir: Path
    genesis_blob: Path
    genesis_blob_sha256: str
    network_yaml: Path
    client_yaml: Path
    iota_keystore: Optional[Path]
    nodes: Dict[str, NodeArtifacts]


class GenesisBuilder:
    """Orchestrates Step 2 of the genesis pipeline."""

    def __init__(self, tools: Optional[ToolRunner] = None) -> None:
        self.tools = tools or ToolRunner()

    def build(
        self,
        committee: Committee,
        output_dir: Path,
        container_config_dir: str = "/custom_config",
    ) -> GenesisArtifacts:
        """Executes Step 2: runs genesis and produces validated node configurations."""
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        raw_dir = output_dir / "raw_genesis"
        raw_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Step 2: Invoking iota-localnet genesis with committee state from %s", committee.state_dir)
        cfg_path = committee.genesis_config_path
        if not cfg_path.is_file():
            raise GenesisError(f"Missing genesis config file: {cfg_path}")

        # Copy config into raw_dir to make path relative for runner
        local_cfg = raw_dir / "genesis-config.yaml"
        shutil.copy2(cfg_path, local_cfg)

        # Use an empty subdirectory for working-dir.
        # iota-localnet attempts fs::remove_dir_all on the working dir if not empty or with --force,
        # which fails with EINVAL (os error 22) if working-dir is "." or the mount point.
        out_dir = raw_dir / "out"
        if out_dir.exists():
            shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(parents=True, exist_ok=True)

        args = ["genesis", "--from-config", "genesis-config.yaml", "--working-dir", "out"]
        out = self.tools.run_localnet(args, raw_dir)
        logger.debug("Genesis tool output:\n%s", out)

        shared_genesis = out_dir / "genesis.blob"
        if not shared_genesis.is_file() or shared_genesis.stat().st_size == 0:
            raise ToolError(f"genesis.blob was not created in {out_dir}")

        genesis_hash = _sha256(shared_genesis)
        logger.info("✅ Shared genesis.blob generated (SHA256: %s, %d bytes)", genesis_hash, shared_genesis.stat().st_size)

        network_yaml = out_dir / "network.yaml"
        client_yaml = out_dir / "client.yaml"
        iota_keystore = out_dir / "iota.keystore"
        if not iota_keystore.is_file():
            # Check if benchmark.keystore exists in committee state
            bench_ks = committee.state_dir / "benchmark.keystore"
            if bench_ks.is_file():
                shutil.copy2(bench_ks, out_dir / "iota.keystore")
                iota_keystore = out_dir / "iota.keystore"
            else:
                iota_keystore = None

        node_artifacts: Dict[str, NodeArtifacts] = {}
        nodes_out_dir = output_dir / "nodes"
        nodes_out_dir.mkdir(parents=True, exist_ok=True)

        secrets = committee.secrets()

        for node in committee.nodes:
            node_dir = nodes_out_dir / node.name
            node_dir.mkdir(parents=True, exist_ok=True)

            # Copy shared genesis.blob identically to each node
            dest_genesis = node_dir / "genesis.blob"
            shutil.copy2(shared_genesis, dest_genesis)

            # Render validator.yaml
            val_yaml_path = node_dir / "validator.yaml"
            rendered = self._render_node_config(
                node=node,
                committee=committee,
                secrets=secrets.get(node.name, {}),
                container_config_dir=container_config_dir,
            )
            val_yaml_path.write_text(yaml.safe_dump(rendered, sort_keys=False), encoding="utf-8")

            # Validate rendered config
            self._validate_rendered_config(rendered, node)

            # Write node metadata JSON
            meta = {
                "name": node.name,
                "role": node.role,
                "ip": node.ip,
                "ports": node.ports,
                "peer_id": node.peer_id,
                "genesis_blob_sha256": genesis_hash,
                "p2p_external_address": node.p2p_external(),
            }
            meta_path = node_dir / "node.json"
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

            node_artifacts[node.name] = NodeArtifacts(
                name=node.name,
                role=node.role,
                config_dir=node_dir,
                validator_yaml=val_yaml_path,
                genesis_blob=dest_genesis,
                node_metadata=meta_path,
                genesis_blob_sha256=genesis_hash,
            )

        logger.info("Step 2 completed: Materialized configs for %d nodes", len(node_artifacts))
        return GenesisArtifacts(
            output_dir=output_dir,
            genesis_blob=shared_genesis,
            genesis_blob_sha256=genesis_hash,
            network_yaml=network_yaml,
            client_yaml=client_yaml,
            iota_keystore=iota_keystore,
            nodes=node_artifacts,
        )

    def _render_node_config(
        self,
        node: CommitteeNode,
        committee: Committee,
        secrets: Dict[str, str],
        container_config_dir: str,
    ) -> Dict[str, Any]:
        """Produces a strictly valid v1.33.1 NodeConfig dict."""
        is_validator = node.role == "validator"
        genesis_loc = f"{container_config_dir}/genesis.blob"

        # Calculate seed peers for P2P network
        seed_peers: List[Dict[str, str]] = []
        if is_validator:
            # Validators peer with all OTHER validators and any gateways
            for other in committee.nodes:
                if other.name != node.name:
                    seed_peers.append({
                        "peer-id": other.peer_id,
                        "address": other.p2p_external(),
                    })
        else:
            # Gateways/fullnodes peer with all validators
            for val in committee.validators:
                seed_peers.append({
                    "peer-id": val.peer_id,
                    "address": val.p2p_external(),
                })

        p2p_config = {
            "listen-address": f"0.0.0.0:{node.ports['p2p']}",
            "external-address": node.p2p_external(),
            "seed-peers": seed_peers,
        }

        config: Dict[str, Any] = {
            "network-key-pair": {"value": secrets.get("network_key", "")},
            "db-path": "/app/db",
            "network-address": f"/ip4/0.0.0.0/tcp/{node.ports['network']}/http",
            "metrics-address": f"0.0.0.0:{node.ports['metrics']}",
            "admin-interface-address": f"127.0.0.1:{node.ports['admin']}",
            "p2p-config": p2p_config,
            "genesis": {
                "genesis-file-location": genesis_loc,
            },
        }

        if is_validator:
            config["authority-key-pair"] = {"value": secrets.get("authority_key", "")}
            config["protocol-key-pair"] = {"value": secrets.get("protocol_key", "")}
            config["account-key-pair"] = {"value": secrets.get("account_key", "")}
            config["consensus-config"] = {
                "db-path": "/app/consensus_db",
            }
        else:
            config["json-rpc-address"] = f"0.0.0.0:{node.ports['json_rpc']}"

        return config

    def _validate_rendered_config(self, config: Dict[str, Any], node: CommitteeNode) -> None:
        """Enforces schema compliance and rejects loopback external addresses."""
        for key in config:
            if key not in NODE_CONFIG_KEYS:
                raise ConfigValidationError(f"Invalid NodeConfig key in {node.name}.yaml: '{key}'")

        is_validator = node.role == "validator"
        req = REQUIRED_VALIDATOR_KEYS if is_validator else REQUIRED_FULLNODE_KEYS
        missing = req - set(config.keys())
        if missing:
            raise ConfigValidationError(f"Node {node.name} missing required keys: {missing}")

        # Validate P2P config
        p2p = config.get("p2p-config")
        if not isinstance(p2p, dict):
            raise ConfigValidationError(f"{node.name}: missing p2p-config section")

        for key in p2p:
            if key not in P2P_CONFIG_KEYS:
                raise ConfigValidationError(f"Invalid P2P key in {node.name}: '{key}'")

        listen = p2p.get("listen-address", "")
        if not listen.startswith("0.0.0.0:"):
            raise ConfigValidationError(f"{node.name}: p2p listen-address must bind 0.0.0.0, got '{listen}'")

        ext = p2p.get("external-address", "")
        if "127.0.0.1" in ext or "localhost" in ext:
            raise ConfigValidationError(f"{node.name}: external-address cannot be loopback: '{ext}'")

        validate_announced(ext, expected_ip=node.ip, proto="udp", suffix="quic", what=f"{node.name} P2P external")

        for sp in p2p.get("seed-peers", []):
            for k in sp:
                if k not in SEED_PEER_KEYS:
                    raise ConfigValidationError(f"Invalid seed-peer key in {node.name}: '{k}'")
            sp_addr = sp.get("address", "")
            if "127.0.0.1" in sp_addr or "localhost" in sp_addr:
                raise ConfigValidationError(f"{node.name}: seed-peer address cannot be loopback: '{sp_addr}'")
