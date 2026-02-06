#!/usr/bin/env python3
# examples/03_smart_contract_full_workflow.py

"""
Exemplo completo: Smart Contract Move com gas manual
Demonstra todo o ciclo de vida de um contrato
"""
import sys
import os
import time
import subprocess

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fogbed import FogbedExperiment, Container
from mininet.log import setLogLevel, info
from fogbed_iota import IotaNetwork

def cleanup_previous_run():
    """Limpa containers e redes de execuções anteriores"""
    print("🧹 Cleaning up previous run...")
    
    # Parar containers mn.*
    subprocess.run(
        "docker ps -a | grep 'mn\\.' | awk '{print $1}' | xargs -r docker rm -f",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    # Limpar Mininet
    subprocess.run(
        ["mn", "-c"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    print("✅ Cleanup complete\n")

def main():
    # Limpar antes de começar
    cleanup_previous_run()
    
    setLogLevel("info")
    
    print("=" * 70)
    print("IOTA Smart Contract Workflow - Gas Manual")
    print("=" * 70)
    
    exp = FogbedExperiment()
    
    # Criar rede IOTA
    iota_net = IotaNetwork(exp, image="iota-dev:latest")
    
    # Topologia: 4 validators + 1 gateway
    for i in range(1, 5):
        iota_net.add_validator(f"validator{i}", f"10.0.0.{i}")
    
    iota_net.add_gateway("gateway", "10.0.0.100")
    
    # Cliente com ferramentas Move
    client = Container(
        name="client",
        dimage="iota-dev:latest",
        ip="10.0.0.200",
        privileged=True
    )
    iota_net.set_client(client)
    
    iota_net.attach_to_experiment("cloud")
    
    # Iniciar
    print("\n🚀 Starting Fogbed network...")
    exp.start()
    
    print("\n🚀 Starting IOTA network...")
    iota_net.start()
    
    print("\n⏳ Waiting for network stabilization (20s)...")
    time.sleep(20)
    
    # ========================================
    # PARTE 1: Gerenciamento de Contas
    # ========================================
    
    print("\n" + "="*70)
    print("STEP 1: Account Management")
    print("="*70)
    
    acct_mgr = iota_net.account_manager
    
    # Gerar contas
    print("\n📝 Generating keypairs...")
    alice = acct_mgr.generate_account("alice")
    bob = acct_mgr.generate_account("bob")
    
    print(f"\n✅ Alice: {alice.address}")
    print(f"✅ Bob: {bob.address}")
    
    # Verificar saldos (devem estar zerados)
    print("\n💰 Checking balances...")
    alice_balance = acct_mgr.get_balance("alice")
    bob_balance = acct_mgr.get_balance("bob")
    
    print(f"   Alice: {alice_balance} MIST (empty)")
    print(f"   Bob: {bob_balance} MIST (empty)")
    
    # ========================================
    # PARTE 2: Funding Manual (Faucet)
    # ========================================
    
    print("\n" + "="*70)
    print("STEP 2: Manual Funding via Faucet")
    print("="*70)
    
    print("\n⚠️  MANUAL STEP REQUIRED:")
    print("   Alice and Bob have no gas. You need to fund them manually.")
    print("")
    print("   Option A: Use IOTA faucet (if available in genesis)")
    print(f"     iota client call --package 0x2 --module faucet \\")
    print(f"       --function request --args {alice.address} \\")
    print(f"       --gas-budget 10000000")
    print("")
    print("   Option B: Transfer from a genesis treasury account")
    print("     (if you configured one in genesis)")
    print("")
    
    input("👉 Press ENTER after funding Alice's account...")
    
    # Verificar saldo novamente
    alice_balance_after = acct_mgr.get_balance("alice")
    print(f"\n💰 Alice balance after funding: {alice_balance_after} MIST")
    
    if alice_balance_after == 0:
        print("\n⚠️  WARNING: Alice still has no balance!")
        print("   Smart contract operations will fail.")
        print("   Make sure to fund the account before proceeding.")
    
    # ========================================
    # PARTE 3: Deploy de Smart Contract
    # ========================================
    
    print("\n" + "="*70)
    print("STEP 3: Smart Contract Deployment")
    print("="*70)
    
    contract_mgr = iota_net.contract_manager
    
    # Assumindo que você tem um contrato em ./contracts/my_counter
    local_contract_path = "./contracts/my_counter"
    
    if not os.path.exists(local_contract_path):
        print(f"\n⚠️  Contract not found at {local_contract_path}")
        print("   Creating example counter contract...")
        create_example_counter_contract(local_contract_path)
    
    # Copiar para container
    print(f"\n📦 Copying contract to container...")
    container_path = contract_mgr.copy_package_to_container(
        local_contract_path, 
        "my_counter"
    )
    
    # Build
    print(f"\n🔨 Building Move package...")
    build_result = contract_mgr.build_package(container_path)
    print(f"   Modules: {', '.join(build_result['modules'])}")
    
    # Publish (requer gas de Alice)
    print(f"\n🚀 Publishing package (using Alice's gas)...")
    
    try:
        package = contract_mgr.publish_package(
            package_path=container_path,
            sender_alias="alice",
            gas_budget=100_000_000
        )
        
        print(f"\n✅ Package deployed successfully!")
        print(f"   Package ID: {package.package_id}")
        print(f"   Transaction: {package.digest}")
        print(f"   Publisher: {package.publisher}")
        
    except RuntimeError as e:
        print(f"\n❌ Publish failed: {e}")
        print("\n   This is expected if Alice has no balance.")
        print("   Please fund Alice and try again.")
        return
    
    # ========================================
    # PARTE 4: Chamada de Função
    # ========================================
    
    print("\n" + "="*70)
    print("STEP 4: Contract Interaction")
    print("="*70)
    
    print(f"\n🔄 Calling increment function...")
    
    try:
        tx_result = contract_mgr.call_function(
            package_id=package.package_id,
            module="counter",
            function="increment",
            sender_alias="alice",
            args=[],
            gas_budget=10_000_000
        )
        
        print(f"\n✅ Function executed!")
        print(f"   Transaction: {tx_result.get('digest', 'N/A')}")
        
        # Buscar objeto Counter criado
        created_objects = [
            obj for obj in tx_result.get('objectChanges', [])
            if obj.get('type') == 'created'
        ]
        
        if created_objects:
            counter_id = created_objects[0]['objectId']
            print(f"   Counter Object: {counter_id}")
            
            # Query do objeto
            print(f"\n📊 Fetching counter object...")
            counter_obj = contract_mgr.get_object(counter_id)
            
            value = counter_obj.get('data', {}).get('content', {}).get('fields', {}).get('value', 'N/A')
            print(f"   Counter value: {value}")
        
    except RuntimeError as e:
        print(f"\n❌ Function call failed: {e}")
    
    # ========================================
    # Fim
    # ========================================
    
    print("\n" + "="*70)
    print("Workflow Complete!")
    print("="*70)
    print("\nNetwork is still running. You can:")
    print("  - Call more functions via contract_mgr.call_function()")
    print("  - Create more accounts via account_mgr.generate_account()")
    print("  - Deploy more contracts")
    print("")
    
    input("Press ENTER to stop the network...")
    exp.stop()


def create_example_counter_contract(path: str):
    """Cria um contrato counter de exemplo"""
    os.makedirs(path, exist_ok=True)
    
    # Move.toml
    with open(f"{path}/Move.toml", "w") as f:
        f.write("""[package]
name = "my_counter"
version = "0.0.1"
edition = "2024"

[dependencies]
Iota = { git = "https://github.com/iotaledger/iota.git", subdir = "crates/iota-framework/packages/iota-framework", rev = "framework/mainnet" }

[addresses]
my_counter = "0x0"
""")
    
    # sources/counter.move
    os.makedirs(f"{path}/sources", exist_ok=True)
    with open(f"{path}/sources/counter.move", "w") as f:
        f.write("""module my_counter::counter {
    use iota::object::{Self, UID};
    use iota::transfer;
    use iota::tx_context::{Self, TxContext};

    public struct Counter has key {
        id: UID,
        value: u64,
    }

    public entry fun increment(ctx: &mut TxContext) {
        let counter = Counter {
            id: object::new(ctx),
            value: 1,
        };
        transfer::transfer(counter, tx_context::sender(ctx));
    }

    public entry fun increment_existing(counter: &mut Counter) {
        counter.value = counter.value + 1;
    }

    public fun get_value(counter: &Counter): u64 {
        counter.value
    }
}
""")
    
    print(f"✅ Example counter contract created at {path}")


if __name__ == "__main__":
    main()
