#!/bin/bash
# 🚀 SCRIPT: Executar Exemplo 04 Corrigido
#
# Este script limpa execuções anteriores e roda o exemplo 04
# com a correção de transferências automáticas implementada.

set -e

echo ""
echo "╔════════════════════════════════════════════════════════════════════════╗"
echo "║                                                                        ║"
echo "║  🚀 EXECUTAR REDE IOTA COM TRANSFERÊNCIAS AUTOMÁTICAS (Exemplo 04)    ║"
echo "║                                                                        ║"
echo "╚════════════════════════════════════════════════════════════════════════╝"
echo ""

# Determinar caminho do projeto
PROJECT_DIR="/home/paulo/Documentos/PVIC_IOTA_Fogbed"

if [ ! -d "$PROJECT_DIR" ]; then
    echo "❌ ERRO: Diretório do projeto não encontrado: $PROJECT_DIR"
    exit 1
fi

echo "📍 Projeto: $PROJECT_DIR"
echo ""

# Passo 1: Limpar execuções anteriores
echo "═══════════════════════════════════════════════════════════════════════════"
echo "PASSO 1: Limpando execuções anteriores..."
echo "═══════════════════════════════════════════════════════════════════════════"
echo ""

echo "  🧹 Removendo containers Mininet..."
sudo docker rm -f $(sudo docker ps -aq --filter "name=mn." 2>/dev/null) 2>/dev/null || true
echo "     ✅ Containers removidos"

echo ""
echo "  🧹 Limpando rede Mininet..."
sudo mn -c 2>/dev/null || true
echo "     ✅ Rede limpa"

echo ""
echo "  ⏳ Aguardando 2 segundos..."
sleep 2

echo ""

# Passo 2: Validar que a correção foi aplicada
echo "═══════════════════════════════════════════════════════════════════════════"
echo "PASSO 2: Validando correção implementada..."
echo "═══════════════════════════════════════════════════════════════════════════"
echo ""

cd "$PROJECT_DIR"

echo "  🔍 Verificando se --json está no TransactionBuilder..."
if grep -q 'cmd_parts.append("--json")' fogbed_iota/client/transaction.py; then
    echo "     ✅ Flag --json presente"
else
    echo "     ❌ ERRO: Flag --json não encontrada"
    exit 1
fi

echo ""
echo "  🔍 Verificando se @ prefix está implementado para sender..."
if grep -q 'sender_with_prefix = self.sender if self.sender.startswith' fogbed_iota/client/transaction.py; then
    echo "     ✅ Prefix @ para sender presente"
else
    echo "     ❌ ERRO: Prefix @ para sender não encontrado"
    exit 1
fi

echo ""
echo "  🔍 Verificando se @ prefix está implementado para recipient..."
if grep -q 'recipient_with_prefix = self.recipient if self.recipient.startswith' fogbed_iota/client/transaction.py; then
    echo "     ✅ Prefix @ para recipient presente"
else
    echo "     ❌ ERRO: Prefix @ para recipient não encontrado"
    exit 1
fi

echo ""

# Passo 3: Executar teste rápido
echo "═══════════════════════════════════════════════════════════════════════════"
echo "PASSO 3: Executando teste rápido da correção..."
echo "═══════════════════════════════════════════════════════════════════════════"
echo ""

if python3 test_transaction_fix.py 2>&1 | grep -q "TODOS OS TESTES PASSARAM"; then
    echo "  ✅ Teste passou!"
else
    echo "  ❌ Teste falhou!"
    exit 1
fi

echo ""

# Passo 4: Executar exemplo 04
echo "═══════════════════════════════════════════════════════════════════════════"
echo "PASSO 4: Executando exemplo 04..."
echo "═══════════════════════════════════════════════════════════════════════════"
echo ""

echo "  🚀 Iniciando rede IOTA com transferências automáticas..."
echo ""

sudo PYTHONPATH="$(pwd)" /opt/fogbed/venv/bin/python3 examples/04_auto_transfer_network.py

echo ""
echo "═══════════════════════════════════════════════════════════════════════════"
echo "✅ EXECUÇÃO COMPLETA"
echo "═══════════════════════════════════════════════════════════════════════════"
echo ""
echo "  ✅ Rede IOTA iniciada com sucesso"
echo "  ✅ Contas criadas e financiadas"
echo "  ✅ Transferências automáticas executadas"
echo ""
echo "  📝 Próximos passos:"
echo "     - Inspeccionar containers: docker ps | grep mn."
echo "     - Acessar cliente: docker exec -it mn.client bash"
echo "     - Verificar saldos: docker exec mn.client iota client gas <address>"
echo ""

exit 0
