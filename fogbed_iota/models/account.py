from typing import Optional

class IotaAccount:
    """Representa uma conta IOTA com keypair"""

    def __init__(
        self,
        address: str,
        alias: str,
        key_scheme: str = "ed25519",
        public_key: Optional[str] = None
    ):
        self.address = address
        self.alias = alias
        self.key_scheme = key_scheme
        self.public_key = public_key
        self._balance = None

    def __repr__(self):
        return f"IotaAccount(alias='{self.alias}', address='{self.address[:8]}...')"
