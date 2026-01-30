# fogbed_iota/client/rpc_client.py

"""
Cliente JSON-RPC para IOTA 1.15

Implementa endpoints oficiais da API JSON-RPC
"""

import asyncio
import json
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass

import requests
import aiohttp

from fogbed_iota.utils import get_logger
from fogbed_iota.client.exceptions import (
    IotaRpcError,
    IotaConnectionError,
    IotaTimeoutError,
)

logger = get_logger("client.rpc")


@dataclass
class RpcResponse:
    """Resposta de chamada RPC"""

    result: Any
    id: int
    jsonrpc: str = "2.0"


class IotaRpcClient:
    """
    Cliente síncrono JSON-RPC para IOTA 1.15

    Exemplos de uso:
        >>> client = IotaRpcClient("http://10.0.0.1:9000")
        >>> balance = client.get_balance("0xADDRESS")
        >>> tx = client.get_transaction_block("0xDIGEST")
    """

    def __init__(
        self,
        endpoint: str,
        timeout: int = 30,
        headers: Optional[Dict[str, str]] = None,
    ):
        """
        Inicializa cliente RPC

        Args:
            endpoint: URL do fullnode RPC (ex: http://10.0.0.1:9000)
            timeout: Timeout em segundos
            headers: Headers HTTP customizados
        """
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.headers = headers or {"Content-Type": "application/json"}
        self._request_id = 0
        logger.info(f"IotaRpcClient initialized: {self.endpoint}")

    def _next_id(self) -> int:
        """Gera próximo request ID"""
        self._request_id += 1
        return self._request_id

    def _call(self, method: str, params: List[Any]) -> Any:
        """
        Executa chamada JSON-RPC

        Args:
            method: Nome do método RPC
            params: Lista de parâmetros

        Returns:
            Resultado da chamada

        Raises:
            IotaRpcError: Erro retornado pelo servidor
            IotaConnectionError: Erro de conexão
            IotaTimeoutError: Timeout
        """
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params,
        }

        logger.debug(f"RPC call: {method} with params: {params}")

        try:
            response = requests.post(
                self.endpoint,
                json=payload,
                headers=self.headers,
                timeout=self.timeout,
            )
            response.raise_for_status()  
            data = response.json()
            
            if "error" in data:
                error = data["error"]
                raise IotaRpcError(
                    code=error.get("code", -1),
                    message=error.get("message", "Unknown error"),
                    data=error.get("data"),
                )

            return data.get("result")

        except requests.exceptions.Timeout:
            raise IotaTimeoutError(f"Request timeout after {self.timeout}s")
        except requests.exceptions.ConnectionError as e:
            raise IotaConnectionError(f"Connection failed: {e}") 
        except requests.exceptions.RequestException as e:
            raise IotaConnectionError(f"Request failed: {e}")

    # ==================== Coin Query API ====================

    def get_balance(
        self, address: str, coin_type: str = "0x2::iota::IOTA"
    ) -> Dict[str, Any]:
        """
        Obtém saldo de um tipo de coin

        Args:
            address: Endereço IOTA
            coin_type: Tipo do coin (default: IOTA nativo)

        Returns:
            Dict com coinType, coinObjectCount, totalBalance
        """
        return self._call("iotax_getBalance", [address, coin_type])

    def get_all_balances(self, address: str) -> List[Dict[str, Any]]:
        """
        Obtém saldos de todos os tipos de coin

        Args:
            address: Endereço IOTA

        Returns:
            Lista de balances (coinType, coinObjectCount, totalBalance)
        """
        return self._call("iotax_getAllBalances", [address])

    def get_coins(
        self,
        address: str,
        coin_type: str = "0x2::iota::IOTA",
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        Obtém coins de um tipo específico

        Args:
            address: Endereço IOTA
            coin_type: Tipo do coin
            cursor: Cursor de paginação
            limit: Limite de resultados

        Returns:
            Dict com data, nextCursor, hasNextPage
        """
        return self._call("iotax_getCoins", [address, coin_type, cursor, limit])

    def get_coin_metadata(self, coin_type: str) -> Dict[str, Any]:
        """
        Obtém metadados de um coin

        Args:
            coin_type: Tipo do coin

        Returns:
            Dict com decimals, name, symbol, description, iconUrl, id
        """
        return self._call("iotax_getCoinMetadata", [coin_type])

    # ==================== Read API ====================

    def get_chain_identifier(self) -> str:
        """
        Obtém identificador da chain (primeiros 4 bytes do genesis digest)

        Returns:
            Chain identifier (ex: "4c78adac")
        """
        return self._call("iota_getChainIdentifier", [])

    def get_checkpoint(self, checkpoint_id: Union[str, int]) -> Dict[str, Any]:
        """
        Obtém dados de um checkpoint

        Args:
            checkpoint_id: Número ou digest do checkpoint

        Returns:
            Checkpoint completo
        """
        return self._call("iota_getCheckpoint", [str(checkpoint_id)])

    def get_latest_checkpoint_sequence_number(self) -> int:
        """
        Obtém sequence number do último checkpoint

        Returns:
            Sequence number
        """
        return int(self._call("iota_getLatestCheckpointSequenceNumber", []))

    def get_object(
        self, object_id: str, options: Optional[Dict[str, bool]] = None
    ) -> Dict[str, Any]:
        """
        Obtém dados de um objeto

        Args:
            object_id: ID do objeto
            options: Opções de visualização (showType, showOwner, showContent, etc)

        Returns:
            IotaObjectResponse
        """
        if options is None:
            options = {
                "showType": True,
                "showOwner": True,
                "showContent": True,
            }
        return self._call("iota_getObject", [object_id, options])

    def get_transaction_block(
        self, digest: str, options: Optional[Dict[str, bool]] = None
    ) -> Dict[str, Any]:
        """
        Obtém dados de uma transação

        Args:
            digest: Digest da transação
            options: Opções de visualização

        Returns:
            TransactionBlockResponse
        """
        if options is None:
            options = {
                "showInput": True,
                "showEffects": True,
                "showEvents": True,
            }
        return self._call("iota_getTransactionBlock", [digest, options])

    def get_events(self, tx_digest: str) -> List[Dict[str, Any]]:
        """
        Obtém eventos de uma transação

        Args:
            tx_digest: Digest da transação

        Returns:
            Lista de eventos
        """
        return self._call("iota_getEvents", [tx_digest])

    # ==================== Write API ====================

    def execute_transaction_block(
        self,
        tx_bytes: str,
        signatures: List[str],
        options: Optional[Dict[str, bool]] = None,
        request_type: str = "WaitForLocalExecution",
    ) -> Dict[str, Any]:
        """
        Executa transaction block

        Args:
            tx_bytes: Transaction serializada (base64)
            signatures: Lista de assinaturas
            options: Opções de resposta
            request_type: Tipo de requisição (WaitForLocalExecution, etc)

        Returns:
            TransactionBlockResponse
        """
        if options is None:
            options = {"showEffects": True, "showEvents": True}

        return self._call(
            "iota_executeTransactionBlock",
            [tx_bytes, signatures, options, request_type],
        )

    def dry_run_transaction_block(self, tx_bytes: str) -> Dict[str, Any]:
        """
        Executa dry run de transação

        Args:
            tx_bytes: Transaction serializada (base64)

        Returns:
            DryRunTransactionBlockResponse
        """
        return self._call("iota_dryRunTransactionBlock", [tx_bytes])

    # ==================== Extended API (requer indexer) ====================

    def query_events(
        self,
        query: Dict[str, Any],
        cursor: Optional[Dict[str, str]] = None,
        limit: int = 50,
        descending_order: bool = False,
    ) -> Dict[str, Any]:
        """
        Query de eventos (requer indexer)

        Args:
            query: Query filter (ex: {"MoveModule": {"package": "0x...", "module": "..."}})
            cursor: Cursor de paginação
            limit: Limite de resultados
            descending_order: Ordem descendente

        Returns:
            EventPage com data, nextCursor, hasNextPage
        """
        return self._call(
            "iotax_queryEvents", [query, cursor, limit, descending_order]
        )

    def query_transaction_blocks(
        self,
        query: Dict[str, Any],
        cursor: Optional[str] = None,
        limit: int = 50,
        descending_order: bool = False,
    ) -> Dict[str, Any]:
        """
        Query de transaction blocks (requer indexer)

        Args:
            query: Query filter
            cursor: Cursor de paginação
            limit: Limite de resultados
            descending_order: Ordem descendente

        Returns:
            TransactionBlocksPage
        """
        return self._call(
            "iotax_queryTransactionBlocks", [query, cursor, limit, descending_order]
        )

    def get_owned_objects(
        self,
        address: str,
        query: Optional[Dict[str, Any]] = None,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        Obtém objetos pertencentes a um endereço

        Args:
            address: Endereço IOTA
            query: Filtro opcional
            cursor: Cursor de paginação
            limit: Limite de resultados

        Returns:
            ObjectsPage
        """
        return self._call("iotax_getOwnedObjects", [address, query, cursor, limit])

    # ==================== Governance API ====================

    def get_reference_gas_price(self) -> int:
        """
        Obtém preço de referência do gas

        Returns:
            Gas price em MIST
        """
        return int(self._call("iotax_getReferenceGasPrice", []))

    def get_validators_apy(self) -> Dict[str, Any]:
        """
        Obtém APY dos validadores

        Returns:
            Dict com apys (lista) e epoch
        """
        return self._call("iotax_getValidatorsApy", [])

    def get_stakes(self, address: str) -> List[Dict[str, Any]]:
        """
        Obtém stakes de um endereço

        Args:
            address: Endereço do staker

        Returns:
            Lista de DelegatedStake
        """
        return self._call("iotax_getStakes", [address])

    def get_committee_info(self, epoch: Optional[int] = None) -> Dict[str, Any]:
        """
        Obtém informações do comitê

        Args:
            epoch: Epoch (None = current)

        Returns:
            CommitteeInfo
        """
        params = [str(epoch)] if epoch is not None else []
        return self._call("iotax_getCommitteeInfo", params)

    # ==================== Utilities ====================

    def health_check(self) -> bool:
        """
        Verifica se nó está saudável

        Returns:
            True se nó responde
        """
        try:
            self.get_chain_identifier()
            return True
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False


class AsyncIotaRpcClient:
    """
    Cliente assíncrono JSON-RPC para IOTA 1.15

    Usa aiohttp para operações assíncronas
    """

    def __init__(
        self,
        endpoint: str,
        timeout: int = 30,
        headers: Optional[Dict[str, str]] = None,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.headers = headers or {"Content-Type": "application/json"}
        self._request_id = 0
        self._session: Optional[aiohttp.ClientSession] = None
        logger.info(f"AsyncIotaRpcClient initialized: {self.endpoint}")

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def __aenter__(self):
        """Context manager entry"""
        self._session = aiohttp.ClientSession(
            headers=self.headers, timeout=self.timeout
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        if self._session:
            await self._session.close()

    async def _call(self, method: str, params: List[Any]) -> Any:
        """Executa chamada JSON-RPC assíncrona"""
        if not self._session:
            raise IotaConnectionError("Session not initialized (use async with)")

        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params,
        }

        logger.debug(f"Async RPC call: {method}")

        try:
            async with self._session.post(self.endpoint, json=payload) as response:
                response.raise_for_status()
                data = await response.json()

                if "error" in data:
                    error = data["error"]
                    raise IotaRpcError(
                        code=error.get("code", -1),
                        message=error.get("message", "Unknown error"),
                        data=error.get("data"),
                    )

                return data.get("result")

        except asyncio.TimeoutError:
            raise IotaTimeoutError(f"Request timeout")
        except aiohttp.ClientError as e:
            raise IotaConnectionError(f"Request failed: {e}")

    # Métodos assíncronos (mesma interface do cliente síncrono)

    async def get_balance(
        self, address: str, coin_type: str = "0x2::iota::IOTA"
    ) -> Dict[str, Any]:
        return await self._call("iotax_getBalance", [address, coin_type])

    async def get_all_balances(self, address: str) -> List[Dict[str, Any]]:
        return await self._call("iotax_getAllBalances", [address])

    async def get_chain_identifier(self) -> str:
        return await self._call("iota_getChainIdentifier", [])

    async def get_checkpoint(self, checkpoint_id: Union[str, int]) -> Dict[str, Any]:
        return await self._call("iota_getCheckpoint", [str(checkpoint_id)])

    async def get_object(
        self, object_id: str, options: Optional[Dict[str, bool]] = None
    ) -> Dict[str, Any]:
        if options is None:
            options = {"showType": True, "showOwner": True, "showContent": True}
        return await self._call("iota_getObject", [object_id, options])

    async def health_check(self) -> bool:
        try:
            await self.get_chain_identifier()
            return True
        except Exception:
            return False
