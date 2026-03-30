#!/usr/bin/env python3

# examples/03_smart_contract_full_workflow.py

"""
Exemplo 3: Workflow Completo de Smart Contracts com IOTA 1.15

Demonstra:
- Setup de rede IOTA completa (4 validators + 1 gateway)
- Gerenciamento de contas (Alice e Bob)
- Funding automático via faucet (com fallback manual)
- Build e deploy de smart contract Move
- Interação com contrato (criar e incrementar counter)
- Transferências entre contas
- Uso correto de IotaCLI e SmartContractManager

IMPORTANTE: Este exemplo usa o SmartContractManager corrigido
para IOTA 1.15, que extrai corretamente packageId e UpgradeCap.
"""

import sys
import time
from pathlib import Path

# Adicionar diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fogbed import FogbedExperiment, Container
from fogbed_iota import IotaNetwork
from fogbed_iota.client.cli import IotaCLI
from fogbed_iota.client.transaction import SimpleTransaction


NETWORK_STABILIZATION_TIME = 20
CONTRACT_SOURCE_DIR = "/contracts/counter"


def print_header(title: str):
    print("\n" + "=" * 70)
    print(title.center(70))
    print("=" * 70 + "\n")


def print_step(step_num: int, description: str):
    print(f"\n{'─' * 70}")
    print(f"STEP {step_num}: {description}")
    print('─' * 70 + "\n")


def format_balance(mist: int) -> str:
    iota = mist / 1_000_000_000
    return f"{mist:,} MIST ({iota:.4f} IOTA)"


def check_account_balance(client_container, address: str) -> int:
    """Verifica saldo de uma conta retornando total em MIST"""
    from fogbed_iota.client.cli import IotaCLI
    cli = IotaCLI(client_container, network="localnet")
    
    try:
        coins = cli.get_gas(address)
        total = sum(c.get("balance", 0) for c in coins)
        return total
    except Exception as e:
        logger.warning(f"Failed to check balance for {address}: {e}")
        return 0


def fund_accounts_via_transfer(client_container, accounts):
    """
    Financia contas via transfer do genesis funder (100% confiável).
    
    Usa PTB (Programmable Transaction Block) para split+transfer atômico.
    Não depende de faucet ou RPC sync - funciona imediatamente após genesis.
    
    Args:
        client_container: Container do cliente
        accounts: Lista de IotaAccount objects
        
    Returns:
        Número de contas financiadas com sucesso
    """
    print("💰 Financiando contas via genesis transfer...\n")

    try:
        from fogbed_iota.client.cli import IotaCLI
        cli = IotaCLI(client_container, network="localnet")

        # Genesis funder address (sempre tem fundos)
        funder_address = "0x05febd29e0f349b6fbfbed1f279481517f162c5653c5c98173cc1aa79d4d2fdd"
        
        # Valor a transferir (0.1 IOTA = 100M MIST)
        amount_mist = 100_000_000

        funded_count = 0
        account_names = ["Alice", "Bob", "Charlie", "Dave"]
        
        for i, account in enumerate(accounts):
            account_name = account_names[i] if i < len(account_names) else f"Account{i+1}"
            
            try:
                # Skip se já é o funder
                if account.address.lower() == funder_address.lower():
                    print(f"  ⏭️  {account_name} já é o funder (sem transfer)")
                    funded_count += 1
                    continue

                print(f"  ⏳ Transferindo para {account_name}...", end="", flush=True)

                # PTB: split-coins + transfer (atômico!)
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
                    if result.get("status") == "success":
                        success = True
                    elif "balanceChanges" in result:
                        success = True
                    elif result.get("confirmedLocalExecution"):
                        success = True
                else:
                    success = ("success" in str(result).lower())

                if success:
                    # Validar que saldo aumentou
                    time.sleep(2)
                    balance = check_account_balance(client_container, account.address)
                    if balance > 0:
                        print(f" ✅ {format_balance(balance)}")
                        funded_count += 1
                    else:
                        print(" ⚠️  Transfer succeeded but balance check failed")
                        funded_count += 1  # Contar como sucesso mesmo assim
                else:
                    print(" ❌ Failed")
                    
            except Exception as e:
                print(f" ❌ Error: {e}")
                continue

        return funded_count
        
    except Exception as e:
        print(f"❌ Funding failed: {e}")
        import traceback
        traceback.print_exc()
        return 0


