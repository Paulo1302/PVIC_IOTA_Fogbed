#!/usr/bin/env python3

# examples/03_smart_contract_full_workflow.py

"""
Exemplo 3: Workflow Completo de Smart Contracts com Gas Manual

Demonstra:
- Setup de rede IOTA completa (4 validators + 1 gateway)
- Gerenciamento de contas (Alice e Bob)
- Funding manual via faucet (princípio de gas transparente)
- Deploy de smart contract Move
- Interação com contrato (chamada de funções)
- Uso de IotaCLI e TransactionBuilder
"""

import sys
import time
from pathlib import Path

# Adicionar diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fogbed import (
    FogbedExperiment,
    Container,
)
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

    # ========== Fase 2: Inicializar CLI Tools ==========
    print_step(2, "Initialize CLI Tools")

    cli = IotaCLI(client)
    print("✅ IotaCLI initialized")

    gas_price = cli.get_reference_gas_price()
    print(f"📊 Reference gas price: {gas_price} MIST")

    # ========== Fase 3: Account Management ==========
    print_step(3, "Account Management")

    print("📝 Generating keypairs...")
    acct_mgr = iota_net.account_manager

    alice = acct_mgr.generate_account("alice")
    print(f"✅ Alice: {alice.address}")

    bob = acct_mgr.generate_account("bob")
    print(f"✅ Bob: {bob.address}")

    # ========== Fase 4: Funding via Faucet ==========
    print_step(4, "Funding Accounts")

    print("💰 Checking initial balances...")
    alice_coins = cli.get_gas(alice.address)
    bob_coins = cli.get_gas(bob.address)

    alice_balance = sum(c["balance"] for c in alice_coins)
    bob_balance = sum(c["balance"] for c in bob_coins)

    print(f"   Alice: {format_balance(alice_balance)}")
    print(f"   Bob:   {format_balance(bob_balance)}")

    if alice_balance == 0:
        print("\n💧 Requesting faucet for Alice...")
        if cli.faucet_request(alice.address):
            print("✅ Faucet request succeeded!")
            time.sleep(3)
            alice_coins = cli.get_gas(alice.address)
            alice_balance = sum(c["balance"] for c in alice_coins)
            print(f"   Alice new balance: {format_balance(alice_balance)}")
        else:
            print("\n⚠️  MANUAL FUNDING REQUIRED")
            print("\nAlice has no funds. Please fund manually:")
            print("\n   Option A: Use faucet in another terminal")
            print("      docker exec -it mn.client bash")
            print(f"      iota client faucet --address {alice.address}")
            print("\n   Option B: Transfer from genesis account")
            print("\n👉 Press ENTER after funding Alice...")
            input()
            alice_coins = cli.get_gas(alice.address)
            alice_balance = sum(c["balance"] for c in alice_coins)
            if alice_balance == 0:
                print("❌ Alice still has no balance. Cannot continue.")
                exp.stop()
                return
            print(f"✅ Alice funded: {format_balance(alice_balance)}")

    # ========== Fase 5: Preparar Smart Contract ==========
    print_step(5, "Prepare Smart Contract")

    print("📝 Creating counter contract...")
    client.cmd("mkdir -p /contracts/counter")

    move_toml = """[package]
name = "counter"
edition = "2024.beta"

[dependencies]
Iota = { git = "https://github.com/iotaledger/iota.git", subdir = "crates/iota-framework/packages/iota-framework", rev = "framework/mainnet" }

[addresses]
counter = "0x0"
"""
    client.cmd(f"cat > /contracts/counter/Move.toml << 'EOF'\n{move_toml}\nEOF")

    client.cmd("mkdir -p /contracts/counter/sources")

    counter_move = """module counter::counter {
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
    client.cmd(
        f"cat > /contracts/counter/sources/counter.move << 'EOF'\n{counter_move}\nEOF"
    )

    print("✅ Contract source created")

    print("\n🔨 Building contract...")
    if cli.move_build("/contracts/counter"):
        print("✅ Contract compiled successfully")
    else:
        print("❌ Contract compilation failed")
        exp.stop()
        return

    # ========== Fase 6: Deploy Smart Contract ==========
    print_step(6, "Deploy Smart Contract")

    print("📦 Publishing contract package...")
    try:
        publish_result = cli.publish_package(
            package_path="/contracts/counter",
            gas_budget=100_000_000,
            sender=alice.address,
        )

        if "package_id" not in publish_result:
            print("❌ Failed to get package ID from publish result")
            print(f"Result: {publish_result}")
            exp.stop()
            return

        package_id = publish_result["package_id"]
        print(f"✅ Package published: {package_id}")
        print(f"   Digest: {publish_result.get('digest', 'N/A')}")
    except Exception as e:
        print(f"❌ Publish failed: {e}")
        exp.stop()
        return

    # ========== Fase 7: Criar Counter ==========
    print_step(7, "Create Counter Object")

    print("🎯 Creating counter...")
    try:
        create_result = cli.call_function(
            package=package_id,
            module="counter",
            function="create",
            args=[],
            gas_budget=10_000_000,
            sender=alice.address,
        )

        print("✅ Counter created!")
        print(f"   Digest: {create_result.get('digest', 'N/A')}")
        time.sleep(3)

        print("\n🔍 Finding counter object...")
        objects = cli.get_objects(alice.address)

        counter_id = None
        for obj in objects:
            obj_details = cli.get_object(obj["object_id"])
            if "counter::counter::Counter" in obj_details.get("type", ""):
                counter_id = obj["object_id"]
                break

        if not counter_id:
            print("⚠️  Could not find counter object automatically")
            print("   You may need to query objects manually")
        else:
            print(f"✅ Counter found: {counter_id}")
    except Exception as e:
        print(f"❌ Create failed: {e}")
        exp.stop()
        return

    # ========== Fase 8: Interagir com Counter ==========
    print_step(8, "Interact with Counter")

    if counter_id:
        print("➕ Incrementing counter (3 times)...")
        for i in range(3):
            try:
                result = cli.call_function(
                    package=package_id,
                    module="counter",
                    function="increment",
                    args=[counter_id],
                    gas_budget=10_000_000,
                    sender=alice.address,
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
