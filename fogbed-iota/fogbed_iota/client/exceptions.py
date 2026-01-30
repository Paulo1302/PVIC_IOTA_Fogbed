"""Exceções específicas do cliente IOTA"""

class IotaClientError(Exception):
    """Erro genérico do cliente IOTA"""
    pass

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
