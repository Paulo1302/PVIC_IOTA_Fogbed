# tests/unit/test_network_facade.py

import pytest
from unittest.mock import MagicMock, patch
from fogbed_iota.network import IotaNetwork
from fogbed_iota.models.iota_node import NodeRole

@pytest.fixture
def mock_fogbed_exp():
    exp = MagicMock()
    exp.add_docker.return_value = MagicMock()
    exp.add_virtual_instance.return_value = MagicMock()
    return exp

def test_iota_network_initialization(mock_fogbed_exp):
    network = IotaNetwork(mock_fogbed_exp)
    
    assert network.exp == mock_fogbed_exp
    assert len(network.nodes) == 0
    assert network.client_container is None

def test_add_validator(mock_fogbed_exp):
    network = IotaNetwork(mock_fogbed_exp)
    
    node = network.add_validator("val1", "10.0.0.1")
    
    assert len(network.nodes) == 1
    assert node.name == "val1"
    assert node.role == "validator"

def test_add_fullnode(mock_fogbed_exp):
    network = IotaNetwork(mock_fogbed_exp)
    
    node = network.add_gateway("full1", "10.0.0.2")
    
    assert len(network.nodes) == 1
    assert node.name == "full1"
    assert node.role == "fullnode"

def test_add_client(mock_fogbed_exp):
    network = IotaNetwork(mock_fogbed_exp)
    
    client = MagicMock()
    client.name = "mn.client1"
    network.set_client(client)
    
    assert network.client_container is not None
    assert network.client_container.name == "mn.client1"

@patch("fogbed_iota.network.ensure_iota_binary")
@patch("fogbed_iota.network.generate_genesis")
@patch("fogbed_iota.network.prepare_configs")
@patch("fogbed_iota.network.inject_and_boot")
@patch("fogbed_iota.network.wait_for_network_ready")
def test_start_network(
    mock_wait,
    mock_inject,
    mock_prepare,
    mock_genesis,
    mock_ensure,
    mock_fogbed_exp
):
    network = IotaNetwork(mock_fogbed_exp)
    network.add_validator("val1", "10.0.0.1")
    
    # Mocking internal setup
    network._configure_client = MagicMock()
    network._setup_smart_contract_env = MagicMock()
    network._print_network_summary = MagicMock()
    
    network.start()
    
    mock_ensure.assert_called_once()
    mock_genesis.assert_called_once()
    mock_prepare.assert_called_once()
    mock_inject.assert_called_once()
    mock_wait.assert_called_once()
    network._configure_client.assert_called_once()
    network._setup_smart_contract_env.assert_called_once()
