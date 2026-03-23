#!/usr/bin/env python3
"""
exemplo/04_auto_transfer_network.py
Suba uma rede IOTA completa e faça transferências automáticas sem faucet manual

Este exemplo demonstra:
1. Subir rede IOTA com validators e gateway
2. Gerar contas automaticamente
3. Financiar contas com tokens via genesis
4. Fazer transferências programaticamente (sem faucet)
5. Consultar saldos e histórico de transações
"""

import sys
import os
import time
import json
import re
import subprocess
from pathlib import Path

# Adicionar projeto ao path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fogbed import FogbedExperiment, Container
from fogbed_iota import IotaNetwork
from fogbed_iota.accounts import AccountManager, IotaAccount
from fogbed_iota.client.transaction import SimpleTransaction, TransactionBuilder
from fogbed_iota.client.rpc_client import IotaRpcClient
from fogbed_iota.utils import get_logger
from mininet.log import setLogLevel

logger = get_logger(__name__)


def cleanup_previous_runs():
    """Remove containers e redes antigas"""
    print("🧹 Removendo execuções anteriores...")
    os.system("docker rm -f $(docker ps -aq --filter name='mn.') 2>/dev/null")
    os.system("sudo -n mn -c 2>/dev/null || true")  # -n: non-interactive, || true: ignore errors
    time.sleep(1)
    print("✅ Limpeza concluída\n")


def wait_for_network_ready(gateway_ip: str, gateway_rpc_port: int, max_retries: int = 30):
    """Aguarda rede estar pronta verificando RPC"""
    print(f"⏳ Aguardando rede IOTA ficar pronta em {gateway_ip}:{gateway_rpc_port}...")

    for i in range(max_retries):
        try:
            # Usar docker exec para testar RPC de dentro da rede
            cmd = (
                f"docker exec mn.gateway curl -s -X POST http://127.0.0.1:{gateway_rpc_port} "
                f"-H 'Content-Type: application/json' "
                f"-d '{{\"jsonrpc\":\"2.0\",\"method\":\"iota_getChainIdentifier\",\"params\":[],\"id\":1}}' "
                f"2>/dev/null"
            )
            result = os.popen(cmd).read()

            if "result" in result and "error" not in result:
                print(f"✅ Rede pronta! ({i+1}s)\n")
                return True
        except:
            pass

        print(f"  Tentativa {i+1}/{max_retries}...", end='\r')
        time.sleep(1)

    print(f"\n⚠️  Timeout aguardando rede (máximo {max_retries}s)")
    return False


def _extract_address_from_output(output) -> str:
    """Extrai endereço IOTA de dict/string retornado pela CLI."""
    if isinstance(output, dict):
        candidates = [
            output.get("iotaAddress"),
            output.get("address"),
            output.get("activeAddress"),
        ]
        nested = output.get("result")
        if isinstance(nested, dict):
            candidates.extend([
                nested.get("iotaAddress"),
                nested.get("address"),
                nested.get("activeAddress"),
            ])
        for value in candidates:
            if isinstance(value, str):
                m = re.search(r"(0x[a-fA-F0-9]{64})", value)
                if m:
                    return m.group(1)
        m = re.search(r"(0x[a-fA-F0-9]{64})", json.dumps(output))
        if m:
            return m.group(1)
        return ""

    m = re.search(r"(0x[a-fA-F0-9]{64})", str(output))
    return m.group(1) if m else ""


def _create_managed_account(cli, account_mgr: AccountManager, alias: str) -> IotaAccount:
    """Cria conta via `iota client new-address` no keystore ativo."""
    out = cli._execute(
        "iota client new-address --key-scheme ed25519 --json",
        timeout=30,
        capture_json=True,
    )
    address = _extract_address_from_output(out)
    if not address:
        raise RuntimeError(f"Falha ao criar conta {alias}: endereço não encontrado no output: {out}")

    account = IotaAccount(address=address, alias=alias)
    account_mgr.accounts[alias] = account
    return account


