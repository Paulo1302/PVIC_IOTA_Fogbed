# tests/fixtures/node_fixtures.py

"""
Fixtures para testes de nós IOTA
"""

import pytest
from fogbed_iota.models.iota_node import (
    IotaNodeConfig,
    NodeRole,
    NodeType,
    ValidatorNode,
    FullnodeNode,
)


@pytest.fixture
def validator_config():
    """Configuração de validador de teste"""
    return IotaNodeConfig(
        name="validator1",
        ip="10.0.0.1",
        role=NodeRole.VALIDATOR,
        port_offset=0,
        image="iota-dev:latest"
    )


@pytest.fixture
def fullnode_config():
    """Configuração de fullnode de teste"""
    return IotaNodeConfig(
        name="fullnode1",
        ip="10.0.0.2",
        role=NodeRole.FULLNODE,
        port_offset=1,
        image="iota-dev:latest"
    )


@pytest.fixture
def consensus_validator_config():
    """Configuração de consensus validator"""
    return IotaNodeConfig(
        name="consensus1",
        ip="10.0.0.3",
        role=NodeRole.VALIDATOR,
        node_type=NodeType.CONSENSUS_VALIDATOR,
        port_offset=2,
    )


@pytest.fixture
def validator_node(validator_config):
    """Nó validador de teste"""
    return ValidatorNode(config=validator_config)


@pytest.fixture
def fullnode_node(fullnode_config):
    """Nó fullnode de teste"""
    return FullnodeNode(config=fullnode_config)
