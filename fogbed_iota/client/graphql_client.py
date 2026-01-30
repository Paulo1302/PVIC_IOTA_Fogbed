# fogbed_iota/client/graphql_client.py

"""
Cliente GraphQL para IOTA 1.15

Alternativa moderna ao JSON-RPC usando GraphQL API
"""

from typing import Any, Dict, Optional
import requests

from fogbed_iota.utils import get_logger
from fogbed_iota.client.exceptions import (
    IotaGraphQLError,
    IotaConnectionError,
    IotaTimeoutError,
)

logger = get_logger("client.graphql")


class IotaGraphQLClient:
    """
    Cliente GraphQL para IOTA 1.15

    Usa a API GraphQL RPC 2.0 oficial (alternativa ao JSON-RPC)

    Exemplos:
        >>> client = IotaGraphQLClient("https://graphql.testnet.iota.cafe")
        >>> result = client.query('''
        ...   query {
        ...     chainIdentifier
        ...   }
        ... ''')
    """

    def __init__(
        self,
        endpoint: str,
        timeout: int = 30,
        headers: Optional[Dict[str, str]] = None,
    ):
        """
        Inicializa cliente GraphQL

        Args:
            endpoint: URL do endpoint GraphQL (ex: https://graphql.testnet.iota.cafe)
            timeout: Timeout em segundos
            headers: Headers HTTP customizados
        """
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.headers = headers or {"Content-Type": "application/json"}
        logger.info(f"IotaGraphQLClient initialized: {self.endpoint}")

    def query(
        self,
        query: str,
        variables: Optional[Dict[str, Any]] = None,
        operation_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executa query GraphQL

        Args:
            query: String da query GraphQL
            variables: Variáveis da query
            operation_name: Nome da operação (opcional)

        Returns:
            Resultado da query

        Raises:
            IotaGraphQLError: Erros retornados pelo servidor
            IotaConnectionError: Erro de conexão
        """
        payload = {"query": query}

        if variables:
            payload["variables"] = variables

        if operation_name:
            payload["operationName"] = operation_name

        logger.debug(f"GraphQL query: {query[:100]}...")

        try:
            response = requests.post(
                self.endpoint,
                json=payload,
                headers=self.headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                raise IotaGraphQLError(errors=data["errors"])

            return data.get("data", {})

        except requests.exceptions.Timeout:
            raise IotaTimeoutError(f"Request timeout after {self.timeout}s")
        except requests.exceptions.ConnectionError as e:
            raise IotaConnectionError(f"Connection failed: {e}")
        except requests.exceptions.RequestException as e:
            raise IotaConnectionError(f"Request failed: {e}")

    def get_chain_identifier(self) -> str:
        """Obtém chain identifier via GraphQL"""
        query = """
        query {
            chainIdentifier
        }
        """
        result = self.query(query)
        return result["chainIdentifier"]

    def get_transaction_block(self, digest: str) -> Dict[str, Any]:
        """Obtém transaction block via GraphQL"""
        query = """
        query GetTransaction($digest: String!) {
            transactionBlock(digest: $digest) {
                digest
                sender {
                    address
                }
                effects {
                    status
                    gasUsed {
                        computationCost
                        storageCost
                        storageRebate
                    }
                }
            }
        }
        """
        result = self.query(query, variables={"digest": digest})
        return result["transactionBlock"]

    def get_object(self, object_id: str) -> Dict[str, Any]:
        """Obtém objeto via GraphQL"""
        query = """
        query GetObject($id: IotaAddress!) {
            object(address: $id) {
                address
                version
                digest
                owner {
                    ... on AddressOwner {
                        owner {
                            address
                        }
                    }
                }
            }
        }
        """
        result = self.query(query, variables={"id": object_id})
        return result["object"]

    def health_check(self) -> bool:
        """Verifica se endpoint está saudável"""
        try:
            self.get_chain_identifier()
            return True
        except Exception as e:
            logger.warning(f"GraphQL health check failed: {e}")
            return False