def create_test_accounts(client_container):
    """Cria contas de teste para demonstração"""
    print("👥 Gerando contas de teste...\n")

    account_mgr = AccountManager(client_container)
    from fogbed_iota.client.cli import IotaCLI
    cli = IotaCLI(client_container, network="localnet")

    # Alice deve existir no keystore atual para assinar sempre
    alice_addr = cli.get_active_address()
    if not alice_addr:
        alice_addr = cli.ensure_managed_address()
    alice = IotaAccount(address=alice_addr, alias="alice")
    account_mgr.accounts["alice"] = alice
    print(f"  ✅ Alice:   {alice.address} (keystore)")

    # Criar Bob/Charlie com new-address para garantir chave no mesmo keystore
    bob = _create_managed_account(cli, account_mgr, "bob")
    if bob.address.lower() == alice.address.lower():
        raise RuntimeError("Bob não pode reutilizar o endereço de Alice")
    print(f"  ✅ Bob:     {bob.address}")

    charlie = _create_managed_account(cli, account_mgr, "charlie")
    if charlie.address.lower() in {alice.address.lower(), bob.address.lower()}:
        raise RuntimeError("Charlie recebeu endereço duplicado, tente novamente")
    print(f"  ✅ Charlie: {charlie.address}")

    print()
    return account_mgr, [alice, bob, charlie]


def fund_accounts_via_transfer(client_container, accounts):
    """Financia contas via transfer da conta pré-existente com fundos de genesis"""
    print("💰 Financiando contas via transfer de conta pré-existente...\n")

    try:
        from fogbed_iota.client.cli import IotaCLI
        cli = IotaCLI(client_container, network="localnet")

        # Obter endereço do funder (ativo/primeiro com fundos)
        funder_address = cli.get_active_address()
        if not funder_address:
            funder_address = "0x05febd29e0f349b6fbfbed1f279481517f162c5653c5c98173cc1aa79d4d2fdd"

        # Valor a transferir em MIST (1 bilhão = 1 IOTA)
        amount_mist = 1_000_000_000  # 1 IOTA

        funded_count = 0
        for i, account in enumerate(accounts):
            account_names = ["Alice", "Bob", "Charlie"]
            try:
                if account.address.lower() == funder_address.lower():
                    print(f"  ⏭️  {account_names[i]} já é o funder/active-address (sem transfer)")
                    funded_count += 1
                    continue

                print(f"  ⏳ Transferindo para {account_names[i]}...", end="", flush=True)

                # PTB: split-coins + transfer
                # Sintaxe correta: @ na frente de addresses
                cmd = (
                    f"iota client ptb "
                    f"--split-coins gas '[{amount_mist}]' "
                    f"--assign coins "
                    f"--transfer-objects '[coins.0]' @{account.address} "
                    f"--sender @{funder_address} "
                    f"--gas-budget 50000000 "
                    f"--json"
                )

                result = cli._execute(cmd, timeout=45, capture_json=True)

                # Verificar sucesso
                success = False
                if isinstance(result, dict):
                    # Verificar estrutura de resultado bem-sucedido
                    if result.get("status") == "success":
                        success = True
                    elif "balanceChanges" in result:  # Transferência bem-sucedida
                        success = True
                    elif result.get("confirmedLocalExecution"):  # Transação local confirmada
                        success = True
                else:
                    success = ("success" in str(result).lower())

                if success:
                    # Validação pós-transfer: verificar se saldo realmente aumentou
                    time.sleep(2)  # Dar tempo para confirmação
                    balance = check_account_balance(client_container, account.address)
                    if balance > 0:
                        print(" ✅")
                        funded_count += 1
                    else:
                        print(" ⏳ (enviado, aguardando...)")
                        logger.warning(f"Transfer sent but balance still 0 for {account_names[i]}")
                else:
                    print(" ❌")
                    # Log detalhado do erro
                    logger.error(f"PTB failed for {account_names[i]}:")
                    if isinstance(result, dict):
                        logger.error(f"  Response: {result}")
                        if "error" in result:
                            logger.error(f"  Error detail: {result['error']}")
                    else:
                        logger.error(f"  Raw: {str(result)[:200]}")

                time.sleep(1)

            except Exception as e:
                print(f" ❌ (exceção: {str(e)[:30]}...)")
                logger.error(f"Funding error for {account_names[i]}: {str(e)}")

        print(f"\n  ✅ {funded_count}/{len(accounts)} contas financiadas\n")
        return funded_count > 0

    except Exception as e:
        logger.error(f"Erro ao financiar contas: {str(e)}")
        print(f"\n  ⚠️  Erro no financing: {str(e)}\n")
        return False


