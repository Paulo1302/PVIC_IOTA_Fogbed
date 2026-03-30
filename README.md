# fogbed-iota

🚀 **IOTA blockchain integration for Fogbed network emulator**

Emulate complete IOTA blockchain networks with multiple validators and fullnodes using containerized infrastructure managed by Fogbed/Mininet.

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-20.10+-blue.svg)](https://www.docker.com/)
[![IOTA](https://img.shields.io/badge/IOTA-v1.15.0-blue.svg)](https://github.com/iotaledger/iota)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## ✨ Features

- ✅ **Auto-extraction of IOTA binaries** from Docker image (no manual installation required)
- ✅ **Automatic genesis generation** for custom validator networks
- ✅ **Pythonic API** for network configuration and orchestration
- ✅ **Support for validators and fullnodes** (gateway with RPC)
- ✅ **Pre-configured IOTA CLI client** for testing
- ✅ **Network topology customization** with configurable latency and bandwidth
- ✅ **Production-ready** - portable across any machine with Docker
- ✅ **Zero Rust compilation** - uses pre-built Docker images

## 📋 Requirements

- **Ubuntu 20.04+** (or Debian 11+)
- **Docker 20.10+**
- **Python 3.8+**
- **4GB+ RAM** (recommended)
- **sudo privileges** (required for Mininet/Fogbed)
- **[Fogbed](https://github.com/fogbed/fogbed)** — fog/edge network emulator (includes Containernet/Mininet)

> **Note:** Containernet is provided by Fogbed and does **not** need to be installed separately.

## 🚀 Quick Start

> **⚠️ SECURITY WARNING**: This project includes a safe cleanup script.
> Use `./scripts/safe_cleanup.sh` which asks for confirmation before removing containers.
> NEVER run bulk removal commands without verifying the containers first!

### 1. Clone the repository

```bash
git clone https://github.com/your-username/fogbed-iota.git
cd fogbed-iota
```

### 2. Install Fogbed

```bash
pip3 install fogbed
# OR install from source for latest version:
# git clone https://github.com/fogbed/fogbed.git && cd fogbed && pip install -e .
```

### 3. Install this package

```bash
pip install -e .
```

### 4. Download IOTA v1.15.0 binaries and build the Docker image

```bash
# Download IOTA v1.15.0 release
curl -L -o /tmp/iota.tgz \
  "https://github.com/iotaledger/iota/releases/download/v1.15.0/iota-v1.15.0-linux-x86_64.tgz"
tar -xzf /tmp/iota.tgz -C /tmp/

# Copy binaries to docker/bins/ for the local build
mkdir -p docker/bins
cp /tmp/iota-v1.15.0-linux-x86_64/iota        docker/bins/iota
cp /tmp/iota-v1.15.0-linux-x86_64/iota-node   docker/bins/iota-node
chmod +x docker/bins/*

# Build Docker image from local binaries (no internet required inside build)
docker build -f docker/Dockerfile.local -t iota-dev:latest .
```

### 5. Run the example

```bash
# ⚠️ IMPORTANTE: Verifique containers antes de remover!
# Liste containers Mininet/Fogbed primeiro:
docker ps -a --filter "name=mn."

# Se você tem OUTROS PROJETOS usando Mininet/Fogbed, remova APENAS
# os containers específicos deste projeto usando o ID do container:
# docker rm -f <container_id_específico>

# APENAS se todos os containers listados forem deste projeto:
sudo mn -c
docker rm -f $(docker ps -aq --filter "name=mn.") 2>/dev/null

sudo PYTHONPATH="$(pwd)" \
  /opt/fogbed/venv/bin/python3 examples/02_complete_network.py
```

That's it! 🎉 The system will automatically:
- Generate a two-step genesis with real validator IPs embedded
- Deploy 4 validators + 1 gateway + 1 client via Fogbed/Mininet
- Start all IOTA nodes over a virtual network (10.0.0.x)
- Expose RPC at `http://10.0.0.100:9000` (accessible via `docker exec mn.gateway`)

## 📚 Usage Examples

### Basic Network (4 Validators + Gateway)

```python
#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fogbed import FogbedExperiment, Container
from fogbed_iota import IotaNetwork

exp = FogbedExperiment()

# Create IOTA network
iota_net = IotaNetwork(exp, image="iota-dev:latest")

# Add 4 validators
for i in range(1, 5):
    iota_net.add_validator(f"validator{i}", f"10.0.0.{i}")

# Add gateway (fullnode with RPC)
iota_net.add_gateway("gateway", "10.0.0.100")

# Add CLI client
client = Container(
    name="client",
    dimage="iota-dev:latest",
    ip="10.0.0.200",
    privileged=True
)
iota_net.set_client(client)

# Attach to experiment and create network topology
iota_net.attach_to_experiment(datacenter_name="cloud")

switch = exp.add_switch('s1')
for node in iota_net.nodes:
    exp.add_link(node, switch, delay='10ms', bw=100)
exp.add_link(client, switch, delay='5ms', bw=1000)

# Start Fogbed network
exp.start()

# Initialize IOTA nodes (genesis, configs, start processes)
iota_net.start()

print("✅ IOTA network is ready!")
print(f"Gateway RPC: http://10.0.0.100:9000")

input("Press ENTER to stop...")
exp.stop()
```

### Advanced: Custom Topology

```python
# Different network configurations
iota_net.add_validator("val1", "10.0.0.1")
iota_net.add_validator("val2", "10.0.0.2")
iota_net.add_gateway("gateway", "10.0.0.100")

# Custom network delays for edge/fog computing simulation
exp.add_link(val1, switch, delay='50ms', bw=10)  # Edge validator
exp.add_link(val2, switch, delay='5ms', bw=1000) # Cloud validator
```

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Host Machine                          │
│                                                          │
│  ┌────────────────────────────────────────────────┐    │
│  │           Fogbed/Mininet Network               │    │
│  │                                                 │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐    │    │
│  │  │validator1│  │validator2│  │validator3│    │    │
│  │  │10.0.0.1  │  │10.0.0.2  │  │10.0.0.3  │    │    │
│  │  └─────┬────┘  └─────┬────┘  └─────┬────┘    │    │
│  │        │             │             │          │    │
│  │        └─────────────┴─────────────┘          │    │
│  │                      │                         │    │
│  │               ┌──────▼───────┐                │    │
│  │               │   Switch s1  │                │    │
│  │               └──────┬───────┘                │    │
│  │                      │                         │    │
│  │        ┌─────────────┴─────────────┐          │    │
│  │        │                           │          │    │
│  │   ┌────▼────┐                 ┌───▼───┐      │    │
│  │   │ Gateway │                 │Client │      │    │
│  │   │10.0.0.100│                │10.0.0.200│   │    │
│  │   │RPC:9000 │                 │(CLI)  │      │    │
│  │   └─────────┘                 └───────┘      │    │
│  │                                                 │    │
│  └────────────────────────────────────────────────┘    │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

## 🔧 Configuration

### Environment Variables

```bash
export IOTA_DOCKER_IMAGE="iota-dev:latest"  # Docker image to use
export RUST_LOG="info,iota_node=debug"      # Logging level
```

### Network Parameters

```python
# Customize P2P ports (auto-assigned by default)
node = iota_net.add_validator("val1", "10.0.0.1")
print(f"P2P Port: {node.p2p_port}")  # 2001, 2011, 2021...

# Customize RPC port
gateway = iota_net.add_gateway("gw", "10.0.0.100")
print(f"RPC Port: {gateway.rpc_port}")  # 9000
```

## 🧪 Testing

### Verify Network is Running

```bash
# List containers
docker ps | grep mn.

# Check validator logs
docker exec -it mn.validator1 cat /app/iota.log

# Test connectivity
docker exec -it mn.validator1 ping -c 2 10.0.0.100

# Check RPC endpoint (wait ~30s after start)
curl http://10.0.0.100:9000

# View Prometheus metrics
curl http://10.0.0.100:9184/metrics
```

### Run Automated Tests

```bash
chmod +x scripts/test_network.sh
sudo ./scripts/test_network.sh
```

## 📊 Monitoring

### Logs

```bash
# Validator logs
docker exec -it mn.validator1 tail -f /app/iota.log

# Gateway logs
docker exec -it mn.gateway tail -f /app/iota.log
```

### Metrics (Prometheus format)

```bash
curl http://10.0.0.100:9184/metrics | grep iota_
```

### Using IOTA CLI

```bash
# Access client container
docker exec -it mn.client bash

# Check IOTA version
iota --version

# Query network (inside client container)
iota client gas
iota client addresses
```

## 🛠️ Troubleshooting

### Issue: Containers already exist

**⚠️ RECOMMENDED: Use the safe cleanup script**
```bash
./scripts/safe_cleanup.sh
```

This script will:
- List all Mininet containers
- Ask for confirmation before removing
- Prevent accidental deletion of containers from other projects

**Manual cleanup (use with caution):**
```bash
# ⚠️ SECURITY WARNING: Always verify BEFORE removing!
# 1. List containers first:
docker ps -a --filter "name=mn."

# 2. Verify they are from this project (IOTA/Fogbed)

# 3. SAFE OPTION - Remove specific containers by ID:
docker rm -f <container_id_1> <container_id_2>

# 4. RISKY OPTION - Removes ALL Mininet/Fogbed containers:
#    Use ONLY if you DON'T have other Mininet/Fogbed projects running!
sudo mn -c
docker rm -f $(docker ps -aq --filter "name=mn.")
```

### Issue: Binary not found in Docker image

The `docker/Dockerfile` downloads binaries during build and requires internet access.  
Use `Dockerfile.local` to build from pre-downloaded binaries in `docker/bins/`:

```bash
docker build -f docker/Dockerfile.local -t iota-dev:latest .
```

> **Note:** `docker/bins/` is in `.gitignore` — download binaries manually before building (see Quick Start step 4).

### Issue: P2P connection errors (`unsupported p2p multiaddr`)

IOTA v1.15.0 uses **UDP/QUIC** for P2P, not TCP. Ensure `external-address` in validator configs uses `/ip4/IP/udp/PORT`.

### Issue: Validators not reaching consensus (connecting to `127.0.0.1`)

The genesis must be generated with real validator IPs, not `127.0.0.1`. This project uses a two-step genesis:
1. Generate initial genesis → get `network.yaml`
2. Patch `network.yaml` with real IPs → re-run genesis → `genesis.blob` contains correct addresses

### Issue: `missing field 'db-path'` on validator startup

`network.yaml` (which lists all validators) was being passed as a single validator config. This is fixed — `network.yaml` is excluded from the validator template list.

### Issue: RPC not accessible from host

The emulated network (`10.0.0.x`) is only accessible **inside containers**. Use:

```bash
# Test RPC from inside the gateway container
docker exec mn.gateway curl -s -X POST http://127.0.0.1:9000 \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"iota_getTotalTransactionBlocks","params":[],"id":1}'

# Or from the client (via emulated network)
docker exec mn.client curl -s -X POST http://10.0.0.100:9000 \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"iota_getTotalTransactionBlocks","params":[],"id":1}'
```

### Issue: Nodes not synchronizing

Check logs with the correct path:

```bash
docker exec mn.validator1 tail -20 /var/log/iota/iota-node.log
docker exec mn.gateway   tail -20 /var/log/iota/iota-node.log
```

## 📁 Project Structure

```
fogbed-iota/
├── fogbed_iota/           # Main Python package
│   ├── __init__.py        # Package initialization
│   ├── __version__.py     # Version information
│   └── network.py         # Core IotaNetwork orchestrator
├── docker/                # Docker configurations
│   ├── Dockerfile         # Production image (downloads binaries, requires internet)
│   ├── Dockerfile.local   # Build from local binaries in docker/bins/ (offline)
│   └── bins/              # Pre-downloaded IOTA binaries (gitignored, copy manually)
├── examples/              # Usage examples
│   ├── 01_basic_network.py      # 4 validators + gateway
│   └── 02_complete_network.py   # Advanced example with client
├── scripts/               # Utility scripts
│   ├── build_docker.sh          # Build Docker images
│   ├── test_network.sh          # Automated tests
│   └── install_iota_host.sh     # Install binary to host
├── tests/                 # Unit and integration tests
├── docs/                  # Documentation
└── README.md
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 👤 Author

**Paulo**
- Email: paulogrcsilva@gmail.com
- GitHub: [@Paulo1302](https://github.com/Paulo1302)

## 🙏 Acknowledgments

- [IOTA Foundation](https://www.iota.org/) - For the IOTA protocol
- [Fogbed](https://github.com/fogbed/fogbed) - For the network emulation framework
- [Mininet](http://mininet.org/) - For the underlying network virtualization

## 📚 References

- [IOTA Documentation](https://docs.iota.org/)
- [Fogbed Documentation](https://fogbed.readthedocs.io/)
- [Docker Documentation](https://docs.docker.com/)

## 🔗 Related Projects

- [iota](https://github.com/iotaledger/iota) - Official IOTA implementation
- [fogbed](https://github.com/fogbed/fogbed) - Fog/Edge network emulator
- [mininet](https://github.com/mininet/mininet) - Network emulator

---

**⭐ If this project helped you, please consider giving it a star!**
