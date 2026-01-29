# tests/test_models.py
"""
Teste dos modelos de nós IOTA
Valida estrutura e comportamento das dataclasses
"""

import sys
import os
from pathlib import Path

# Adicionar diretório raiz ao path (correto para tests/)
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fogbed_iota.models import (
    NodeRole,
    IotaNodeConfig,
    IotaNodeMetadata,
    ValidatorNode,
    FullnodeNode,
    create_validator,
    create_fullnode,
)
from fogbed_iota.utils import setup_logging, get_logger

# Setup logging
setup_logging(level="DEBUG")
logger = get_logger('test_models')


def test_node_role():
    """Testa enum NodeRole"""
    logger.info("=" * 60)
    logger.info("TEST: NodeRole Enum")
    logger.info("=" * 60)
    
    # Testar valores
    assert str(NodeRole.VALIDATOR) == "validator"
    assert str(NodeRole.FULLNODE) == "fullnode"
    
    logger.info("✅ NodeRole.VALIDATOR: validator")
    logger.info("✅ NodeRole.FULLNODE: fullnode")
    
    # Testar conversão
    role = NodeRole("validator")
    assert role == NodeRole.VALIDATOR
    logger.info("✅ NodeRole('validator') → NodeRole.VALIDATOR")


def test_iota_node_config():
    """Testa IotaNodeConfig"""
    logger.info("=" * 60)
    logger.info("TEST: IotaNodeConfig")
    logger.info("=" * 60)
    
    # Criar config válida
    config = IotaNodeConfig(
        name="iota1",
        ip="10.0.0.1",
        role=NodeRole.VALIDATOR,
        port_offset=0,
        image="iota-dev:latest"
    )
    
    logger.info(f"✅ Config created: {config.name}")
    logger.info(f"   IP: {config.ip}")
    logger.info(f"   Role: {config.role}")
    logger.info(f"   P2P Port: {config.p2p_port}")
    logger.info(f"   RPC Port: {config.rpc_port}")
    logger.info(f"   Metrics Port: {config.metrics_port}")
    
    # Testar que portas foram calculadas
    assert config.p2p_port == 2001
    assert config.rpc_port == 9000
    assert config.metrics_port == 9184
    logger.info("✅ Ports calculated correctly")
    
    # Testar serialização
    data = config.to_dict()
    assert data['name'] == "iota1"
    assert data['p2p_port'] == 2001
    logger.info("✅ to_dict() works")
    
    # Testar desserialização
    config2 = IotaNodeConfig.from_dict(data)
    assert config2.name == config.name
    assert config2.p2p_port == config.p2p_port
    logger.info("✅ from_dict() works")


def test_iota_node_config_validation():
    """Testa validação de IotaNodeConfig"""
    logger.info("=" * 60)
    logger.info("TEST: IotaNodeConfig Validation")
    logger.info("=" * 60)
    
    # Testar nome inválido - ESPERADO: ValueError
    try:
        config = IotaNodeConfig(
            name="invalid-name@123",  # Caracteres inválidos
            ip="10.0.0.1"
        )
        logger.error("❌ Should have rejected invalid name")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        logger.info(f"✅ Rejected invalid name (expected)")
    
    # Testar IP inválido - ESPERADO: ValueError
    try:
        config = IotaNodeConfig(
            name="iota1",
            ip="999.999.999.999"  # IP inválido
        )
        logger.error("❌ Should have rejected invalid IP")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        logger.info(f"✅ Rejected invalid IP (expected)")
    
    # Testar role inválido - ESPERADO: ValueError
    try:
        config = IotaNodeConfig(
            name="iota1",
            ip="10.0.0.1",
            role="invalid_role"  # Role inválida
        )
        logger.error("❌ Should have rejected invalid role")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        logger.info(f"✅ Rejected invalid role (expected)")


def test_iota_node_metadata():
    """Testa IotaNodeMetadata"""
    logger.info("=" * 60)
    logger.info("TEST: IotaNodeMetadata")
    logger.info("=" * 60)
    
    # Criar config e metadata
    config = IotaNodeConfig(
        name="iota1",
        ip="10.0.0.1",
        role=NodeRole.VALIDATOR
    )
    
    metadata = IotaNodeMetadata.from_config(config)
    
    logger.info(f"✅ Metadata created for {config.name}")
    logger.info(f"   Container: {metadata.container_name}")
    logger.info(f"   Status: {metadata.status}")
    
    assert metadata.container_name == "mn.iota1"
    assert metadata.status == "created"
    logger.info("✅ Container name correct")
    
    # Testar status update
    metadata.set_status("booting")
    assert metadata.status == "booting"
    logger.info("✅ Status updated to 'booting'")
    
    # Testar status com erro
    metadata.set_status("error", error="Connection failed")
    assert metadata.status == "error"
    assert metadata.error == "Connection failed"
    logger.info("✅ Status updated with error message")


