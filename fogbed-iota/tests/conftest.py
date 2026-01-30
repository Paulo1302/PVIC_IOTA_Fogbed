# tests/conftest.py

"""
Configuração global de testes do projeto fogbed_iota
"""

import sys
from pathlib import Path
import pytest

# Adiciona raiz do projeto ao PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def pytest_configure(config):
    """Configuração executada antes dos testes"""
    config.addinivalue_line(
        "markers", "asyncio: mark test as asynchronous"
    )
    config.addinivalue_line(
        "markers", "integration: mark test requiring real IOTA node"
    )
    config.addinivalue_line(
        "markers", "unit: mark test as unit test"
    )


def pytest_addoption(parser):
    """Adiciona opções customizadas ao pytest"""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests (requires running IOTA node)"
    )
