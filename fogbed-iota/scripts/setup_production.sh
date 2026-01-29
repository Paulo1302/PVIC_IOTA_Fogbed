# scripts/setup_production.sh

#!/bin/bash
set -e

echo "🚀 Configurando fogbed-iota para produção..."

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# 1. Verificar Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker não encontrado. Instale o Docker primeiro."
    exit 1
fi
echo "✅ Docker encontrado"

# 2. Verificar se imagem existe
if ! docker images | grep -q "iota-dev"; then
    echo "📦 Imagem iota-dev não encontrada. Construindo..."
    docker build -f docker/Dockerfile -t iota-dev:latest .
fi
echo "✅ Imagem iota-dev:latest disponível"

# 3. Verificar Python e dependências
if ! python3 -c "import fogbed" 2>/dev/null; then
    echo "📦 Instalando Fogbed..."
    pip3 install fogbed --break-system-packages 2>/dev/null || \
    pip3 install fogbed
fi
echo "✅ Fogbed instalado"

# 4. Verificar módulo fogbed_iota
python3 << 'PYEOF'
import sys
import os
sys.path.insert(0, os.getcwd())
try:
    from fogbed_iota import IotaNetwork
    print("✅ Módulo fogbed_iota disponível")
except ImportError as e:
    print(f"❌ Erro ao importar fogbed_iota: {e}")
    sys.exit(1)
PYEOF

# 5. Verificar permissões
if [ "$EUID" -ne 0 ]; then 
    echo "⚠️  Este script precisa de privilégios sudo para configurar a rede"
    echo "   Execute: sudo ./scripts/setup_production.sh"
fi

echo ""
echo "✅ Setup completo!"
echo ""
echo "📝 Próximos passos:"
echo "   1. Execute: sudo python3 examples/01_basic_network.py"
echo "   2. Em caso de erro, limpe com: sudo mn -c"
echo ""
