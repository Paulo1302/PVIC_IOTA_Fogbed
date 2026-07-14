import os
from typing import Dict, List, Optional

from fogbed_iota.utils import get_logger
from fogbed_iota.models.account import IotaAccount
from fogbed_iota.crypto.keypair import generate_keypair
from fogbed_iota.client.cli import IotaCLI

logger = get_logger('accounts.manager')


class AccountManager:
    """
    Gerencia criação e tracking de contas IOTA
    """

    def __init__(self, client_container):
        self.client = client_container
        self.cli = IotaCLI(client_container)
        self.accounts: Dict[str, IotaAccount] = {}
        self.keystore_path = "/root/.iota/iota.keystore"

    def generate_account(self, alias: str, key_scheme: str = "ed25519") -> IotaAccount:
        """
        Gera nova keypair IOTA E importa para o keystore
        
        Args:
            alias: Nome amigável para a conta
            key_scheme: ed25519 (default), secp256k1 ou secp256r1

        Returns:
            IotaAccount criada (sem saldo)
        """
        account = generate_keypair(self.client, alias, key_scheme)
        self.accounts[alias] = account
        logger.info(f"✅ Account created: {alias} -> {account.address}")
        return account

    def get_account(self, alias: str) -> Optional[IotaAccount]:
        """Busca conta por alias"""
        return self.accounts.get(alias)

    def list_accounts(self) -> List[IotaAccount]:
        """Lista todas as contas criadas"""
        return list(self.accounts.values())

    def get_balance(self, alias: str) -> int:
        """
        Consulta saldo on-chain de uma conta usando IotaCLI

        Returns:
            Saldo em MIST (1 IOTA = 10^9 MIST)
        """
        account = self.get_account(alias)
        if not account:
            raise ValueError(f"Account '{alias}' not found")

        logger.info(f"Querying balance for {alias} ({account.address[:16]}...)")

        try:
            coins = self.cli.get_gas(account.address)
            total = sum(c.get("balance", 0) for c in coins)
            account._balance = total
            logger.info(f"Balance for {alias}: {total} MIST")
            return total
        except Exception as e:
            logger.warning(f"Could not query balance for {alias} (network not ready or no funds): {e}")
            account._balance = 0
            return 0

    def export_keystore(self, output_path: str = "/tmp/iota_keystore_backup.json"):
        """
        Exporta keystore para backup

        ATENÇÃO: Contém chaves privadas - manter seguro
        """
        logger.warning("⚠️  Exporting keystore with PRIVATE KEYS")

        copy_cmd = f"docker cp mn.{self.client.name}:{self.keystore_path} {output_path}"
        result = os.system(copy_cmd)

        if result == 0:
            logger.info(f"Keystore exported to {output_path}")
            return output_path
        else:
            logger.error("Failed to export keystore")
            return None
