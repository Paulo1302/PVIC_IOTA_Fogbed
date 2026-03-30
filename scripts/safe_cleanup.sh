#!/bin/bash

# Safe Cleanup Script for PVIC_IOTA_Fogbed
# Este script lista e remove APENAS containers deste projeto com confirmação

echo "=============================================="
echo "🧹 Limpeza Segura - PVIC_IOTA_Fogbed"
echo "=============================================="
echo ""

# Verificar se há containers Mininet
containers=$(docker ps -a --filter "name=mn." --format "{{.ID}}")

if [ -z "$containers" ]; then
    echo "✅ Nenhum container Mininet encontrado."
    echo ""
    
    # Limpar Mininet mesmo assim (por segurança)
    echo "🧹 Limpando configurações Mininet..."
    sudo mn -c 2>/dev/null || true
    echo "✅ Concluído!"
    exit 0
fi

echo "🔍 Containers Mininet encontrados:"
echo ""
docker ps -a --filter "name=mn." --format "table {{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Image}}"
echo ""

echo "=============================================="
echo "⚠️  ATENÇÃO"
echo "=============================================="
echo "Este script irá remover os containers listados acima."
echo ""
echo "Verifique se são APENAS containers deste projeto:"
echo "  - mn.validator*, mn.gateway, mn.client"
echo "  - mn.iota*"
echo ""
echo "Se houver containers de OUTROS PROJETOS na lista,"
echo "CANCELE e remova manualmente os containers específicos:"
echo "  docker rm -f <container_id_específico>"
echo ""

# Solicitar confirmação
read -p "Deseja continuar? Digite 'sim' para confirmar: " confirm

if [ "$confirm" != "sim" ]; then
    echo ""
    echo "❌ Operação cancelada pelo usuário."
    echo ""
    echo "Para remover containers específicos, use:"
    echo "  docker rm -f <container_id>"
    exit 1
fi

echo ""
echo "🧹 Removendo containers Mininet..."

# Remover containers
docker rm -f $(docker ps -aq --filter "name=mn.") 2>/dev/null

if [ $? -eq 0 ]; then
    echo "✅ Containers removidos"
else
    echo "⚠️  Erro ao remover alguns containers"
fi

echo ""
echo "🧹 Limpando configurações Mininet..."
sudo mn -c 2>/dev/null || true

echo ""
echo "=============================================="
echo "✅ Limpeza concluída!"
echo "=============================================="
