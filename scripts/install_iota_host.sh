#!/bin/bash
set -e

echo "📦 Instalando binário IOTA no host..."

# Extrai binário do container
CONTAINER_ID=$(docker create --rm iota-dev:latest)
docker cp ${CONTAINER_ID}:/usr/local/bin/iota /tmp/iota
docker cp ${CONTAINER_ID}:/usr/local/bin/iota-node /tmp/iota-node
docker rm ${CONTAINER_ID}

# Move para /usr/local/bin
sudo mv /tmp/iota /usr/local/bin/
sudo mv /tmp/iota-node /usr/local/bin/
sudo chmod +x /usr/local/bin/iota /usr/local/bin/iota-node

# Verifica
iota --version
iota-node --version

echo "✅ Binários instalados com sucesso!"
