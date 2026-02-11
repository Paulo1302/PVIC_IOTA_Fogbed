# fogbed_iota/client/exceptions.py

"""
Exceções específicas do cliente IOTA

Compatível com:
- rpc_client.py  (IotaRpcError, IotaConnectionError, IotaTimeoutError, IotaGraphQLError)
- cli.py         (IotaClientException, TransactionFailedException, etc.)
"""


# ==== Base genérica ====

class IotaClientError(Exception):
    """Erro genérico do cliente IOTA (base antiga)"""
    pass


class IotaClientException(Exception):
    """Exceção base para erros do cliente IOTA (base nova)"""
    pass


# ==== Exceções usadas pelo rpc_client.py ====

class IotaRpcError(IotaClientError):
    """Erro retornado pelo servidor IOTA via JSON-RPC"""
    def __init__(self, code: int, message: str, data: dict = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"RPC Error {code}: {message}")


class IotaConnectionError(IotaClientError):
    """Erro de conexão com o nó IOTA"""
    pass


class IotaTimeoutError(IotaClientError):
    """Timeout na comunicação com o nó"""
    pass


class IotaGraphQLError(IotaClientError):
    """Erro GraphQL do nó IOTA"""
    pass


# ==== Exceções usadas pelo cli.py e camadas mais altas ====

class TransactionFailedException(IotaClientException):
    """Exceção quando uma transação falha"""
    pass


class ObjectNotFoundException(IotaClientException):
    """Exceção quando um objeto não é encontrado"""
    pass


class InsufficientBalanceException(IotaClientException):
    """Exceção quando saldo é insuficiente"""
    pass


class NetworkException(IotaClientException):
    """Exceção relacionada à rede"""
    pass


class ContractException(IotaClientException):
    """Exceção relacionada a smart contracts"""
    pass


class KeystoreException(IotaClientException):
    """Exceção relacionada ao keystore"""
    pass


class ValidationException(IotaClientException):
    """Exceção quando validação falha"""
    pass
