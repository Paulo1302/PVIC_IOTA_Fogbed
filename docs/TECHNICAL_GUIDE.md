# 🔧 Technical Guide: IOTA Automatic Transfers

Complete technical reference for the automatic transfer system.

## 🏗️ Architecture Overview

### Network Layers

```
┌─────────────────────────────────────────────────────────┐
│                    Application Layer                     │
│  (TransactionBuilder, AccountManager, SimpleTransaction) │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│               RPC/Client Layer                           │
│        (IotaRpcClient, CLI Wrapper, Containers)         │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│              Network Layer (Fogbed/Mininet)             │
│   (IotaNetwork, IotaNode, Validators, Gateway)          │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│              Container Layer (Docker)                    │
│         (iota-node, iota CLI, Services)                 │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│               Host System (Linux/Docker)                │
└─────────────────────────────────────────────────────────┘
```

## 📊 Transaction Execution Flow

```
User Code
    ↓
TransactionBuilder.transfer_iota([recipient], [amount])
    ├─ Creates split_coins command
    ├─ Creates transfer_objects for each recipient
    └─ Stores commands list
    ↓
TransactionBuilder.build_cli_command()
    ├─ Converts each command to CLI format
    ├─ Adds --sender and --gas-budget
    └─ Returns full `iota client ptb ...` command
    ↓
client_container.cmd(cli_command)
    ├─ Executes via `docker exec mn.client`
    └─ Returns output string
    ↓
TransactionBuilder._parse_execution_result(output)
    ├─ Extracts digest
    ├─ Checks status (Success/Failure)
    ├─ Parses gas used
    └─ Returns structured result dict
    ↓
Returns: {
    'success': bool,
    'digest': str,
    'gas_used': int,
    'error': str (if failed)
}
```

## 🔐 Account Generation Process

### Account Lifecycle

```
1. AccountManager.generate_account(alias)
   ↓
2. docker exec mn.client iota keytool generate ed25519
   ↓
3. Parse output:
   - Extract: 0x<64-hex-chars> (address)
   - Extract: Base64 string (public key)
   ↓
4. Store in memory:
   accounts["alice"] = IotaAccount(...)
   ↓
5. Optional: Export keystore for backup
```

### Account Data Model

```python
@dataclass
class IotaAccount:
    address: str           # 0x<64-hex> - unique identifier
    alias: str            # "alice" - friendly name
    key_scheme: str       # "ed25519" (or secp256k1/secp256r1)
    public_key: str       # Base64 encoded public key
    _balance: int         # Cached balance in MIST
```

## 💰 Transfer Mechanism

### Simple Transfer Process

```
Input:
  sender: 0x123...
  recipient: 0xabc...
  amount: 100,000 MIST

Process:
1. Split gas coin into one output of 100,000 MIST
2. Transfer that output to recipient
3. Remaining gas for fees

Commands Generated:
  iota client ptb \
    --split-coins gas '[100000]' \
    --transfer-objects '[result:0]' 0xabc... \
    --sender 0x123... \
    --gas-budget 10000000

Result:
  Transaction Digest: 1a2b3c4d5e6f...
  Gas Used: 1,234 MIST (from budget of 10,000,000)
  Status: Success
```

### Multi-Transfer Process

```
Input:
  sender: 0x123...
  recipients: [0xabc..., 0xdef...]
  amounts: [100,000, 50,000]

Process:
1. Split gas coin into TWO outputs:
   - 100,000 MIST
   - 50,000 MIST

2. Transfer first output to first recipient
3. Transfer second output to second recipient

Commands Generated:
  iota client ptb \
    --split-coins gas '[100000, 50000]' \
    --transfer-objects '[result:0]' 0xabc... \
    --transfer-objects '[result:1]' 0xdef... \
    --sender 0x123... \
    --gas-budget 10000000
```

## 🔌 RPC Endpoint Communication

### Direct RPC vs CLI Wrapper

**Direct RPC (IotaRpcClient):**
```python
client = IotaRpcClient("http://10.0.0.100:9000")
balance = client.get_balance("0x123...", "0x2::iota::IOTA")
```

**CLI Wrapper (via docker exec):**
```python
result = client_container.cmd("iota client gas 0x123...")
```

### RPC Methods Used

| Method | Purpose | Example |
|--------|---------|---------|
| `iota_getChainIdentifier` | Health check | Network ready? |
| `iotax_getBalance` | Query balance | Account funds |
| `iota_getLatestCheckpointSequenceNumber` | Chain height | Latest block |
| `iota_getObject` | Fetch object | Query coin |
| `iota_getTransactionBlock` | Tx details | Confirm tx |
| `iota_getEvents` | Query events | Track events |

