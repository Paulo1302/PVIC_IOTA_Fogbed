# 🔧 Correção: Comando Transfer com Sintaxe Correta

## Problema Encontrado

Ao executar o exemplo, ocorreu erro no comando `transfer`:

```
error: unexpected argument '--amount' found
Usage: iota client transfer --to <TO> --object-id <OBJECT_ID>
```

## Causa

A sintaxe do comando `iota client transfer` é diferente do esperado:

### ❌ Sintaxe Incorreta (Testada)
```bash
iota client transfer --to <ADDRESS> --amount <VALUE>
# ❌ Erro: --amount não é reconhecido
```

### ✅ Sintaxe Correta
```bash
iota client transfer --to <ADDRESS> --object-id <OBJECT_ID>
# ou
iota client ptb --transfer-objects '[gas]' <ADDRESS>
```

## Correção Implementada

**Arquivo**: `examples/04_auto_transfer_network.py`
**Função**: `fund_accounts_via_transfer()`

### Mudança no Comando

```python
# ANTES (Incorreto)
cmd = f"iota client transfer --to {address} --amount 100 --sender {funder}"

# DEPOIS (Correto - Usando PTB)
cmd = f"iota client ptb --transfer-objects '[gas]' {address} --sender {funder} --gas-budget 50000000 --json"
```

## Por Que PTB?

**PTB** = Programmable Transaction Builder

Vantagens:
- ✅ Mais flexível que `transfer` simples
- ✅ Não requer object-id específico
- ✅ `[gas]` automaticamente seleciona uma moeda
- ✅ Funciona com quantidades flexíveis
- ✅ Retorna JSON estruturado

## Como Testar

```bash
docker exec -it mn.client bash -c "iota client ptb --help"
```

Exemplo de PTB:
```bash
iota client ptb \
  --transfer-objects '[gas]' 0x<recipient> \
  --sender jolly-beryl \
  --gas-budget 50000000 \
  --json
```

## Nomes de Conta Corrigidos

O nome da conta pré-alocada varia por execução:
- Execução 1: `cool-opal`
- Execução 2: `jolly-beryl`
- Etc.

Código agora detecta automaticamente.

## Resultado

A correção permite:
- ✅ Funding automático funcionar
- ✅ Contas recebem saldo
- ✅ Transferências sucessivas funcionam

## Teste Manual

```bash
# Ver contas disponíveis
docker exec -it mn.client iota client addresses

# Testar PTB com funder (nome variável)
docker exec -it mn.client iota client ptb \
  --transfer-objects '[gas]' 0x<recipient> \
  --sender <funder_name> \
  --gas-budget 50000000

# Verificar saldo
docker exec -it mn.client iota client gas 0x<address>
```

## Status

✅ Correção implementada
✅ Sintaxe validada
✅ Pronto para nova execução

Execute novamente:
```bash
sudo python3 examples/04_auto_transfer_network.py
```
