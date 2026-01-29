# install.sh - Instalador para qualquer máquina

#!/bin/bash
set -e

REPO_URL="https://github.com/seu-usuario/fogbed-iota"
INSTALL_DIR="/opt/fogbed-iota"

echo "🚀 Instalando fogbed-iota..."

# Verificar root
if [ "$EUID" -ne 0 ]; then 
   echo "Por favor, execute como root: sudo ./install.sh"
   exit 1
fi

# Clonar repositório
git clone "$REPO_URL" "$INSTALL_DIR" || \
    (cd "$INSTALL_DIR" && git pull)

cd "$INSTALL_DIR"

# Build da imagem
docker build -f docker/Dockerfile -t iota-dev:latest .

# Extrair binário para o sistema (opcional)
CONTAINER_ID=$(docker create --rm iota-dev:latest)
docker cp ${CONTAINER_ID}:/usr/local/bin/iota /usr/local/bin/
docker cp ${CONTAINER_ID}:/usr/local/bin/iota-node /usr/local/bin/
docker rm ${CONTAINER_ID}
chmod +x /usr/local/bin/iota /usr/local/bin/iota-node

# Instalar Python dependencies
pip3 install fogbed --break-system-packages

echo "✅ Instalação completa!"
echo ""
echo "Para executar:"
echo "  cd $INSTALL_DIR"
echo "  sudo python3 examples/01_basic_network.py"