def check_account_balance(client_container, address: str):
    """Consulta saldo de uma conta via RPC"""
    try:
        cmd = (
            f"docker exec mn.client iota client gas {address} 2>&1"
        )
        result = os.popen(cmd).read()

        # Parse simples do output
        if "No gas coins" in result or "error" in result.lower():
            return 0

        # NOVO: Extrair valor do formato da CLI 1.15.0
        import re

        # Tenta novo formato (IOTA 1.15.0): procura por número de 10+ dígitos (NANOS)
        # Pattern: procura por número grande perto de "nanosBalance"
        match = re.search(r'nanosBalance[^\d]*(\d{10,})', result)
        if match:
            return int(match.group(1))

        # Fallback: procura por número com 10+ dígitos na tabela
        match = re.search(r'\b(\d{10,})\b', result)
        if match:
            return int(match.group(1))

        # Fallback antigo: tenta formato antigo
        match = re.search(r'balance:\s*(\d+)', result)
        if match:
            return int(match.group(1))

        return 0
    except Exception as e:
        logger.error(f"Erro ao consultar saldo: {e}")
        return 0


def execute_transfer(client_container, sender_address: str, recipient_address: str, amount: int):
    """Executa uma transferência IOTA entre contas"""
    print(f"\n💸 Transferindo {amount} MIST de {sender_address[:16]}... para {recipient_address[:16]}...")

    try:
        # Usar TransactionBuilder para criar transação programática
        tx = TransactionBuilder(
            sender=sender_address,
            gas_budget=10_000_000  # 10M MIST para gas
        )

        # Adicionar comando de transferência
        tx.transfer_iota([recipient_address], [amount])

        # Debug: mostrar comando gerado
        cmd = tx.build_cli_command()
        print(f"  🔧 Comando: {cmd[:150]}...")

        # Executar transação
        result = tx.execute(client_container)

        # Debug: mostrar resultado COMPLETO
        if 'raw_output' in result:
            print(f"  📡 Raw output:\n{result['raw_output']}\n")

        if result['success']:
            print(f"  ✅ Transferência bem-sucedida!")
            print(f"     Digest: {result.get('digest', 'N/A')[:16]}...")
            if 'gas_used' in result:
                print(f"     Gas usado: {result['gas_used']} MIST")
            return True
        else:
            print(f"  ❌ Transferência falhou: {result.get('error', 'Erro desconhecido')}")
            print(f"     Resultado completo: {result}")
            return False

    except Exception as e:
        print(f"  ❌ Erro ao executar transferência: {e}")
        logger.error(f"Transfer execution error: {e}")
        return False


def demo_multiple_transfers(client_container, accounts):
    """Demonstra múltiplas transferências em cadeia"""
    print("\n" + "="*60)
    print("🔄 DEMONSTRAÇÃO: Transferências em Cadeia")
    print("="*60)

    alice, bob, charlie = accounts

    # Simular transferência: Alice -> Bob
    print(f"\n1️⃣  Alice → Bob")
    execute_transfer(client_container, alice.address, bob.address, 100_000)

    time.sleep(2)

    # Simular transferência: Bob -> Charlie
    print(f"\n2️⃣  Bob → Charlie")
    execute_transfer(client_container, bob.address, charlie.address, 50_000)

    time.sleep(2)

    # Simular transferência: Charlie -> Alice
    print(f"\n3️⃣  Charlie → Alice")
    execute_transfer(client_container, charlie.address, alice.address, 25_000)


def print_summary(iota_net, gateway, account_mgr, accounts, client_container):
    """Imprime resumo da rede e contas"""
    print("\n" + "="*60)
    print("📊 RESUMO DA REDE IOTA")
    print("="*60)

    validators = [n for n in iota_net.nodes if n.role == 'validator']

    print(f"\n🏛️  ARQUITETURA:")
    print(f"  Validadores:     {len(validators)}")
    print(f"  Gateway:         {gateway.name} ({gateway.ip_addr})")
    print(f"  RPC Endpoint:    http://{gateway.ip_addr}:9000")
    print(f"  Métricas:        http://{gateway.ip_addr}:9184/metrics")

    print(f"\n👥 CONTAS CRIADAS:")
    for i, account in enumerate(accounts, 1):
        saldo = check_account_balance(client_container, account.address)
        print(f"  {i}. {account.alias.upper():8} | {account.address}")
        print(f"     Saldo: {saldo} MIST")

    print(f"\n💡 COMO FINANCIAR CONTAS:")
    print(f"  # Opção 1: Via faucet manual")
    print(f"  docker exec -it mn.client iota client faucet 0x<ADDRESS>")
    print(f"")
    print(f"  # Opção 2: Via genesis (editar network.py)")
    print(f"  Ver docs/architecture.md para mais detalhes")

    print(f"\n💡 COMANDOS ÚTEIS:")
    print(f"  # Acessar cliente CLI")
    print(f"  docker exec -it mn.client bash")
    print(f"")
    print(f"  # Verificar logs do gateway")
    print(f"  docker exec -it mn.gateway tail -f /app/iota.log")
    print(f"")
    print(f"  # Executar query RPC")
    print(f"  docker exec mn.client iota client addresses")
    print(f"")
    print(f"  # Ver transações de uma conta")
    print(f"  docker exec mn.client iota client txs <ADDRESS>")
    print(f"")
    print(f"  # Verificar saldo")
    print(f"  docker exec mn.client iota client gas <ADDRESS>")


