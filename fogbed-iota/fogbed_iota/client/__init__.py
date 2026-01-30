# fogbed_iota/client/__init__.py

"""
Cliente para interação com nós IOTA

Fornece abstrações para JSON-RPC e GraphQL
"""

from fogbed_iota.client.rpc_client import IotaRpcClient, AsyncIotaRpcClient
from fogbed_iota.client.graphql_client import IotaGraphQLClient
from fogbed_iota.client.exceptions import (
    IotaClientError,
    IotaRpcError,
    IotaGraphQLError,
    IotaConnectionError,
    IotaTimeoutError,
)

__all__ = [
    "IotaRpcClient",
    "AsyncIotaRpcClient",
    "IotaGraphQLClient",
    "IotaClientError",
    "IotaRpcError",
    "IotaGraphQLError",
    "IotaConnectionError",
    "IotaTimeoutError",
]
