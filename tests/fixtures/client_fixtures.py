# tests/fixtures/client_fixtures.py

"""
Fixtures para testes de cliente IOTA
"""

import pytest
from typing import Dict, Any
from unittest.mock import Mock


@pytest.fixture
def mock_rpc_endpoint():
    """Endpoint RPC de teste"""
    return "http://localhost:9000"


@pytest.fixture
def mock_graphql_endpoint():
    """Endpoint GraphQL de teste"""
    return "https://graphql.testnet.iota.cafe"


@pytest.fixture
def test_address():
    """Endereço IOTA de teste"""
    return "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"


@pytest.fixture
def test_tx_digest():
    """Digest de transação de teste"""
    return "AaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPpQqRrSsTtUuVvWwXxYyZz0123456789AB"


@pytest.fixture
def test_object_id():
    """Object ID de teste"""
    return "0xabcd1234567890abcdef1234567890abcdef1234567890abcdef1234567890"


@pytest.fixture
def mock_rpc_response():
    """Factory para criar resposta RPC mockada"""
    def _mock_response(result: Any) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "result": result
        }
    return _mock_response


@pytest.fixture
def mock_rpc_error():
    """Factory para criar erro RPC mockado"""
    def _mock_error(code: int, message: str, data: Any = None) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {
                "code": code,
                "message": message,
                "data": data
            }
        }
    return _mock_error


@pytest.fixture
def mock_balance_response():
    """Resposta de balance mockada"""
    return {
        "coinType": "0x2::iota::IOTA",
        "coinObjectCount": 5,
        "totalBalance": "1000000000",
        "lockedBalance": {}
    }


@pytest.fixture
def mock_transaction_response(test_tx_digest, test_address):
    """Resposta de transação mockada"""
    return {
        "digest": test_tx_digest,
        "transaction": {
            "data": {
                "sender": test_address,
                "gasPayment": {"objectId": "0xGAS123"}
            }
        },
        "effects": {
            "status": {"status": "success"},
            "gasUsed": {
                "computationCost": "1000",
                "storageCost": "2000",
                "storageRebate": "500"
            }
        },
        "events": []
    }


@pytest.fixture
def mock_checkpoint_response():
    """Resposta de checkpoint mockada"""
    return {
        "epoch": "100",
        "sequenceNumber": "5000",
        "digest": "ABC123CHECKPOINT",
        "networkTotalTransactions": "10000",
        "previousDigest": "ABC122CHECKPOINT",
        "timestampMs": "1234567890000"
    }


@pytest.fixture
def mock_coins_page(test_address):
    """Página de coins mockada com paginação"""
    return {
        "data": [
            {
                "coinType": "0x2::iota::IOTA",
                "coinObjectId": "0xCOIN001",
                "version": "1",
                "digest": "COIN001DIGEST",
                "balance": "100000000",
                "previousTransaction": "TX001"
            },
            {
                "coinType": "0x2::iota::IOTA",
                "coinObjectId": "0xCOIN002",
                "version": "1",
                "digest": "COIN002DIGEST",
                "balance": "200000000",
                "previousTransaction": "TX002"
            }
        ],
        "nextCursor": "cursor_abc123",
        "hasNextPage": True
    }


@pytest.fixture
def mock_graphql_response():
    """Factory para criar resposta GraphQL mockada"""
    def _mock_graphql(data: Dict[str, Any]) -> Dict[str, Any]:
        return {"data": data}
    return _mock_graphql


@pytest.fixture
def mock_graphql_error():
    """Factory para criar erro GraphQL mockado"""
    def _mock_error(message: str, locations: list = None) -> Dict[str, Any]:
        error = {"message": message}
        if locations:
            error["locations"] = locations
        return {"errors": [error]}
    return _mock_error
