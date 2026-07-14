import re
from typing import Optional

from fogbed_iota.utils import get_logger
from fogbed_iota.models.account import IotaAccount

logger = get_logger('crypto.keypair')

def generate_keypair(client_container, alias: str, key_scheme: str = "ed25519") -> IotaAccount:
    """
    Gera nova keypair IOTA E importa para o keystore local do container

    Args:
        client_container: O container do Fogbed (com iota cli instalado)
        alias: Nome amigável para a conta
        key_scheme: ed25519 (default), secp256k1 ou secp256r1

    Returns:
        IotaAccount contendo address e public key
    """
    logger.info(f"Generating keypair: {alias} ({key_scheme})")

    # Nova sintaxe para IOTA v1.15.0+
    cmd = f"iota keytool generate {key_scheme}"
    result = client_container.cmd(cmd)
    logger.debug(f"Keytool raw output:\n{result}")

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

    # Buscar mnemonic para importar ao keystore
    mnemonic_match = re.search(r'mnemonic\s*[:\s]\s*([a-z\s]+?)(?:peerId|$)', clean_result, re.IGNORECASE)
    mnemonic = mnemonic_match.group(1).strip() if mnemonic_match else None

    if not mnemonic:
        logger.warning(f"⚠️  Could not extract mnemonic from keytool output, skipping keystore import")
    else:
        logger.info(f"📝 Importing mnemonic to keystore for {alias}...")
        import_cmd = f'iota keytool import "{mnemonic}" {key_scheme} --alias {alias} 2>&1'
        import_result = client_container.cmd(import_cmd)

        if "error" in import_result.lower() or "failed" in import_result.lower():
            logger.error(f"❌ Failed to import key for {alias}: {import_result}")
        else:
            logger.info(f"✅ Key imported to keystore for {alias}")
            logger.debug(f"Import result:\n{import_result}")

    account = IotaAccount(
        address=address,
        alias=alias,
        key_scheme=key_scheme,
        public_key=public_key
    )

    # Salvar alias mapping manualmente
    mapping_cmd = f"echo '{alias}:{address}' >> /root/.iota/account_aliases.txt"
    client_container.cmd(mapping_cmd)

    return account
