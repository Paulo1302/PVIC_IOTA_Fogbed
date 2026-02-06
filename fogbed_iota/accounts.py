# fogbed_iota/accounts.py

"""
Gerenciamento de contas e keypairs para IOTA
Sem funding automático - apenas geração e tracking
"""

import json
import subprocess
import re
from typing import Dict, List, Optional
from pathlib import Path

from fogbed_iota.utils import get_logger

logger = get_logger('accounts')


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


class AccountManager:
    """
    Gerencia criação e tracking de contas IOTA
    
    NÃO faz funding automático - princípio de gas manual
    """
    
    def __init__(self, client_container):
        self.client = client_container
        self.accounts: Dict[str, IotaAccount] = {}
        self.keystore_path = "/root/.iota/iota.keystore"
        
    def generate_account(
        self, 
        alias: str, 
        key_scheme: str = "ed25519"
    ) -> IotaAccount:
        """
        Gera nova keypair IOTA
        
        Args:
            alias: Nome amigável para a conta
            key_scheme: ed25519 (default), secp256k1 ou secp256r1
            
        Returns:
            IotaAccount criada (sem saldo)
        """
        logger.info(f"Generating keypair: {alias} ({key_scheme})")
        
        # Nova sintaxe para IOTA v1.15.0+
        cmd = f"iota keytool generate {key_scheme}"
        result = self.client.cmd(cmd)
        
        logger.debug(f"Keytool raw output:\n{result}")
        
        # Parse do output texto com tabela formatada
        # Formato: │ iotaAddress │  0xABC...  │
        
        # Remover caracteres de formatação de tabela e logs
        clean_result = result.replace('│', '').replace('─', '').replace('╭', '').replace('╮', '').replace('╰', '').replace('╯', '')
        
        # Buscar padrão de endereço IOTA (0x seguido de 64 caracteres hex)
        address_match = re.search(r'(?:iotaAddress|IOTA Address|Address)\s*[:\s]\s*(0x[a-fA-F0-9]{64})', clean_result, re.IGNORECASE)
        
        if not address_match:
            # Tentar regex mais agressiva - qualquer 0x64chars
            address_match = re.search(r'(0x[a-fA-F0-9]{64})', result)
        
        if not address_match:
            logger.error(f"Failed to parse address from keytool output:\n{result}")
            raise RuntimeError(f"Could not extract address from keytool output")
        
        address = address_match.group(1)
        
        # Buscar public key
        pubkey_match = re.search(r'publicBase64Key\s*[:\s]\s*([A-Za-z0-9+/=]+)', clean_result)
        public_key = pubkey_match.group(1) if pubkey_match else None
        
        account = IotaAccount(
            address=address,
            alias=alias,
            key_scheme=key_scheme,
            public_key=public_key
        )
        
        self.accounts[alias] = account
        logger.info(f"✅ Account created: {alias} -> {address}")
        
        # Salvar alias mapping manualmente
        mapping_cmd = f"echo '{alias}:{address}' >> /root/.iota/account_aliases.txt"
        self.client.cmd(mapping_cmd)
        
        return account
    
    def get_account(self, alias: str) -> Optional[IotaAccount]:
        """Busca conta por alias"""
        return self.accounts.get(alias)
    
    def list_accounts(self) -> List[IotaAccount]:
        """Lista todas as contas criadas"""
        return list(self.accounts.values())
    
    def get_balance(self, alias: str) -> int:
        """
        Consulta saldo on-chain de uma conta
        
        Returns:
            Saldo em MIST (1 IOTA = 10^9 MIST)
        """
        account = self.get_account(alias)
        if not account:
            raise ValueError(f"Account '{alias}' not found")
        
        logger.info(f"Querying balance for {alias} ({account.address[:16]}...)")
        
        # Usar iota client gas <address> com timeout
        cmd = f"timeout 5 iota client gas {account.address} 2>&1 || echo 'TIMEOUT'"
        result = self.client.cmd(cmd)
        
        logger.debug(f"Gas query result: {result}")
        
        # Se timeout ou erro, assumir saldo zero
        if "TIMEOUT" in result or "No gas coins" in result or "error" in result.lower() or "Error" in result:
            logger.warning(f"Could not query balance for {alias} (network not ready or no funds)")
            account._balance = 0
            return 0
        
        # Tentar extrair valores
        total = 0
        for line in result.split('\n'):
            balance_match = re.search(r'(?:balance|value):\s*(\d+)', line, re.IGNORECASE)
            if balance_match:
                total += int(balance_match.group(1))
        
        account._balance = total
        logger.info(f"Balance for {alias}: {total} MIST")
        return total

    def export_keystore(self, output_path: str = "/tmp/iota_keystore_backup.json"):
        """
        Exporta keystore para backup
        
        ATENÇÃO: Contém chaves privadas - manter seguro
        """
        logger.warning("⚠️  Exporting keystore with PRIVATE KEYS")
        
        # Copiar keystore
        import os
        copy_cmd = f"docker cp mn.{self.client.name}:{self.keystore_path} {output_path}"
        result = os.system(copy_cmd)
        
        if result == 0:
            logger.info(f"Keystore exported to {output_path}")
            return output_path
        else:
            logger.error("Failed to export keystore")
            return None