def main():
    """Função principal"""
    print("\n" + "="*60)
    print("🚀 REDE IOTA COM TRANSFERÊNCIAS AUTOMÁTICAS")
    print("="*60)

    # Limpar execuções anteriores
    cleanup_previous_runs()

    # Configurar logging
    setLogLevel('info')

    # ============== CRIAR INFRAESTRUTURA ==============
    print("📦 Criando infraestrutura Fogbed...\n")

    exp = FogbedExperiment()

    # Criar datacenter virtual
    print("  ☁️  Criando datacenter 'cloud'...")
    cloud = exp.add_virtual_instance("cloud")

    # Criar rede IOTA
    print("  🌐 Criando rede IOTA...")
    iota_net = IotaNetwork(experiment=exp, image='iota-dev:latest')

    # ============== ADICIONAR NODOS ==============
    print("\n🔗 Adicionando nodos à rede...\n")

    # 4 Validadores
    print("  📦 Validadores:")
    for i in range(1, 5):
        validator = iota_net.add_validator(f'validator{i}', f'10.0.0.{10+i}')
        print(f"     ✅ {validator.name} ({validator.ip_addr})")

    # 1 Gateway (fullnode com RPC)
    print("\n  📦 Gateway:")
    gateway = iota_net.add_gateway('gateway', '10.0.0.100')
    print(f"     ✅ {gateway.name} ({gateway.ip_addr}:9000)")

    # 1 Cliente CLI
    print("\n  📦 Cliente CLI:")
    client = Container(
        name='client',
        dimage='iota-dev:latest',
        ip='10.0.0.200',
        dcmd='tail -f /dev/null'
    )
    iota_net.set_client(client)
    print(f"     ✅ {client.name} ({client.ip})")

    # ============== CONFIGURAR TOPOLOGIA ==============
    print("\n🔗 Anexando nodos ao datacenter...")
    iota_net.attach_to_experiment(datacenter_name="cloud")
    print("   ✅ Topologia configurada (estrela)\n")

    # ============== INICIAR FOGBED ==============
    print("▶️  Iniciando rede Fogbed...")
    exp.start()
    print("   ✅ Rede Fogbed iniciada\n")

    # ============== INICIAR IOTA ==============
    print("⚙️  Configurando nodos IOTA...")
    print("   (gerando genesis, patcheando configs, iniciando processos)...")
    iota_net.start()
    print("   ✅ Nodos IOTA iniciados\n")

    # ============== AGUARDAR REDE ==============
    print("⏳ Aguardando rede ficar operacional...")
    if not wait_for_network_ready(gateway.ip_addr, gateway.rpc_port):
        print("❌ Rede não ficou pronta a tempo. Abortando.")
        exp.stop()
        return

    # ============== CRIAR CONTAS ==============
    print("✅ Rede IOTA operacional!\n")
    account_mgr, accounts = create_test_accounts(client)

    # ============== FINANCIAR CONTAS ==============
    print("💰 Etapa de Funding...")
    fund_accounts_via_transfer(client, accounts)

    # Aguardar confirmação
    print("⏳ Aguardando confirmação de fundos (10 segundos)...")
    time.sleep(10)

    # ============== FAZER TRANSFERÊNCIAS ==============
    print("💸 Iniciando demonstração de transferências programáticas...\n")
    demo_multiple_transfers(client, accounts)

    # ============== RESUMO ==============
    print_summary(iota_net, gateway, account_mgr, accounts, client)

    # ============== AGUARDAR INPUT ==============
    print("\n⏸️  Sistema operacional. Pressione ENTER para encerrar...")
    try:
        input()
    except KeyboardInterrupt:
        print("\n")

    # ============== FINALIZAR ==============
    print("\n🛑 Encerrando rede...")
    exp.stop()
    print("✅ Finalizado!\n")


if __name__ == '__main__':
    main()
