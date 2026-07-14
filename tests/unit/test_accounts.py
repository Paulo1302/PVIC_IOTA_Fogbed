# tests/unit/test_accounts.py

import pytest
from unittest.mock import MagicMock, patch
from fogbed_iota.accounts.manager import AccountManager
from fogbed_iota.models.account import IotaAccount

@pytest.fixture
def mock_cli_or_container():
    cli = MagicMock()
    # Mocking IotaCLI behavior
    cli.new_address.return_value = ["0x123", "word1 word2"]
    cli.get_gas.return_value = [{"balance": "1000", "coinObjectId": "0xc1"}]
    return cli

def test_account_manager_create_account(mock_cli_or_container):
    manager = AccountManager(mock_cli_or_container)
    
    with patch('fogbed_iota.accounts.manager.generate_keypair') as mock_gen:
        mock_gen.return_value = IotaAccount(address="0x123", alias="alice")
        account = manager.generate_account("alice")
        
        assert account.alias == "alice"
        assert account.address == "0x123"
        assert manager.get_account("alice") == account

def test_account_manager_get_balance(mock_cli_or_container):
    manager = AccountManager(mock_cli_or_container)
    
    with patch('fogbed_iota.accounts.manager.generate_keypair') as mock_gen:
        mock_gen.return_value = IotaAccount(address="0x123", alias="alice")
        manager.generate_account("alice")
    
    # Need to patch IotaCLI.get_gas
    manager.cli = MagicMock()
    manager.cli.get_gas.return_value = [{"balance": 1000, "coinObjectId": "0xc1"}]
    
    balance = manager.get_balance("alice")
    assert balance == 1000
    manager.cli.get_gas.assert_called_with("0x123")
