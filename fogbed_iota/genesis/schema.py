"""IOTA v1.33.1 node-config schema (key names only), used to reject unknown / legacy keys.

``NodeConfig`` does not use ``deny_unknown_fields``, so a legacy template (e.g. the pre-1.33
``node:`` / ``consensus:`` layout) would be silently ignored by ``iota-node`` and the node would
run with random keys and default addresses. We therefore validate every rendered YAML against
the exact key sets extracted from the release source:

  * ``NodeConfig``      crates/iota-config/src/node.rs   (tag v1.33.1, commit 97b1057f8de0)
  * ``ConsensusConfig`` crates/iota-config/src/node.rs
  * ``P2pConfig``       crates/iota-config/src/p2p.rs
  * ``SeedPeer``        crates/iota-config/src/p2p.rs
  * ``Genesis``         flattened ``genesis-file-location`` (node.rs ``GenesisLocation::File``)
"""

from __future__ import annotations

NODE_CONFIG_KEYS = frozenset(
    {
        "authority-key-pair", "protocol-key-pair", "account-key-pair", "network-key-pair",
        "db-path", "network-address", "json-rpc-address", "metrics-address",
        "admin-interface-address", "consensus-config", "enable-index-processing",
        "jsonrpc-server-type", "grpc-load-shed", "grpc-concurrency-limit-per-core",
        "p2p-config", "genesis", "migration-tx-data-path", "authority-store-pruning-config",
        "end-of-epoch-broadcast-channel-capacity", "checkpoint-executor-config", "metrics",
        "supported-protocol-versions", "expensive-safety-check-config",
        "transaction-deny-config", "certificate-deny-config", "state-debug-dump-config",
        "checkpoint-archive-config", "state-snapshot-write-config", "indexer-max-subscriptions",
        "transaction-kv-store-read-config", "transaction-kv-store-write-config",
        "authority-overload-config", "run-with-range", "policy-config", "firewall-config",
        "execution-cache-config", "full-checkpoint-contents-cache-size-mb",
        "enable-validator-tx-finalizer", "enable-soft-locking", "verifier-signing-config",
        "enable-db-write-stall", "iota-names-config", "enable-grpc-api", "grpc-api-config",
        "chain-override-for-testing", "validator-client-monitor-config",
    }
)

CONSENSUS_CONFIG_KEYS = frozenset(
    {
        "db-path", "db-retention-epochs", "db-pruner-period-secs", "max-pending-transactions",
        "max-submit-position", "submit-delay-step-override-millis", "parameters",
        "graduated-load-shedding-soft-limit-pct",
    }
)

P2P_CONFIG_KEYS = frozenset(
    {
        "listen-address", "external-address", "seed-peers", "anemo-config", "state-sync",
        "discovery", "randomness", "excessive-message-size",
    }
)

SEED_PEER_KEYS = frozenset({"peer-id", "address"})
GENESIS_KEYS = frozenset({"genesis-file-location"})
KEY_PAIR_KEYS = frozenset({"value", "path"})

#: Keys of a pre-v1.33 template that must never reappear.
LEGACY_TOP_LEVEL_KEYS = frozenset({"node", "consensus", "rest-api-bind-address", "p2p-bind-address"})

#: Fields the fogbed templates are required to set explicitly.
REQUIRED_VALIDATOR_KEYS = frozenset(
    {
        "authority-key-pair", "protocol-key-pair", "account-key-pair", "network-key-pair",
        "db-path", "network-address", "metrics-address", "consensus-config", "p2p-config", "genesis",
    }
)
REQUIRED_FULLNODE_KEYS = frozenset(
    {"network-key-pair", "db-path", "network-address", "json-rpc-address", "metrics-address",
     "p2p-config", "genesis"}
)
