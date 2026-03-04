#!/bin/bash
# scripts/run_tests.sh

echo "🧪 Running IOTA Client Tests..."

# Testes unitários
echo "Running unit tests..."
pytest tests/test_iota_client.py -v --tb=short

# Se testes passarem, tentar integração (opcional)
if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Unit tests passed!"
    echo ""
    
    # Verifica se nó está rodando
    if curl -s http://localhost:9000 > /dev/null 2>&1; then
        echo "🔗 IOTA node detected, running integration tests..."
        pytest tests/test_iota_client.py --run-integration -v
    else
        echo "⚠️  No IOTA node running at localhost:9000, skipping integration tests"
    fi
else
    echo "❌ Unit tests failed!"
    exit 1
fi