## ⚙️ Gas Model

### Gas Budget Structure

```
Gas Budget = 10,000,000 MIST
             ├─ Computation: ~1,000,000 MIST
             ├─ Storage: ~500,000 MIST
             └─ Reserve: ~8,500,000 MIST (safety margin)
```

### Calculating Gas for Transfers

```
Base PTB Command: ~1,000 MIST
Per Split: ~200 MIST
Per Transfer: ~300 MIST

Example 2 transfers:
  = 1,000 (base)
  + 200 (1 split coin)
  + 600 (2 transfers)
  = 1,800 MIST (typical)
```

### Gas Limits and Failures

```
Scenario 1: Gas too low
  Budget: 1,000 MIST
  Needed: 1,800 MIST
  Result: FAILURE - "GasPriceHigherThanMax"
  Solution: Increase --gas-budget

Scenario 2: Insufficient funds
  Sender balance: 500,000 MIST
  Transfer: 600,000 MIST
  Result: FAILURE - "InsufficientGasFunds"
  Solution: Fund account or reduce amount

Scenario 3: Gas ok, amounts ok
  Budget: 10,000,000 MIST
  Amount: 100,000 MIST
  Result: SUCCESS + Gas Refund
```

## 🌐 Network Initialization Sequence

### Boot Sequence Timeline

```
T+0s:   Create Fogbed experiment
T+2s:   Add nodes and links
T+5s:   exp.start() → Mininet creates namespaces
T+10s:  IOTA node processes start in containers
T+15s:  Genesis consensus reached
T+20s:  RPC endpoint responsive
T+30s:  Ready for transactions

wait_for_network_ready() implementation:
  Loop until T+30s:
    GET http://10.0.0.100:9000 (RPC health check)
    If success: READY
    Else: sleep(1) and retry
```

### Genesis Generation

```
Step 1: Generate initial genesis
  - Used internally for node bootstrap
  - Creates authority keys
  - Establishes validator set

Step 2: Patch with real IPs
  - network.yaml updated with actual IPs
  - Each validator: 10.0.0.X
  - P2P ports: 2001, 2011, 2021, 2031

Step 3: Regenerate genesis.blob
  - Commits real topology to consensus
  - Nodes use this to connect peers
  - Result: Blockchain genesis block

Step 4: Start validators
  - Each validates using genesis.blob
  - P2P connections established
  - First checkpoints produced
```

## 📝 CLI Command Examples

### Account Management

```bash
# Generate keypair
iota keytool generate ed25519

# List addresses
iota client addresses

# Get balance (gas coins only)
iota client gas 0x<ADDRESS>

# Get all coins
iota client objects 0x<ADDRESS>

# Export active address
iota client active-address
```

### Transactions (PTB)

```bash
# Simple transfer
iota client ptb \
  --transfer-objects '[0xOBJ_ID]' 0xRECIPIENT \
  --sender 0xSENDER \
  --gas-budget 10000000

# Split and transfer
iota client ptb \
  --split-coins gas '[100000, 50000]' \
  --transfer-objects '[result:0]' 0xRECIPIENT1 \
  --transfer-objects '[result:1]' 0xRECIPIENT2 \
  --sender 0xSENDER \
  --gas-budget 10000000

# Merge coins
iota client ptb \
  --merge-coins 0xCOIN1 '[0xCOIN2, 0xCOIN3]' \
  --sender 0xSENDER \
  --gas-budget 10000000

# Call Move function
iota client ptb \
  --move-call 0x2::counter::increment 0xCOUNTER_ID \
  --sender 0xSENDER \
  --gas-budget 10000000

# Dry run (no commit)
iota client ptb ... --dry-run
```

### RPC Queries

```bash
# Check RPC health
curl -X POST http://10.0.0.100:9000 \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"iota_getChainIdentifier","params":[],"id":1}'

# Get balance
curl -X POST http://10.0.0.100:9000 \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"iotax_getBalance","params":["0x...","0x2::iota::IOTA"],"id":1}'

# Get coins
curl -X POST http://10.0.0.100:9000 \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"iotax_getCoins","params":["0x...","0x2::iota::IOTA"],"id":1}'
```

## 🔍 Debugging Transfers

### Step 1: Verify Account Exists

```bash
docker exec mn.client iota client addresses
# Should list all generated addresses
```

### Step 2: Check Gas Balance

```bash
docker exec mn.client iota client gas 0x<ADDRESS>
# Should show available coins
```

