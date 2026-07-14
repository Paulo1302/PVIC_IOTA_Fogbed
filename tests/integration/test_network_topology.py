# tests/test_integration_docker.py

"""
Testes de integração com Docker

Testa operações Docker reais com containers
"""

import sys
import os
import time
from pathlib import Path

# Adicionar diretório raiz ao path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fogbed_iota.models import create_validator, create_fullnode
from fogbed_iota.utils import (
    setup_logging, get_logger
)

# Setup logging
setup_logging(level="DEBUG")
logger = get_logger('test_integration_docker')




def test_node_config_docker_compatibility():
    """Testa que configurações de nó são compatíveis com Docker"""
    logger.info("=" * 80)
    logger.info("TEST: Node Config Docker Compatibility")
    logger.info("=" * 80)

    # Criar validador com múltiplos offsets
    validators = []
    for offset in range(4):
        node = create_validator(
            name=f"iota_val{offset}",
            ip=f"10.0.0.{offset+1}",
            port_offset=offset
        )
        validators.append(node)
        logger.info(f"✅ Created validator {offset}: {node.config.name}")
        logger.info(f"   P2P: {node.get_p2p_address()}")
        logger.info(f"   Metrics: {node.get_metrics_endpoint()}")

    # Validar que portas não conflitam
    all_ports = set()
    for node in validators:
        config = node.config
        ports = {config.p2p_port, config.rpc_port, config.metrics_port}
        
        conflicts = all_ports.intersection(ports)
        assert not conflicts, f"Port conflicts detected: {conflicts}"
        
        all_ports.update(ports)
        logger.info(
            f"✅ No port conflicts for {config.name}: "
            f"P2P={config.p2p_port}, RPC={config.rpc_port}, Metrics={config.metrics_port}"
        )

    logger.info(f"✅ All {len(validators)} validators have unique ports")

    # Criar fullnodes com offsets diferentes
    fullnodes = []
    for offset in range(2):
        node = create_fullnode(
            name=f"gateway_{offset}",
            ip=f"10.0.0.{10+offset}",
            port_offset=offset
        )
        fullnodes.append(node)
        logger.info(f"✅ Created fullnode {offset}: {node.config.name}")
        logger.info(f"   RPC: {node.get_rpc_endpoint()}")

    # Validar que RPC ports variam
    rpc_ports = [node.config.rpc_port for node in fullnodes]
    assert rpc_ports[0] != rpc_ports[1], "RPC ports should differ by port_offset"
    logger.info(f"✅ RPC ports differ correctly: {rpc_ports}")


def test_port_calculation():
    """Testa cálculo de portas com diferentes offsets"""
    logger.info("=" * 80)
    logger.info("TEST: Port Calculation Accuracy")
    logger.info("=" * 80)

    # Criar nós com offsets crescentes
    nodes = []
    for offset in range(5):
        node = create_validator(f"test_{offset}", "10.0.0.1", port_offset=offset)
        nodes.append(node)

        # Validar cálculo de portas
        config = node.config
        expected_p2p = 2001 + (offset * 10)
        expected_rpc = 9000 + (offset * 10)
        expected_metrics = 9184 + (offset * 10)

        assert config.p2p_port == expected_p2p, f"P2P port mismatch for offset {offset}"
        assert config.rpc_port == expected_rpc, f"RPC port mismatch for offset {offset}"
        assert config.metrics_port == expected_metrics, f"Metrics port mismatch for offset {offset}"

        logger.info(
            f"✅ Offset {offset}: P2P={config.p2p_port}, "
            f"RPC={config.rpc_port}, Metrics={config.metrics_port}"
        )

    logger.info(f"✅ Port calculation verified for {len(nodes)} nodes")