def test_validator_node():
    """Testa ValidatorNode"""
    logger.info("=" * 60)
    logger.info("TEST: ValidatorNode")
    logger.info("=" * 60)
    
    # Criar com factory function
    validator = create_validator("iota1", "10.0.0.1", port_offset=0)
    
    logger.info(f"✅ Validator created: {validator.config.name}")
    logger.info(f"   Role: {validator.config.role}")
    logger.info(f"   P2P Address: {validator.get_p2p_address()}")
    logger.info(f"   Consensus DB: {validator.get_consensus_db_path()}")
    
    assert validator.config.role == NodeRole.VALIDATOR
    assert validator.get_p2p_address() == "/ip4/10.0.0.1/udp/2001"
    assert validator.get_rpc_endpoint() is None
    logger.info("✅ ValidatorNode properties correct")
    
    # Testar que rejeita role errada
    try:
        config = IotaNodeConfig(
            name="bad",
            ip="10.0.0.1",
            role=NodeRole.FULLNODE
        )
        validator_bad = ValidatorNode(config=config)
        logger.error("❌ Should have rejected fullnode role")
        assert False
    except ValueError as e:
        logger.info(f"✅ Rejected wrong role (expected)")


def test_fullnode_node():
    """Testa FullnodeNode"""
    logger.info("=" * 60)
    logger.info("TEST: FullnodeNode")
    logger.info("=" * 60)
    
    # Criar com factory function
    fullnode = create_fullnode("gateway", "10.0.0.5", port_offset=4)
    
    logger.info(f"✅ Fullnode created: {fullnode.config.name}")
    logger.info(f"   Role: {fullnode.config.role}")
    logger.info(f"   P2P Address: {fullnode.get_p2p_address()}")
    logger.info(f"   RPC Endpoint: {fullnode.get_rpc_endpoint()}")
    logger.info(f"   Metrics: {fullnode.get_metrics_endpoint()}")
    
    assert fullnode.config.role == NodeRole.FULLNODE
    assert fullnode.get_rpc_endpoint() == "http://10.0.0.5:9000"
    assert fullnode.get_metrics_endpoint() == "http://10.0.0.5:9184/metrics"
    logger.info("✅ FullnodeNode properties correct")
    
    # Testar que rejeita role errada
    try:
        config = IotaNodeConfig(
            name="bad",
            ip="10.0.0.1",
            role=NodeRole.VALIDATOR
        )
        fullnode_bad = FullnodeNode(config=config)
        logger.error("❌ Should have rejected validator role")
        assert False
    except ValueError as e:
        logger.info(f"✅ Rejected wrong role (expected)")


def test_port_offset():
    """Testa cálculo de portas com diferentes offsets"""
    logger.info("=" * 60)
    logger.info("TEST: Port Offset Calculation")
    logger.info("=" * 60)
    
    for offset in range(4):
        config = IotaNodeConfig(
            name=f"iota{offset}",
            ip=f"10.0.0.{offset+1}",
            port_offset=offset
        )
        
        expected_p2p = 2001 + (offset * 10)
        assert config.p2p_port == expected_p2p
        
        logger.info(f"✅ Offset {offset}: P2P port = {config.p2p_port}")


def run_all_tests():
    """Executa todos os testes"""
    logger.info("\n")
    logger.info("🧪 INICIANDO TESTES DE MODELOS")
    logger.info("")
    
    try:
        test_node_role()
        logger.info("")
        
        test_iota_node_config()
        logger.info("")
        
        test_iota_node_config_validation()
        logger.info("")
        
        test_iota_node_metadata()
        logger.info("")
        
        test_validator_node()
        logger.info("")
        
        test_fullnode_node()
        logger.info("")
        
        test_port_offset()
        logger.info("")
        
        logger.info("=" * 60)
        logger.info("✅ TODOS OS TESTES PASSARAM!")
        logger.info("=" * 60)
        
        return True
    
    except Exception as e:
        logger.error("")
        logger.error("=" * 60)
        logger.error(f"❌ TESTE FALHOU: {e}")
        logger.error("=" * 60)
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)