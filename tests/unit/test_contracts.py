# tests/unit/test_contracts.py

import pytest
from unittest.mock import MagicMock, patch
from fogbed_iota.contracts.manager import SmartContractManager
from fogbed_iota.models.package import MovePackage

@pytest.fixture
def mock_cli():
    cli = MagicMock()
    # Mocking as IotaCLI type check might pass if we patch it or if it just has .container
    cli.container = MagicMock()
    return cli

@pytest.fixture
def mock_account_manager():
    return MagicMock()

def test_contract_manager_initialization(mock_cli, mock_account_manager):
    manager = SmartContractManager(mock_cli, mock_account_manager)
    assert manager.accounts == mock_account_manager
    assert manager.client == mock_cli

@patch("fogbed_iota.contracts.manager.SmartContractManager._extract_publish_metadata")
def test_contract_manager_publish(mock_extract, mock_cli, mock_account_manager):
    manager = SmartContractManager(mock_cli, mock_account_manager)
    
    # Mocking return values
    manager.executor.run_raw_publish = MagicMock()
    manager.executor.run_raw_publish.return_value = {"some": "json"}
    
    mock_pkg = MovePackage("0xPKG123", "contract", [], "digest", "0xSENDER")
    mock_extract.return_value = mock_pkg
    
    manager.accounts.get_account.return_value = MagicMock(address="0xSENDER")
    manager.accounts.get_balance.return_value = 1000000000
    
    package = manager.publish_package("/path/to/contract", "alice")
    
    assert isinstance(package, MovePackage)
    assert package.package_id == "0xPKG123"
    manager.executor.run_raw_publish.assert_called_once()

def test_contract_manager_call(mock_cli, mock_account_manager):
    manager = SmartContractManager(mock_cli, mock_account_manager)
    
    manager.accounts.get_account.return_value = MagicMock(address="0xSENDER")
    
    # Mock call result
    manager.executor.run_raw_call = MagicMock()
    manager.executor.run_raw_call.return_value = {"effects": {"status": {"status": "success"}}}
    
    result = manager.call_function("0xPKG123", "test", "my_func", "alice")
    
    assert result["effects"]["status"]["status"] == "success"
    manager.executor.run_raw_call.assert_called_once()
