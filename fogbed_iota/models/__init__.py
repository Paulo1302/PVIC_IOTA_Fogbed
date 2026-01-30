# fogbed_iota/models/__init__.py
"""
Modelos de dados para fogbed-iota
Estruturas dataclass para validação e organização de dados
"""

from .iota_node import (
    NodeRole,
    IotaNodeConfig,
    IotaNodeMetadata,
    ValidatorNode,
    FullnodeNode,
    create_validator,
    create_fullnode,
)

__all__ = [
    'NodeRole',
    'IotaNodeConfig',
    'IotaNodeMetadata',
    'ValidatorNode',
    'FullnodeNode',
    'create_validator',
    'create_fullnode',
]
