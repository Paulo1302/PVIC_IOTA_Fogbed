# fogbed_iota/utils/validation.py
"""
Validação de inputs para fogbed-iota
"""

import re
from ipaddress import ip_address, AddressValueError
from fogbed_iota.utils.logging import get_logger

logger = get_logger('validation')


def validate_ip(ip_str):
    """
    Validar endereço IP
    
    Args:
        ip_str: String de IP
    
    Returns:
        bool: IP válido
    """
    try:
        ip_address(ip_str)
        logger.debug(f"✅ Valid IP: {ip_str}")
        return True
    except (AddressValueError, ValueError) as e:
        logger.error(f"❌ Invalid IP: {ip_str} - {str(e)}")
        return False


def validate_port(port):
    """
    Validar porta (1-65535)
    
    Args:
        port: Número da porta
    
    Returns:
        bool: Porta válida
    """
    try:
        port_num = int(port)
        valid = 1 <= port_num <= 65535
        
        if not valid:
            logger.error(f"❌ Port out of range: {port_num}")
        else:
            logger.debug(f"✅ Valid port: {port_num}")
        
        return valid
    
    except (ValueError, TypeError):
        logger.error(f"❌ Invalid port type: {port}")
        return False


def validate_container_name(name):
    """
    Validar nome de container (Docker naming rules)
    
    Args:
        name: Nome do container
    
    Returns:
        bool: Nome válido
    """
    # Docker: lowercase, numbers, dash, underscore, max 63 chars
    pattern = r'^[a-z0-9_-]{1,63}$'
    
    valid = bool(re.match(pattern, name))
    
    if valid:
        logger.debug(f"✅ Valid container name: {name}")
    else:
        logger.error(f"❌ Invalid container name: {name}")
    
    return valid


def validate_node_config(name, ip, role, port_offset=0):
    """
    Validar configuração completa de nó
    
    Args:
        name: Nome do nó
        ip: IP do nó
        role: Papel ('validator' ou 'fullnode')
        port_offset: Offset de portas
    
    Returns:
        tuple: (bool, list of errors)
    """
    
    errors = []
    
    # Validar nome
    if not validate_container_name(name):
        errors.append(f"Invalid node name: {name}")
    
    # Validar IP
    if not validate_ip(ip):
        errors.append(f"Invalid node IP: {ip}")
    
    # Validar role
    if role not in ['validator', 'fullnode']:
        errors.append(f"Invalid role: {role}. Must be 'validator' or 'fullnode'")
    
    # Validar port_offset
    if not isinstance(port_offset, int) or port_offset < 0:
        errors.append(f"Invalid port_offset: {port_offset}")
    
    if errors:
        logger.error(f"❌ Config validation failed for {name}:")
        for error in errors:
            logger.error(f"   - {error}")
        return (False, errors)
    else:
        logger.info(f"✅ Valid node config: {name} ({role}) @ {ip}")
        return (True, [])


def validate_network_config(validators, fullnodes):
    """
    Validar configuração completa de rede
    
    Args:
        validators: Lista de nós validadores
        fullnodes: Lista de nós fullnode
    
    Returns:
        tuple: (bool, list of errors)
    """
    
    errors = []
    all_ips = set()
    all_names = set()
    
    # Validar que temos pelo menos 1 validador
    if not validators or len(validators) == 0:
        errors.append("At least one validator is required")
    
    # Validar validadores
    for node in validators:
        if node['ip'] in all_ips:
            errors.append(f"Duplicate IP: {node['ip']}")
        if node['name'] in all_names:
            errors.append(f"Duplicate name: {node['name']}")
        
        all_ips.add(node['ip'])
        all_names.add(node['name'])
    
    # Validar fullnodes
    for node in fullnodes:
        if node['ip'] in all_ips:
            errors.append(f"Duplicate IP: {node['ip']}")
        if node['name'] in all_names:
            errors.append(f"Duplicate name: {node['name']}")
        
        all_ips.add(node['ip'])
        all_names.add(node['name'])
    
    if errors:
        logger.error("❌ Network config validation failed:")
        for error in errors:
            logger.error(f"   - {error}")
        return (False, errors)
    else:
        logger.info(f"✅ Valid network config: {len(validators)} validators, {len(fullnodes)} fullnodes")
        return (True, [])


def validate_genesis_blob(blob_path):
    """
    Validar arquivo genesis.blob
    
    Args:
        blob_path: Caminho para genesis.blob
    
    Returns:
        bool: Arquivo válido
    """
    from pathlib import Path
    
    path = Path(blob_path)
    
    if not path.exists():
        logger.error(f"❌ Genesis blob not found: {blob_path}")
        return False
    
    if not path.is_file():
        logger.error(f"❌ Genesis path is not a file: {blob_path}")
        return False
    
    size_mb = path.stat().st_size / (1024 * 1024)
    
    if size_mb < 0.1:
        logger.error(f"❌ Genesis blob too small: {size_mb:.2f}MB")
        return False
    
    logger.info(f"✅ Valid genesis blob: {size_mb:.2f}MB")
    return True