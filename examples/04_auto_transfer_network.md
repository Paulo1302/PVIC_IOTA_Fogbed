# 🚀 Example 4: IOTA Network with Automatic Transfers

A complete example demonstrating:
1. **Boot an IOTA network** with validators and gateway
2. **Generate accounts** automatically without manual intervention
3. **Execute transfers** between accounts programmatically
4. **Query balances** and transaction history

## 📋 Prerequisites

- ✅ Fogbed installed: `pip3 install fogbed`
- ✅ Repository cloned: `git clone <repo>`
- ✅ Dependencies installed: `pip install -e .`
- ✅ Docker IOTA image: `docker build -f docker/Dockerfile.local -t iota-dev:latest .`
- ✅ Sudo permissions for Mininet/Fogbed

## 🚀 How to Use

### Option 1: Automatic Execution (Recommended)

```bash
# Navigate to repository
cd /home/paulo/Documentos/PVIC_IOTA_Fogbed

# ⚠️ IMPORTANTE: Verifique containers antes de remover!
# Liste primeiro para ver o que será removido:
docker ps -a --filter "name=mn."

# OPÇÃO SEGURA: Remova containers específicos por ID
docker rm -f <container_id_específico>

# OPÇÃO ARRISCADA: Remove TODOS containers Mininet/Fogbed
# Use APENAS se não houver outros projetos Fogbed rodando!
sudo mn -c
docker rm -f $(docker ps -aq --filter "name=mn.")

# Run example with proper permissions
sudo PYTHONPATH="$(pwd)" /opt/fogbed/venv/bin/python3 examples/04_auto_transfer_network.py
```

### Option 2: Direct Python (if using local venv)

```bash
# With local venv
python3 examples/04_auto_transfer_network.py
```

## 📊 Expected Output

```
============================================================
🚀 IOTA NETWORK WITH AUTOMATIC TRANSFERS
============================================================

🧹 Removing previous runs...
✅ Cleanup completed

📦 Creating Fogbed infrastructure...

  ☁️  Creating 'cloud' datacenter...
  🌐 Creating IOTA network...

🔗 Adding nodes to network...

  📦 Validators:
     ✅ validator1 (10.0.0.11)
     ✅ validator2 (10.0.0.12)
     ✅ validator3 (10.0.0.13)
     ✅ validator4 (10.0.0.14)

  📦 Gateway:
     ✅ gateway (10.0.0.100:9000)

  📦 CLI Client:
     ✅ client (10.0.0.200)

▶️  Starting Fogbed network...
   ✅ Fogbed network started

⚙️  Configuring IOTA nodes...
   (generating genesis, patching configs, starting processes)...
   ✅ IOTA nodes started

⏳ Waiting for network to become operational...
✅ Network ready! (15s)

👥 Generating test accounts...

  ✅ Alice:   0x1234567890abcdef...
  ✅ Bob:     0xfedcba0987654321...
  ✅ Charlie: 0xabcdef1234567890...

============================================================
🔄 DEMONSTRATION: Chained Transfers
============================================================

1️⃣  Alice → Bob
💸 Transferring 100000 MIST...
  ✅ Transfer successful!
     Digest: 1a2b3c4d5e6f...
     Gas used: 1234 MIST

2️⃣  Bob → Charlie
💸 Transferring 50000 MIST...
  ✅ Transfer successful!

3️⃣  Charlie → Alice
💸 Transferring 25000 MIST...
  ✅ Transfer successful!

============================================================
📊 NETWORK SUMMARY
============================================================

🏛️  ARCHITECTURE:
  Validators:      4
  Gateway:         gateway (10.0.0.100)
  RPC Endpoint:    http://10.0.0.100:9000
  Metrics:         http://10.0.0.100:9184/metrics

👥 ACCOUNTS CREATED:
  1. ALICE    | 0x1234567890abcdef...
     Balance: 1000000000 MIST
  2. BOB      | 0xfedcba0987654321...
     Balance: 999900000 MIST
  3. CHARLIE  | 0xabcdef1234567890...
     Balance: 1000050000 MIST

⏸️  System operational. Press ENTER to shutdown...
```

## 🔧 What the Example Does

### 1. **Network Infrastructure**
```python
# Creates Fogbed experiment with virtual datacenter
exp = FogbedExperiment()
cloud = exp.add_virtual_instance("cloud")
iota_net = IotaNetwork(experiment=exp, image='iota-dev:latest')
```

### 2. **IOTA Topology**
```
┌─────────────────────────────────────────┐
│          Fogbed Network (10.0.0.x)      │
│                                          │
│  ┌──────────┐  ┌──────────┐            │
│  │validator1│  │validator2│  ...      │
│  │10.0.0.11 │  │10.0.0.12 │          │
│  └────┬─────┘  └────┬─────┘           │
│       │             │                   │
│       └─────────┬───┘                  │
│               ┌─▼──┐                   │
│               │ s1  │ (switch)         │
│               └─┬──┘                   │
│                 │                      │
│         ┌───────┼────────┐             │
│         │                │             │
│    ┌────▼────┐      ┌───▼────┐       │
│    │ gateway  │      │ client  │      │
│    │10.0.0.100│      │10.0.0.200│    │
│    │RPC:9000  │      │CLI tool │     │
│    └──────────┘      └─────────┘     │
│                                        │
└─────────────────────────────────────────┘
```

### 3. **Automatic Account Generation**
- Generates 3 accounts (Alice, Bob, Charlie) without manual faucet
- Automatically saves addresses
- Queries balance via RPC

### 4. **Programmatic Transfers**
Uses `TransactionBuilder` to create transfers:

