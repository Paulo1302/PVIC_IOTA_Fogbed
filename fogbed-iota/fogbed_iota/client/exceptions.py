# fogbed_iota/client/exceptions.py

"""
Exceções customizadas para cliente IOTA
"""


class IotaClientError(Exception):
    """Erro base para cliente IOTA"""

    pass


class IotaRpcError(IotaClientError):
    """Erro em chamada JSON-RPC"""

    def __init__(self, code: int, message: str, data=None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"RPC Error {code}: {message}")


class IotaGraphQLError(IotaClientError):
    """Erro em query GraphQL"""

    def __init__(self, errors: list):
        self.errors = errors
        super().__init__(f"GraphQL errors: {errors}")


class IotaConnectionError(IotaClientError):
    """Erro de conexão com nó"""

    pass


class IotaTimeoutError(IotaClientError):
    """Timeout em requisição"""

    pass
