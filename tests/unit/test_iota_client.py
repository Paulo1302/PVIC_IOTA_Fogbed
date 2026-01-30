# tests/unit/test_iota_client.py

"""
Testes unitários para cliente IOTA (RPC e GraphQL)
Testa funcionalidades principais com mocks
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, MagicMock
from fogbed_iota.client import (
    IotaRpcClient,
    AsyncIotaRpcClient,
    IotaGraphQLClient,
    IotaClientError,
    IotaRpcError,
    IotaGraphQLError,
    IotaConnectionError,
    IotaTimeoutError,
)


# ==================== Testes: IotaRpcClient (Síncrono) ====================

@pytest.mark.unit
class TestIotaRpcClient:
    """Testes para cliente RPC síncrono"""

    def test_client_initialization(self, mock_rpc_endpoint):
        """Testa inicialização do cliente"""
        client = IotaRpcClient(mock_rpc_endpoint)
        assert client.endpoint == mock_rpc_endpoint
        assert client.timeout == 30
        assert client.headers["Content-Type"] == "application/json"
        assert client._request_id == 0

    def test_client_initialization_with_custom_params(self):
        """Testa inicialização com parâmetros customizados"""
        custom_headers = {"Authorization": "Bearer token123"}
        client = IotaRpcClient(
            "http://custom:9000",
            timeout=60,
            headers=custom_headers
        )
        assert client.timeout == 60
        assert "Authorization" in client.headers

    def test_next_id_increments(self, mock_rpc_endpoint):
        """Testa incremento de request ID"""
        client = IotaRpcClient(mock_rpc_endpoint)
        assert client._next_id() == 1
        assert client._next_id() == 2
        assert client._next_id() == 3

    @patch('requests.post')
    def test_get_chain_identifier_success(
        self, mock_post, mock_rpc_endpoint, mock_rpc_response
    ):
        """Testa obtenção do chain identifier"""
        mock_post.return_value.json.return_value = mock_rpc_response("4c78adac")
        mock_post.return_value.raise_for_status = Mock()

        client = IotaRpcClient(mock_rpc_endpoint)
        result = client.get_chain_identifier()

        assert result == "4c78adac"
        mock_post.assert_called_once()

        # Verifica payload enviado
        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        assert payload["method"] == "iota_getChainIdentifier"
        assert payload["params"] == []

    @patch('requests.post')
    def test_get_balance_success(
        self, mock_post, mock_rpc_endpoint, mock_rpc_response,
        test_address, mock_balance_response
    ):
        """Testa obtenção de saldo"""
        mock_post.return_value.json.return_value = mock_rpc_response(mock_balance_response)
        mock_post.return_value.raise_for_status = Mock()

        client = IotaRpcClient(mock_rpc_endpoint)
        result = client.get_balance(test_address)

        assert result["totalBalance"] == "1000000000"
        assert result["coinObjectCount"] == 5

        # Verifica parâmetros
        payload = mock_post.call_args[1]["json"]
        assert payload["method"] == "iotax_getBalance"
        assert payload["params"][0] == test_address

    @patch('requests.post')
    def test_get_coins_with_pagination(
        self, mock_post, mock_rpc_endpoint, mock_rpc_response,
        test_address, mock_coins_page
    ):
        """Testa obtenção de coins com paginação"""
        mock_post.return_value.json.return_value = mock_rpc_response(mock_coins_page)
        mock_post.return_value.raise_for_status = Mock()

        client = IotaRpcClient(mock_rpc_endpoint)
        result = client.get_coins(test_address, limit=2)

        assert len(result["data"]) == 2
        assert result["hasNextPage"] is True
        assert result["nextCursor"] == "cursor_abc123"

    @patch('requests.post')
    def test_get_checkpoint(
        self, mock_post, mock_rpc_endpoint, mock_rpc_response,
        mock_checkpoint_response
    ):
        """Testa obtenção de checkpoint"""
        mock_post.return_value.json.return_value = mock_rpc_response(mock_checkpoint_response)
        mock_post.return_value.raise_for_status = Mock()

        client = IotaRpcClient(mock_rpc_endpoint)
        result = client.get_checkpoint(5000)

        assert result["sequenceNumber"] == "5000"
        assert result["epoch"] == "100"

    @patch('requests.post')
    def test_get_transaction_block(
        self, mock_post, mock_rpc_endpoint, mock_rpc_response,
        test_tx_digest, mock_transaction_response
    ):
        """Testa obtenção de transaction block"""
        mock_post.return_value.json.return_value = mock_rpc_response(mock_transaction_response)
        mock_post.return_value.raise_for_status = Mock()

        client = IotaRpcClient(mock_rpc_endpoint)
        result = client.get_transaction_block(test_tx_digest)

        assert result["digest"] == test_tx_digest
        assert result["effects"]["status"]["status"] == "success"

    @patch('requests.post')
    def test_rpc_error_handling(
        self, mock_post, mock_rpc_endpoint, mock_rpc_error
    ):
        """Testa tratamento de erros RPC"""
        mock_post.return_value.json.return_value = mock_rpc_error(
            -32602, "Invalid params"
        )
        mock_post.return_value.raise_for_status = Mock()

        client = IotaRpcClient(mock_rpc_endpoint)

        with pytest.raises(IotaRpcError) as exc_info:
            client.get_chain_identifier()

        assert exc_info.value.code == -32602
        assert "Invalid params" in exc_info.value.message

    @patch('requests.post')
    def test_connection_error_handling(self, mock_post, mock_rpc_endpoint):
        """Testa tratamento de erro de conexão"""
        import requests
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

        client = IotaRpcClient(mock_rpc_endpoint)

        with pytest.raises(IotaConnectionError) as exc_info:
            client.get_chain_identifier()

        assert "Connection failed" in str(exc_info.value)

    @patch('requests.post')
    def test_health_check_success(
        self, mock_post, mock_rpc_endpoint, mock_rpc_response
    ):
        """Testa health check bem-sucedido"""
        mock_post.return_value.json.return_value = mock_rpc_response("4c78adac")
        mock_post.return_value.raise_for_status = Mock()

        client = IotaRpcClient(mock_rpc_endpoint)
        assert client.health_check() is True


# ==================== Testes: AsyncIotaRpcClient ====================

@pytest.mark.unit
@pytest.mark.asyncio
class TestAsyncIotaRpcClient:
    """Testes para cliente RPC assíncrono"""

    async def test_client_initialization(self, mock_rpc_endpoint):
        """Testa inicialização do cliente assíncrono"""
        client = AsyncIotaRpcClient(mock_rpc_endpoint)
        assert client.endpoint == mock_rpc_endpoint
        assert client._session is None


# ==================== Testes: IotaGraphQLClient ====================

@pytest.mark.unit
class TestIotaGraphQLClient:
    """Testes para cliente GraphQL"""

    def test_client_initialization(self, mock_graphql_endpoint):
        """Testa inicialização do cliente GraphQL"""
        client = IotaGraphQLClient(mock_graphql_endpoint)
        assert client.endpoint == mock_graphql_endpoint
        assert client.timeout == 30

    @patch('requests.post')
    def test_query_success(self, mock_post, mock_graphql_endpoint, mock_graphql_response):
        """Testa query GraphQL bem-sucedida"""
        mock_post.return_value.json.return_value = mock_graphql_response(
            {"chainIdentifier": "4c78adac"}
        )
        mock_post.return_value.raise_for_status = Mock()

        client = IotaGraphQLClient(mock_graphql_endpoint)
        result = client.query("query { chainIdentifier }")

        assert result["chainIdentifier"] == "4c78adac"


# ==================== Testes: IOTA 1.15 Específico ====================

@pytest.mark.unit
class TestIota15RpcClient:
    """Testes específicos IOTA 1.15"""

    @patch('requests.post')
    def test_latest_checkpoint_sequence_success(
        self, mock_post, mock_rpc_endpoint, mock_rpc_response
    ):
        """Testa último checkpoint sequence"""
        mock_post.return_value.json.return_value = mock_rpc_response(5000)
        mock_post.return_value.raise_for_status = Mock()

        client = IotaRpcClient(mock_rpc_endpoint)
        result = client.get_latest_checkpoint_sequence_number()

        assert result == 5000
        mock_post.assert_called_once()

    @patch('requests.post')
    def test_latest_checkpoint_success(
        self, mock_post, mock_rpc_endpoint, mock_checkpoint_response, mock_rpc_response
    ):
        """Testa último checkpoint completo"""
        mock_post.return_value.json.return_value = mock_rpc_response(mock_checkpoint_response)
        mock_post.return_value.raise_for_status = Mock()

        client = IotaRpcClient(mock_rpc_endpoint)
        result = client.get_checkpoint(5000)

        assert result["sequenceNumber"] == "5000"
        assert result["epoch"] == "100"
        
        mock_post.assert_called_once()

    @patch('requests.post')
    def test_owned_objects_success(
        self, mock_post, mock_rpc_endpoint, mock_rpc_response, test_address
    ):
        """Testa objetos de owner"""
        mock_response = {
            "data": [{"objectId": "obj1", "type": "0x2::iota::IOTA"}],
            "hasNextPage": False
        }
        mock_post.return_value.json.return_value = mock_rpc_response(mock_response)
        mock_post.return_value.raise_for_status = Mock()

        client = IotaRpcClient(mock_rpc_endpoint)
        result = client.get_owned_objects(test_address)

        assert len(result["data"]) == 1

    @patch('requests.post')
    def test_get_object_success(
        self, mock_post, mock_rpc_endpoint, mock_rpc_response
    ):
        """Testa objeto específico"""
        mock_obj = {
            "data": {
                "objectId": "0xABC123",
                "type": "0x2::coin::Coin<0x2::iota::IOTA>",
                "balance": "1000000"
            }
        }
        mock_post.return_value.json.return_value = mock_rpc_response(mock_obj)
        mock_post.return_value.raise_for_status = Mock()

        client = IotaRpcClient(mock_rpc_endpoint)
        result = client.get_object("0xABC123")

        assert result["data"]["objectId"] == "0xABC123"

    @patch('requests.post')
    def test_protocol_version_success(
        self, mock_post, mock_rpc_endpoint, mock_rpc_response
    ):
        """Testa versão do protocolo"""
        mock_post.return_value.json.return_value = mock_rpc_response("1.15.0")
        mock_post.return_value.raise_for_status = Mock()

        client = IotaRpcClient(mock_rpc_endpoint)
        result = client.get_protocol_version()

        assert result == "1.15.0"

    @patch('requests.post')
    def test_get_events_success(
        self, mock_post, mock_rpc_endpoint, mock_rpc_response
    ):
        """Testa eventos"""
        mock_events = {
            "data": [{"txDigest": "tx123", "event": {"type": "Transfer"}}],
            "hasNextPage": False
        }
        mock_post.return_value.json.return_value = mock_rpc_response(mock_events)
        mock_post.return_value.raise_for_status = Mock()

        client = IotaRpcClient(mock_rpc_endpoint)
        query = {"TransactionDigest": "tx123"}
        result = client.get_events(query)

        assert len(result["data"]) == 1
