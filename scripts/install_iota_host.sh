#!/bin/bash
set -e

echo "📦 Instalando binários IOTA no host..."

echo "⚠️  Esta ação irá extrair os binários da imagem Docker e copiá-los para /usr/local/bin/."
read -p "Deseja continuar? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]
then
    echo "❌ Instalação cancelada."
    exit 1
fi

echo "Extraindo binários do container 'iota-dev:latest'..."
CONTAINER_ID=$(docker create --rm iota-dev:latest)
docker cp ${CONTAINER_ID}:/usr/local/bin/iota /tmp/iota
docker cp ${CONTAINER_ID}:/usr/local/bin/iota-node /tmp/iota-node
docker rm ${CONTAINER_ID}

echo "Movendo para /usr/local/bin/ (requer senha de root)..."
sudo mv /tmp/iota /usr/local/bin/
sudo mv /tmp/iota-node /usr/local/bin/
sudo chmod +x /usr/local/bin/iota /usr/local/bin/iota-node

echo "Testando instalação..."
iota --version
iota-node --version

echo "✅ Binários instalados com sucesso!"