### Step 3: Test RPC Endpoint

```bash
docker exec mn.client curl -X POST http://10.0.0.100:9000 \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"iotax_getBalance","params":["0x<ADDRESS>","0x2::iota::IOTA"],"id":1}'
```

### Step 4: Dry Run Transfer

```bash
docker exec mn.client iota client ptb \
  --transfer-objects '[0xCOIN_ID]' 0xRECIPIENT \
  --sender 0xSENDER \
  --gas-budget 10000000 \
  --dry-run
```

### Step 5: Check Logs

```bash
# Validator logs
docker exec mn.validator1 tail -f /app/iota.log

# Gateway logs
docker exec mn.gateway tail -f /app/iota.log

# Client errors
docker exec mn.client bash -c 'tail -f /tmp/*.log'
```

## 🚀 Performance Optimization

### Batch Transfers

```python
# Slow: One transfer at a time
for recipient in recipients:
    execute_transfer(client, sender, recipient, 100_000)
    time.sleep(2)  # Waiting for finality

# Fast: Batch in one PTB
tx = TransactionBuilder(sender)
for recipient in recipients:
    tx.transfer_iota([recipient], [100_000])
tx.execute(client)  # One transaction!
```

### Connection Pooling

```python
# Slow: New HTTP connection each time
client1 = IotaRpcClient("http://10.0.0.100:9000")
client2 = IotaRpcClient("http://10.0.0.100:9000")

# Fast: Reuse connection
rpc = IotaRpcClient("http://10.0.0.100:9000")
balance1 = rpc.get_balance("0x...")
balance2 = rpc.get_balance("0x...")
```

### Parallel Execution

```python
# Using ThreadPoolExecutor for concurrent transfers
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(max_workers=4) as executor:
    futures = []
    for i, (sender, recipient) in enumerate(transfer_pairs):
        future = executor.submit(execute_transfer, client, sender, recipient, 100_000)
        futures.append(future)

    results = [f.result() for f in futures]
```

## 📊 Monitoring and Metrics

### Key Metrics to Track

```python
metrics = {
    'tx_count': 0,           # Total transactions
    'tx_success': 0,         # Successful transactions
    'tx_failed': 0,          # Failed transactions
    'avg_gas_used': 0,       # Average gas consumption
    'total_mist_moved': 0,   # Total MIST transferred
    'avg_latency': 0,        # Average time to finality
    'network_ready_time': 0, # Time to RPC ready
}
```

### Prometheus Metrics

```bash
# Query from gateway metrics endpoint
curl http://10.0.0.100:9184/metrics | grep iota

# Common metrics:
# iota_transactions_total
# iota_transaction_latency
# iota_block_height
# iota_validators_count
# iota_consensus_latency
```

## 🛡️ Error Handling

### Common Error Codes

| Error | Cause | Solution |
|-------|-------|----------|
| `InsufficientGasFunds` | Not enough gas | Increase gas budget |
| `GasPriceHigherThanMax` | Gas too expensive | Use higher budget |
| `InvalidSignature` | Auth failed | Check sender account |
| `ObjectNotFound` | Coin doesn't exist | Verify coin ID |
| `TransactionNotFound` | TX not finalized | Wait and retry |
| `RpcError` | Network issue | Check RPC endpoint |

### Retry Logic

```python
def execute_with_retry(tx, client, max_retries=3):
    for attempt in range(max_retries):
        try:
            result = tx.execute(client)
            if result['success']:
                return result
            elif 'TransactionNotFound' in result.get('error', ''):
                time.sleep(2 ** attempt)  # Exponential backoff
                continue
            else:
                return result
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)
```

## 📚 Related Files

| File | Purpose |
|------|---------|
| `fogbed_iota/client/transaction.py` | TransactionBuilder implementation |
| `fogbed_iota/accounts.py` | AccountManager implementation |
| `fogbed_iota/client/rpc_client.py` | RPC client implementation |
| `fogbed_iota/network.py` | IotaNetwork orchestration |
| `fogbed_iota/crypto/keypair.py` | Cryptographic utilities |

## 🔗 References

- [IOTA Programmable Transactions](https://docs.iota.org/concepts/transactions/ptb)
- [IOTA Gas Mechanism](https://docs.iota.org/concepts/transactions/gas-in-iota)
- [IOTA CLI Documentation](https://docs.iota.org/guides/developer/getting-started/using-iota-cli)
- [Fogbed Documentation](https://fogbed.readthedocs.io/)

---

**Version**: 1.0
**Last Updated**: 2026-03-23
