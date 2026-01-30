# fogbed_iota/utils/__init__.py

"""
Utilities para fogbed-iota
"""

from .logging import setup_logging, get_logger, logger
from .docker import (
    docker_copy, 
    docker_exec, 
    docker_logs, 
    container_exists, 
    is_container_running,        # NOVA
    wait_for_container, 
    wait_for_port,                # NOVA
    get_container_ip,
    healthcheck_container         # NOVA
)
from .validation import (
    validate_ip, 
    validate_port, 
    validate_container_name, 
    validate_node_config, 
    validate_network_config, 
    validate_genesis_blob
)

__all__ = [
    # Logging
    'setup_logging',
    'get_logger',
    'logger',
    
    # Docker
    'docker_copy',
    'docker_exec',
    'docker_logs',
    'container_exists',
    'is_container_running',      # NOVA
    'wait_for_container',
    'wait_for_port',              # NOVA
    'get_container_ip',
    'healthcheck_container',      # NOVA
    
    # Validation
    'validate_ip',
    'validate_port',
    'validate_container_name',
    'validate_node_config',
    'validate_network_config',
    'validate_genesis_blob',
]