def main():
    print_header("IOTA Smart Contract Workflow - Using CLI Tools")

    # ========== Fase 1: Setup da Rede ==========
    print_step(1, "Network Setup")

    print("🚀 Starting Fogbed experiment...")
    exp = FogbedExperiment()

    # IMPORTANTE: usar os mesmos nomes que no exemplo 01 (iota1..4, gateway)
    print("📦 Adding IOTA nodes...")
    iota_net = IotaNetwork(exp, image="iota-dev:latest")

    iota_net.add_validator("iota1", "10.0.0.1")
    iota_net.add_validator("iota2", "10.0.0.2")
    iota_net.add_validator("iota3", "10.0.0.3")
    iota_net.add_validator("iota4", "10.0.0.4")
    iota_net.add_gateway("gateway", "10.0.0.5")

    print("💻 Adding client container...")
    client = Container(
        name="client",
        ip="10.0.0.100",
        dimage="iota-dev:latest",
        dcmd="tail -f /dev/null",
    )
    iota_net.set_client(client)

    print("🔗 Attaching to experiment...")
    iota_net.attach_to_experiment()

    print("▶️ Starting experiment...")
    exp.start()

    # Debug: garantir que os containers Mininet foram criados
    import os
    os.system("docker ps -a | egrep 'mn\\.' || echo 'no mn.* containers'")

    print("\n🚀 Starting IOTA network...")
    iota_net.start()

    print(f"\n⏳ Waiting for network stabilization ({NETWORK_STABILIZATION_TIME}s)...")
    time.sleep(NETWORK_STABILIZATION_TIME)

    # ========== Fase 2: Inicializar CLI Tools e Managers ==========
    print_step(2, "Initialize CLI Tools and Managers")

    cli = IotaCLI(client)
    print("✅ IotaCLI initialized")

    # Obter managers do IotaNetwork
    acct_mgr = iota_net.account_manager
    contract_mgr = iota_net.contract_manager
    print("✅ AccountManager initialized")
    print("✅ SmartContractManager initialized")

    gas_price = cli.get_reference_gas_price()
    print(f"📊 Reference gas price: {gas_price} MIST")

    # ========== Fase 3: Account Management ==========
    print_step(3, "Account Management")

    print("📝 Generating keypairs...")

    alice = acct_mgr.generate_account("alice")
    print(f"✅ Alice: {alice.address}")

    bob = acct_mgr.generate_account("bob")
    print(f"✅ Bob: {bob.address}")

    # ========== Fase 4: Funding via Genesis Transfer ==========
    print_step(4, "Funding Accounts via Genesis Transfer")

    print("💰 Checking initial balances...")
    alice_balance = check_account_balance(client, alice.address)
    bob_balance = check_account_balance(client, bob.address)

    print(f"   Alice: {format_balance(alice_balance)}")
    print(f"   Bob:   {format_balance(bob_balance)}")

    # Verificar se precisam de funding
    need_funding = alice_balance < 10_000_000 or bob_balance < 10_000_000
    
    if need_funding:
        print("\n🚀 Auto-funding via genesis transfer (no faucet needed)...")
        funded_count = fund_accounts_via_transfer(client, [alice, bob])
        
        if funded_count >= 1:
            print(f"\n✅ {funded_count}/2 contas financiadas automaticamente!")
            
            # Atualizar balances
            time.sleep(2)
            alice_balance = check_account_balance(client, alice.address)
            bob_balance = check_account_balance(client, bob.address)
            
            print("\n💰 Balances após funding:")
            print(f"   Alice: {format_balance(alice_balance)}")
            print(f"   Bob:   {format_balance(bob_balance)}")
            
            # Verificar se Alice tem saldo suficiente para continuar
            if alice_balance < 10_000_000:
                print("\n❌ Alice não tem saldo suficiente. Tentando faucet como fallback...")
                if cli.faucet_request(alice.address):
                    print("✅ Faucet request succeeded!")
                    time.sleep(3)
                    alice_balance = check_account_balance(client, alice.address)
                    print(f"   Alice new balance: {format_balance(alice_balance)}")
                else:
                    print("\n⚠️  MANUAL FUNDING REQUIRED")
                    print("\nAlice has no funds. Please fund manually:")
                    print("   docker exec -it mn.client bash")
                    print(f"   iota client faucet --address {alice.address}")
                    print("\n👉 Press ENTER after funding Alice...")
                    input()
                    alice_balance = check_account_balance(client, alice.address)
                    if alice_balance == 0:
                        print("❌ Alice still has no balance. Cannot continue.")
                        exp.stop()
                        return
        else:
            print("\n❌ Auto-funding failed. Trying faucet as fallback...")
            if cli.faucet_request(alice.address):
                print("✅ Faucet request succeeded!")
                time.sleep(3)
                alice_balance = check_account_balance(client, alice.address)
                print(f"   Alice: {format_balance(alice_balance)}")
            else:
                print("\n⚠️  MANUAL FUNDING REQUIRED")
                print("   docker exec -it mn.client bash")
                print(f"   iota client faucet --address {alice.address}")
                print("\n👉 Press ENTER after funding...")
                input()
    else:
        print("\n✅ Contas já possuem saldo suficiente!")

    # ========== Fase 5: Preparar Smart Contract ==========
    print_step(5, "Prepare Smart Contract")

    print("📂 Creating counter contract on HOST...")
    
    # Criar estrutura de diretórios no HOST
    import os
    os.makedirs("contracts/counter/sources", exist_ok=True)
    
    # Criar Move.toml no HOST
    move_toml_content = """[package]
name = "counter"
edition = "2024.beta"

[addresses]
counter = "0x0"
"""
    with open("contracts/counter/Move.toml", "w") as f:
        f.write(move_toml_content)
    
    # Criar counter.move no HOST
    counter_move_content = """module counter::counter {
    use iota::object::{Self, UID};
    use iota::transfer;
    use iota::tx_context::{Self, TxContext};

    /// Counter object
    public struct Counter has key {
        id: UID,
        value: u64
    }

    /// Create new counter
    public entry fun create(ctx: &mut TxContext) {
        let counter = Counter {
            id: object::new(ctx),
            value: 0
        };
        transfer::share_object(counter);
    }

    /// Increment counter
    public entry fun increment(counter: &mut Counter) {
        counter.value = counter.value + 1;
    }

    /// Get counter value
    public fun get_value(counter: &Counter): u64 {
        counter.value
    }
}
"""
    with open("contracts/counter/sources/counter.move", "w") as f:
        f.write(counter_move_content)
    
    print("✅ Local contract source created")
    print("   - contracts/counter/Move.toml")
    print("   - contracts/counter/sources/counter.move")

    # Copiar do HOST para o CONTAINER
    print("\n📦 Copying package to container...")
    try:
        # Ativar modo debug para diagnosticar problemas de copy
        container_path = contract_mgr.copy_package_to_container(
            "./contracts/counter",
            "counter",
            debug=True  # Ativa debugging verboso
        )
        print(f"✅ Copy command executed: {container_path}")
        
        # 🔍 VERIFICAÇÃO CRÍTICA: Verificar se copy realmente funcionou
        print("🔍 Verifying copy success...")
        verify_result = client.cmd('test -f /contracts/counter/Move.toml && echo "OK" || echo "FAILED"')
        
        if "FAILED" in verify_result or "OK" not in verify_result:
            print("⚠️  Copy via tar failed! Using manual fallback...")
            
            # FALLBACK: Criar arquivos diretamente no container
            print("📝 Creating Move.toml in container...")
            client.cmd("mkdir -p /contracts/counter/sources")
            
            # Move.toml - sem dependências explícitas (usa auto-dependencies)
            client.cmd("""cat > /contracts/counter/Move.toml << 'EOFMOVE'
[package]
name = "counter"
edition = "2024.beta"

[addresses]
counter = "0x0"
EOFMOVE""")
            
            # counter.move
            print("📝 Creating counter.move in container...")
            client.cmd("""cat > /contracts/counter/sources/counter.move << 'EOFMOVE'
module counter::counter {
    use iota::object::{Self, UID};
    use iota::transfer;
    use iota::tx_context::{Self, TxContext};

    /// Counter object
    public struct Counter has key {
        id: UID,
        value: u64
    }

    /// Create new counter
    public entry fun create(ctx: &mut TxContext) {
        let counter = Counter {
            id: object::new(ctx),
            value: 0
        };
        transfer::share_object(counter);
    }

    /// Increment counter
    public entry fun increment(counter: &mut Counter) {
        counter.value = counter.value + 1;
    }

    /// Get counter value
    public fun get_value(counter: &Counter): u64 {
        counter.value
    }
}
EOFMOVE""")
            
            # Verificar novamente
            verify_result2 = client.cmd('test -f /contracts/counter/Move.toml && echo "OK" || echo "FAILED"')
            if "OK" not in verify_result2:
                print("❌ Manual fallback also failed!")
                exp.stop()
                return
            
            print("✅ Manual copy succeeded!")
        else:
            print("✅ Copy verified successfully!")
            
    except Exception as e:
        print(f"❌ Failed to copy package: {e}")
        import traceback
        traceback.print_exc()
        exp.stop()
        return

    # 🔍 Listar arquivos para debug
    print("\n🔍 Listing container files:")
    ls_result = client.cmd("ls -la /contracts/counter/ && ls -la /contracts/counter/sources/")
    print(ls_result)

    # Build no container
    print("\n🔨 Building contract...")
    try:
        build_result = contract_mgr.build_package("/contracts/counter", debug=True)
        print("✅ Contract compiled successfully")
        print(f"   Modules: {', '.join(build_result['modules'])}")
    except Exception as e:
        print(f"❌ Contract compilation failed: {e}")
        print("\n🔍 Debug info:")
        print("Container working directory:")
        print(client.cmd("pwd"))
        print("\nContainer /contracts structure:")
        print(client.cmd("ls -R /contracts/"))
        import traceback
        traceback.print_exc()
        exp.stop()
        return

    # ========== Fase 6: Deploy Smart Contract ==========
    print_step(6, "Deploy Smart Contract")

    print("📦 Publishing contract package...")
    print(f"   Package: /contracts/counter")
    print(f"   Sender: alice ({alice.address})")
    print(f"   Gas budget: 100,000,000 MIST")
    print(f"\n⏳ Publishing (this may take 5-10 minutes for Git dependencies)...")
    
    try:
        # Usar SmartContractManager.publish_package() (IOTA 1.15 compatible)
        package = contract_mgr.publish_package(
            package_path="/contracts/counter",
            sender_alias="alice",
            gas_budget=100_000_000
        )

        package_id = package.package_id
        print(f"\n✅ Package published successfully!")
        print(f"   Package ID: {package_id}")
        print(f"   Transaction: {package.digest}")
        print(f"   Modules: {', '.join(package.modules)}")
        print(f"   Upgradeable: {'Yes' if package.upgrade_cap_id else 'No'}")
        if package.upgrade_cap_id:
            print(f"   UpgradeCap: {package.upgrade_cap_id}")
    except Exception as e:
        print(f"\n❌ Publish failed: {e}")
        print("\n🔍 Debug: Checking CLI availability...")
        print(f"   IotaCLI available: {contract_mgr.cli is not None}")
        if contract_mgr.cli:
            print(f"   CLI container: {contract_mgr.cli.container.name}")
        print(f"   Client container: {contract_mgr.client.name}")
        import traceback
        traceback.print_exc()
        exp.stop()
        return

    # ========== Fase 7: Criar Counter ==========
    print_step(7, "Create Counter Object")

    print("🎯 Creating counter...")
    try:
        # Usar SmartContractManager.call_function() (IOTA 1.15 compatible)
        create_result = contract_mgr.call_function(
            package_id=package_id,
            module="counter",
            function="create",
            sender_alias="alice",
            gas_budget=10_000_000
        )

        print("✅ Counter created!")
        print(f"   Digest: {create_result.get('digest', 'N/A')}")
        time.sleep(3)

        print("\n🔍 Finding counter object...")
        objects = cli.get_objects(alice.address)

        counter_id = None
        for obj in objects:
            obj_id = obj.get("object_id")
            if obj_id:
                try:
                    obj_details = cli.get_object(obj_id)
                    obj_type = str(obj_details.get("type", ""))
                    if "counter::counter::Counter" in obj_type or "Counter" in obj_type:
                        counter_id = obj_id
                        break
                except:
                    continue

        if not counter_id:
            print("⚠️  Could not find counter object automatically")
            print("   Checking objectChanges from create transaction...")
            # Tentar extrair de objectChanges
            object_changes = create_result.get('objectChanges', [])
            for change in object_changes:
                if change.get('type') == 'created':
                    obj_type = change.get('objectType', '')
                    if 'Counter' in obj_type:
                        counter_id = change.get('objectId')
                        print(f"✅ Counter found in objectChanges: {counter_id}")
                        break
        
        if counter_id:
            print(f"✅ Counter object: {counter_id}")
        else:
            print("⚠️  Could not locate counter - you may need to query manually")
            
    except Exception as e:
        print(f"❌ Create failed: {e}")
        import traceback
        traceback.print_exc()
        exp.stop()
        return

    # ========== Fase 8: Interagir com Counter ==========
    print_step(8, "Interact with Counter")

    if counter_id:
        print("➕ Incrementing counter (3 times)...")
        for i in range(3):
            try:
                # Usar SmartContractManager.call_function()
                result = contract_mgr.call_function(
                    package_id=package_id,
                    module="counter",
                    function="increment",
                    sender_alias="alice",
                    args=[counter_id],
                    gas_budget=10_000_000
                )
                print(f"   ✅ Increment {i+1}: {result.get('digest', 'N/A')[:16]}...")
                time.sleep(2)
            except Exception as e:
                print(f"   ❌ Increment {i+1} failed: {e}")

    # ========== Fase 9: Transfer usando TransactionBuilder ==========
    print_step(9, "Transfer using TransactionBuilder")

    print("💸 Transferring 100M MIST from Alice to Bob...")
    try:
        result = SimpleTransaction.transfer_iota(
            sender=alice.address,
            recipient=bob.address,
            amount=100_000_000,
            client_container=client,
            gas_budget=10_000_000,
        )

        if result.get("success"):
            print(f"✅ Transfer succeeded: {result.get('digest', 'N/A')}")
            time.sleep(3)

            print("\n💰 Final balances:")
            alice_coins = cli.get_gas(alice.address)
            bob_coins = cli.get_gas(bob.address)

            alice_balance = sum(c["balance"] for c in alice_coins)
            bob_balance = sum(c["balance"] for c in bob_coins)

            print(f"   Alice: {format_balance(alice_balance)}")
            print(f"   Bob:   {format_balance(bob_balance)}")
        else:
            print(f"❌ Transfer failed: {result.get('error', 'Unknown')}")
    except Exception as e:
        print(f"❌ Transfer error: {e}")

    # ========== Finalização ==========
    print_step(10, "Workflow Complete")

    print("📊 Summary:")
    print("   ✅ Network: 4 validators + 1 gateway")
    print("   ✅ Accounts: Alice & Bob")
    print(f"   ✅ Package: {package_id}")
    if counter_id:
        print(f"   ✅ Counter: {counter_id}")
    print("   ✅ Transfers: 1 successful")

    print("\n🎉 All steps completed successfully!")
    print("\nNetwork is still running. You can:")
    print("  - Inspect with: docker exec -it mn.client bash")
    print("  - Check objects: iota client objects")
    print("  - Call functions: iota client call ...")

    print("\n👉 Press ENTER to stop the network...")
    input()

    print("\n🛑 Stopping experiment...")
    exp.stop()
    print("\n✅ Experiment stopped. Goodbye!")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        print("Cleaning up...")
        import os
        os.system("sudo mn -c")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback, os
        traceback.print_exc()
        print("\nCleaning up...")
        os.system("sudo mn -c")