```python
tx = TransactionBuilder(sender_address, gas_budget=10_000_000)
tx.transfer_iota([recipient_address], [amount])
result = tx.execute(client_container)
```

### 5. **Chained Transfers**
Demonstrates:
- Alice → Bob (100,000 MIST)
- Bob → Charlie (50,000 MIST)
- Charlie → Alice (25,000 MIST)

## 💡 Useful Commands During Execution

### Access CLI Client
```bash
docker exec -it mn.client bash
```

### View Available Addresses
```bash
docker exec -it mn.client iota client addresses
```

### Check Account Balance
```bash
docker exec -it mn.client iota client gas 0x<ADDRESS>
```

### View Account Transactions
```bash
docker exec -it mn.client iota client txs 0x<ADDRESS>
```

### View Gateway Logs
```bash
docker exec -it mn.gateway tail -f /app/iota.log
```

### Test RPC Directly
```bash
docker exec mn.client curl -X POST http://10.0.0.100:9000 \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"iota_getChainIdentifier","params":[],"id":1}'
```

### View Prometheus Metrics
```bash
docker exec mn.gateway curl http://127.0.0.1:9184/metrics
```

## 🔍 Code Structure

```
04_auto_transfer_network.py
├── cleanup_previous_runs()           # Remove old containers
├── wait_for_network_ready()          # Wait for RPC to be accessible
├── create_test_accounts()            # Generate 3 test accounts
├── fund_account_via_genesis()        # Fund from genesis (placeholder)
├── check_account_balance()           # Query balance via RPC
├── execute_transfer()                # Execute a transfer
├── demo_multiple_transfers()         # Perform chained transfers
├── print_summary()                   # Print final summary
└── main()                            # Main orchestration
```

## 🎯 Use Cases

### 1. **Automated Network Testing**
```bash
# No manual intervention - network boots and executes transfers
sudo python3 examples/04_auto_transfer_network.py
```

### 2. **Continuous Integration (CI/CD)**
```bash
# Use in test pipeline
- name: Test IOTA Network
  run: |
    python3 examples/04_auto_transfer_network.py << EOF

    EOF
```

### 3. **Development and Debugging**
- Network remains running after transfers
- Connect via `docker exec` for additional tests
- Press ENTER to shutdown

### 4. **Smart Contract Prototyping**
- Extend `execute_transfer()` for Move calls
- Use `TransactionBuilder.move_call()` for contracts
- See example in `03_smart_contract_full_workflow.py`

## ⚙️ Customizable Configurations

### Change Number of Validators
```python
for i in range(1, 6):  # 5 validators instead of 4
    iota_net.add_validator(f'validator{i}', f'10.0.0.{10+i}')
```

### Change Number of Accounts
```python
# In create_test_accounts()
names = ["alice", "bob", "charlie", "dave", "eve"]
for name in names:
    account_mgr.generate_account(name)
```

### Modify Transfer Amounts
```python
# In demo_multiple_transfers()
execute_transfer(client, alice.address, bob.address, 500_000)  # 500k MIST
```

### Increase Gas Budget
```python
tx = TransactionBuilder(sender, gas_budget=50_000_000)  # 50M MIST
```

## 🐛 Troubleshooting

### Error: "Port already in use"
```bash
# ⚠️ SEGURANÇA: SEMPRE verifique antes de remover!
# 1. Liste os containers
docker ps -a --filter "name=mn."

# 2. Identifique quais são deste projeto

# 3. Remova containers específicos (RECOMENDADO)
docker rm -f <container_id_1> <container_id_2>

# 4. OU remova todos Mininet (apenas se todos forem deste projeto!)
sudo mn -c
docker rm -f $(docker ps -aq --filter "name=mn.")
```

### Error: "Docker image not found"
```bash
# Check if image exists
docker images | grep iota-dev

# If not, build it
cd /home/paulo/Documentos/PVIC_IOTA_Fogbed
docker build -f docker/Dockerfile.local -t iota-dev:latest .
```

### Error: "Permission denied"
```bash
# Run with sudo
sudo PYTHONPATH="$(pwd)" /opt/fogbed/venv/bin/python3 examples/04_auto_transfer_network.py
```

### Network takes long to become ready
```bash
# Increase timeout in code (line ~150)
if not wait_for_network_ready(gateway.ip_addr, gateway.rpc_port, max_retries=60):
```

### Transfer fails
1. Check logs: `docker exec -it mn.gateway tail -f /app/iota.log`
2. Verify accounts have balance: `docker exec mn.client iota client gas <ADDRESS>`
3. Increase sleep between transfers: `time.sleep(5)` instead of 2

## 📚 Next Steps

### Extend to Smart Contracts
See `03_smart_contract_full_workflow.py` for:
- Deploy Move packages
- Call custom functions
- Interact with on-chain objects

### Monitor the Network
- Use Prometheus for metrics
- Grafana for visualization
- Custom alerting

### Load Testing
- Multiple parallel transfers
- Throughput measurement
- Latency analysis

## 📝 Important Notes

1. **Genesis Funding**: Accounts are created but need balance via genesis
2. **Gas Budget**: 10M MIST is sufficient for simple transfers
3. **RPC Timeout**: Network takes 10-30s to become ready after initialization
4. **Automatic Cleanup**: Verify containers were removed: `docker ps -a | grep mn`

## 📖 References

- [IOTA Docs](https://docs.iota.org/)
- [Fogbed](https://github.com/fogbed/fogbed)
- [IOTA CLI Client](https://docs.iota.org/concepts/indexing/default)
- [TransactionBuilder](../fogbed_iota/client/transaction.py)

---

**Author**: Paulo
**Date**: 2026-03-23
**Version**: 1.0