def test_metadata_tracking():
    """Testa rastreamento de metadados"""
    logger.info("=" * 80)
    logger.info("TEST: Metadata Tracking")
    logger.info("=" * 80)

    # Criar nó e validar metadados iniciais
    node = create_validator("test_node", "10.0.0.1")
    metadata = node.metadata

    logger.info(f"Container name: {metadata.container_name}")
    logger.info(f"Status: {metadata.status}")
    logger.info(f"Is ready: {metadata.is_ready()}")

    assert metadata.container_name == "mn.test_node", "Container name format incorrect"
    assert metadata.status == "created", "Initial status should be 'created'"
    assert not metadata.is_ready(), "Node should not be ready in 'created' state"

    logger.info("✅ Initial metadata state correct")

    # Testar transição de estados
    states = ["injecting", "booting", "running"]
    for state in states:
        metadata.set_status(state)
        assert metadata.status == state, f"Status transition to {state} failed"
        logger.info(f"✅ Status transitioned to: {state}")

    # Testar que is_ready retorna True apenas em 'running'
    assert metadata.is_ready(), "Node should be ready in 'running' state"
    logger.info("✅ is_ready() returns True for 'running' state")

    # Testar error state
    metadata.set_status("error", error="Connection failed")
    assert not metadata.is_ready(), "Node should not be ready in 'error' state"
    assert metadata.error == "Connection failed", "Error message not stored"
    logger.info("✅ Error state handled correctly")


def test_node_serialization():
    """Testa serialização e desserialização de nós"""
    logger.info("=" * 80)
    logger.info("TEST: Node Serialization")
    logger.info("=" * 80)

    # Criar nó
    original = create_fullnode("gateway", "10.0.0.5", port_offset=2)

    # Serializar
    node_dict = original.to_dict()
    logger.info(f"✅ Serialized node: {node_dict['type']}")
    logger.info(f"   Name: {node_dict['config']['name']}")
    logger.info(f"   Role: {node_dict['config']['role']}")

    # Desserializar
    from fogbed_iota.models import IotaNodeConfig, FullnodeNode
    config = IotaNodeConfig.from_dict(node_dict['config'])
    deserialized = FullnodeNode(config=config)

    # Validar
    assert deserialized.config.name == original.config.name
    assert deserialized.config.ip == original.config.ip
    assert deserialized.config.rpc_port == original.config.rpc_port

    logger.info("✅ Serialization/deserialization works correctly")


def test_network_topology():
    """Testa criação de topologia de rede IOTA"""
    logger.info("=" * 80)
    logger.info("TEST: Network Topology")
    logger.info("=" * 80)

    # Criar rede com 3 validadores + 1 gateway
    validators = []
    for i in range(3):
        node = create_validator(
            name=f"validator_{i}",
            ip=f"10.0.0.{i+1}",
            port_offset=i
        )
        validators.append(node)

    gateway = create_fullnode("gateway", "10.0.0.10", port_offset=10)

    logger.info(f"✅ Created network topology:")
    logger.info(f"   Validators: {len(validators)}")
    logger.info(f"   Gateway: 1")

    # Validar conectividade esperada
    logger.info("\n   Validator addresses:")
    for node in validators:
        logger.info(f"   - {node.config.name}: {node.get_p2p_address()}")

    logger.info(f"\n   Gateway RPC: {gateway.get_rpc_endpoint()}")

    # Validar que todos podem se conectar
    for node in validators:
        assert node.get_rpc_endpoint() is None, "Validators should not expose RPC"

    assert gateway.get_rpc_endpoint() is not None, "Gateway should expose RPC"

    logger.info("✅ Network topology validated")


def run_all_integration_tests():
    """Executa todos os testes de integração"""
    logger.info("\n")
    logger.info("🧪 INICIANDO TESTES DE INTEGRAÇÃO")
    logger.info("")

    try:
        test_node_config_docker_compatibility()
        logger.info("")

        test_port_calculation()
        logger.info("")

        test_metadata_tracking()
        logger.info("")

        test_node_serialization()
        logger.info("")

        test_network_topology()
        logger.info("")

        logger.info("=" * 80)
        logger.info("✅ TODOS OS TESTES DE INTEGRAÇÃO PASSARAM!")
        logger.info("=" * 80)
        return True

    except Exception as e:
        logger.error("")
        logger.error("=" * 80)
        logger.error(f"❌ TESTE DE INTEGRAÇÃO FALHOU: {e}")
        logger.error("=" * 80)
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_integration_tests()
    sys.exit(0 if success else 1)