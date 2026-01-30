# fogbed_iota/models/iota_node.py

"""
Modelo de dados para nós IOTA

Define estrutura e validação de nós validadores e fullnodes com ports parametrizados
e subtipos operacionais alinhados à arquitetura da rede IOTA.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from enum import Enum

from fogbed_iota.utils import (
    get_logger,
    validate_port,
    validate_ip,
    validate_container_name,
)

logger = get_logger("models.iota_node")


class NodeRole(Enum):
    """Roles de nós na rede IOTA"""

    VALIDATOR = "validator"
    FULLNODE = "fullnode"

    def __str__(self):
        return self.value


class NodeType(Enum):
    """
    Subtipos operacionais para infraestrutura (não oficiais da IOTA).
    
    A rede IOTA 1.15+ possui apenas 2 tipos oficiais:
    - VALIDATOR: nós de consenso (authority)
    - FULLNODE: nós de leitura/sincronização
    
    Os subtipos abaixo são abstrações para facilitar deploy e configuração.
    """
    CONSENSUS_VALIDATOR = "consensus_validator"  # Validator padrão
    ARCHIVE_VALIDATOR = "archive_validator"      # Validator + retenção alta
    PUBLIC_FULLNODE = "public_fullnode"          # Fullnode exposto (RPC público)
    VALIDATOR_FULLNODE = "validator_fullnode"    # Fullnode upstream de validator
    INDEXER_FULLNODE = "indexer_fullnode"        # Fullnode + índices extras

    def __str__(self) -> str:
        return self.value


@dataclass
class IotaNodeConfig:
    """
    Configuração de um nó IOTA

    Attributes:
        name: Nome identificador do nó
        ip: Endereço IP do nó (10.0.0.X)
        role: Papel do nó (validator ou fullnode)
        node_type: Subtipo operacional (ex: consensus_validator, public_fullnode)
        port_offset: Offset para cálculo de portas P2P, RPC, Metrics
        image: Imagem Docker a usar
    """

    name: str
    ip: str
    role: NodeRole = NodeRole.VALIDATOR
    port_offset: int = 0
    image: str = "iota-dev:latest"
    node_type: Optional[NodeType] = None

    # Campos computados (read-only após inicialização)
    p2p_port: Optional[int] = field(init=False, default=None)
    rpc_port: Optional[int] = field(init=False, default=None)
    metrics_port: Optional[int] = field(init=False, default=None)

    # Base ports (configuráveis para evitar conflitos)
    BASE_P2P_PORT: int = 2001
    BASE_RPC_PORT: int = 9000
    BASE_METRICS_PORT: int = 9184
    PORT_STEP: int = 10  # Incremento entre offsets

    def __post_init__(self):
        """Validar e calcular ports após inicialização"""
        self._validate()
        self._compute_ports()

    def _validate(self) -> None:
        """Valida configuração do nó"""
        logger.debug(f"Validating node config: {self.name}")

        # Validar nome
        if not validate_container_name(self.name):
            raise ValueError(f"Invalid node name: {self.name}")

        # Validar IP
        if not validate_ip(self.ip):
            raise ValueError(f"Invalid node IP: {self.ip}")

        # Validar role (string → enum)
        if not isinstance(self.role, NodeRole):
            try:
                self.role = NodeRole(self.role)
            except ValueError:
                raise ValueError(f"Invalid role: {self.role}")

        # Validar node_type (string → enum)
        if isinstance(self.node_type, str):
            try:
                self.node_type = NodeType(self.node_type)
            except ValueError:
                raise ValueError(f"Invalid node_type: {self.node_type}")

        # Ajustar role com base no node_type (se definido)
        if self.node_type:
            if self.node_type in (
                NodeType.CONSENSUS_VALIDATOR,
                NodeType.ARCHIVE_VALIDATOR,
            ):
                self.role = NodeRole.VALIDATOR
            elif self.node_type in (
                NodeType.PUBLIC_FULLNODE,
                NodeType.VALIDATOR_FULLNODE,
                NodeType.INDEXER_FULLNODE,
            ):
                self.role = NodeRole.FULLNODE

        # Validar port_offset
        if not isinstance(self.port_offset, int) or self.port_offset < 0:
            raise ValueError(f"Invalid port_offset: {self.port_offset}")

        logger.debug(f"✅ Node config validated: {self.name}")

    def _compute_ports(self) -> None:
        """Calcula portas baseado no offset - TODOS os ports variam"""
        # Calcular portas com offset
        self.p2p_port = self.BASE_P2P_PORT + (self.port_offset * self.PORT_STEP)
        self.rpc_port = self.BASE_RPC_PORT + (self.port_offset * self.PORT_STEP)
        self.metrics_port = self.BASE_METRICS_PORT + (self.port_offset * self.PORT_STEP)

        # Validar portas calculadas
        if not validate_port(self.p2p_port):
            raise ValueError(f"Invalid P2P port: {self.p2p_port}")

        if not validate_port(self.rpc_port):
            raise ValueError(f"Invalid RPC port: {self.rpc_port}")

        if not validate_port(self.metrics_port):
            raise ValueError(f"Invalid Metrics port: {self.metrics_port}")

        logger.debug(
            f"Ports computed for {self.name}: "
            f"P2P={self.p2p_port}, RPC={self.rpc_port}, Metrics={self.metrics_port}"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Converte config para dicionário"""
        return {
            "name": self.name,
            "ip": self.ip,
            "role": str(self.role),
            "node_type": str(self.node_type) if self.node_type else None,
            "port_offset": self.port_offset,
            "image": self.image,
            "p2p_port": self.p2p_port,
            "rpc_port": self.rpc_port,
            "metrics_port": self.metrics_port,
        }

    def to_yaml_context(self) -> str:
        """Retorna contexto YAML para logging"""
        return (
            f"Node(name={self.name}, role={self.role}, type={self.node_type}, ip={self.ip}, "
            f"p2p={self.p2p_port}, rpc={self.rpc_port}, metrics={self.metrics_port})"
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IotaNodeConfig":
        """Cria config a partir de dicionário"""
        logger.debug(f"Creating IotaNodeConfig from dict: {data}")

        role = data.get("role", NodeRole.VALIDATOR)
        if isinstance(role, str):
            role = NodeRole(role)

        node_type = data.get("node_type")
        if isinstance(node_type, str):
            node_type = NodeType(node_type)

        return cls(
            name=data["name"],
            ip=data["ip"],
            role=role,
            node_type=node_type,
            port_offset=data.get("port_offset", 0),
            image=data.get("image", "iota-dev:latest"),
        )


@dataclass
class IotaNodeMetadata:
    """
    Metadados de um nó em execução

    Attributes:
        config: Configuração do nó
        container_name: Nome do container Mininet (mn.{name})
        genesis_path: Caminho para genesis.blob
        config_path: Caminho para validator.yaml
        status: Estado atual do nó
        error: Mensagem de erro se houver
        created_at: Timestamp de criação
    """

    config: IotaNodeConfig
    container_name: str = field(init=False)
    genesis_path: Optional[str] = None
    config_path: Optional[str] = None
    status: str = "created"  # created, injecting, booting, running, error, stopped
    error: Optional[str] = None
    created_at: Optional[float] = field(init=False, default=None)

    def __post_init__(self):
        """Inicializa metadados"""
        import time

        self.container_name = f"mn.{self.config.name}"
        self.created_at = time.time()
        logger.debug(f"Metadata created for {self.container_name}")

    def is_validator(self) -> bool:
        """Verifica se é validador"""
        return self.config.role == NodeRole.VALIDATOR

    def is_fullnode(self) -> bool:
        """Verifica se é fullnode"""
        return self.config.role == NodeRole.FULLNODE

    def is_ready(self) -> bool:
        """Verifica se nó está pronto para operações"""
        return self.status == "running" and self.error is None

    def set_status(self, status: str, error: Optional[str] = None) -> None:
        """
        Atualiza status do nó

        Args:
            status: Novo status
            error: Mensagem de erro (se houver)
        """
        old_status = self.status
        self.status = status
        self.error = error

        if error:
            logger.error(
                f"Node {self.config.name} status: {old_status} → {status} "
                f"(error: {error})"
            )
        else:
            logger.info(f"Node {self.config.name} status: {old_status} → {status}")

    def to_dict(self) -> Dict[str, Any]:
        """Converte metadados para dicionário"""
        return {
            "config": self.config.to_dict(),
            "container_name": self.container_name,
            "genesis_path": self.genesis_path,
            "config_path": self.config_path,
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at,
        }

    @classmethod
    def from_config(cls, config: IotaNodeConfig) -> "IotaNodeMetadata":
        """Cria metadados a partir de configuração"""
        return cls(config=config)


@dataclass
class ValidatorNode:
    """
    Nó validador especializado

    Participa do consensus e produz checkpoints
    """

    config: IotaNodeConfig
    metadata: IotaNodeMetadata = field(init=False)

    def __post_init__(self):
        """Valida que é validador"""
        if self.config.role != NodeRole.VALIDATOR:
            raise ValueError(f"Expected validator role, got {self.config.role}")
        self.metadata = IotaNodeMetadata.from_config(self.config)
        logger.info(f"ValidatorNode created: {self.config.name}")

    def get_p2p_address(self) -> str:
        """Retorna endereço P2P (multiaddr format)"""
        return f"/ip4/{self.config.ip}/udp/{self.config.p2p_port}"

    def get_rpc_endpoint(self) -> Optional[str]:
        """Retorna endpoint RPC (validadores normalmente não expõem)"""
        return None

    def get_metrics_endpoint(self) -> str:
        """Retorna endpoint de métricas"""
        return f"http://{self.config.ip}:{self.config.metrics_port}/metrics"

    def get_consensus_db_path(self) -> str:
        """Retorna caminho do consensus database"""
        return "/app/consensus_db"

    def to_dict(self) -> Dict[str, Any]:
        """Serializa para dicionário"""
        return {
            "type": "ValidatorNode",
            "config": self.config.to_dict(),
            "metadata": self.metadata.to_dict(),
        }


@dataclass
class FullnodeNode:
    """
    Nó fullnode/gateway especializado

    Apenas lê estado, expõe RPC, sincroniza com validadores
    """

    config: IotaNodeConfig
    metadata: IotaNodeMetadata = field(init=False)

    def __post_init__(self):
        """Valida que é fullnode"""
        if self.config.role != NodeRole.FULLNODE:
            raise ValueError(f"Expected fullnode role, got {self.config.role}")
        self.metadata = IotaNodeMetadata.from_config(self.config)
        logger.info(f"FullnodeNode created: {self.config.name} (gateway)")

    def get_p2p_address(self) -> str:
        """Retorna endereço P2P (multiaddr format)"""
        return f"/ip4/{self.config.ip}/udp/{self.config.p2p_port}"

    def get_rpc_endpoint(self) -> str:
        """Retorna endpoint RPC"""
        return f"http://{self.config.ip}:{self.config.rpc_port}"

    def get_metrics_endpoint(self) -> str:
        """Retorna endpoint de métricas Prometheus"""
        return f"http://{self.config.ip}:{self.config.metrics_port}/metrics"

    def get_db_path(self) -> str:
        """Retorna caminho do application database"""
        return "/app/db"

    def to_dict(self) -> Dict[str, Any]:
        """Serializa para dicionário"""
        return {
            "type": "FullnodeNode",
            "config": self.config.to_dict(),
            "metadata": self.metadata.to_dict(),
        }


# Factory functions básicas
def create_validator(
    name: str,
    ip: str,
    port_offset: int = 0,
    image: str = "iota-dev:latest",
) -> ValidatorNode:
    """
    Cria nó validador
    """
    config = IotaNodeConfig(
        name=name,
        ip=ip,
        role=NodeRole.VALIDATOR,
        port_offset=port_offset,
        image=image,
    )
    return ValidatorNode(config=config)


def create_fullnode(
    name: str,
    ip: str,
    port_offset: int = 0,
    image: str = "iota-dev:latest",
) -> FullnodeNode:
    """
    Cria nó fullnode/gateway
    """
    config = IotaNodeConfig(
        name=name,
        ip=ip,
        role=NodeRole.FULLNODE,
        port_offset=port_offset,
        image=image,
    )
    return FullnodeNode(config=config)


# Factory functions especializadas por NodeType
def create_consensus_validator(
    name: str,
    ip: str,
    port_offset: int = 0,
    image: str = "iota-dev:latest",
) -> ValidatorNode:
    """Cria validador de consenso"""
    config = IotaNodeConfig(
        name=name,
        ip=ip,
        role=NodeRole.VALIDATOR,
        node_type=NodeType.CONSENSUS_VALIDATOR,
        port_offset=port_offset,
        image=image,
    )
    return ValidatorNode(config=config)


def create_archive_validator(
    name: str,
    ip: str,
    port_offset: int = 0,
    image: str = "iota-dev:latest",
) -> ValidatorNode:
    """Cria validador com perfil de archive node"""
    config = IotaNodeConfig(
        name=name,
        ip=ip,
        role=NodeRole.VALIDATOR,
        node_type=NodeType.ARCHIVE_VALIDATOR,
        port_offset=port_offset,
        image=image,
    )
    return ValidatorNode(config=config)


def create_public_fullnode(
    name: str,
    ip: str,
    port_offset: int = 0,
    image: str = "iota-dev:latest",
) -> FullnodeNode:
    """Cria fullnode público (exposto para clientes externos)"""
    config = IotaNodeConfig(
        name=name,
        ip=ip,
        role=NodeRole.FULLNODE,
        node_type=NodeType.PUBLIC_FULLNODE,
        port_offset=port_offset,
        image=image,
    )
    return FullnodeNode(config=config)


def create_validator_fullnode(
    name: str,
    ip: str,
    port_offset: int = 0,
    image: str = "iota-dev:latest",
) -> FullnodeNode:
    """Cria fullnode acoplado a um validador (RPC interno)"""
    config = IotaNodeConfig(
        name=name,
        ip=ip,
        role=NodeRole.FULLNODE,
        node_type=NodeType.VALIDATOR_FULLNODE,
        port_offset=port_offset,
        image=image,
    )
    return FullnodeNode(config=config)


def create_indexer_fullnode(
    name: str,
    ip: str,
    port_offset: int = 0,
    image: str = "iota-dev:latest",
) -> FullnodeNode:
    """Cria fullnode com perfil de indexador"""
    config = IotaNodeConfig(
        name=name,
        ip=ip,
        role=NodeRole.FULLNODE,
        node_type=NodeType.INDEXER_FULLNODE,
        port_offset=port_offset,
        image=image,
    )
    return FullnodeNode(config=config)
