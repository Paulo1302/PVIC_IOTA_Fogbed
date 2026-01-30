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

## 🚀 Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/your-username/fogbed-iota.git
cd fogbed-iota
```

### 2. Build the Docker image

```bash
docker build -f docker/Dockerfile -t iota-dev:latest .
```

### 3. Install Fogbed (if not already installed)

```bash
pip3 install fogbed
```

### 4. Run the example

```bash
sudo python3 examples/01_basic_network.py
```

That's it! 🎉 The system will automatically:
- Extract IOTA binaries from the Docker image
- Generate genesis configuration
- Deploy 4 validators + 1 gateway + 1 client
- Start all IOTA nodes

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

```bash
# Clean up previous network
sudo mn -c
docker rm -f $(docker ps -aq --filter "name=mn.")
```

### Issue: Binary not found

The system automatically extracts the IOTA binary from the Docker image. Ensure the image exists:

```bash
docker images | grep iota-dev
```

If missing, rebuild:

```bash
docker build -f docker/Dockerfile -t iota-dev:latest .
```

### Issue: Genesis generation fails

Check validator IPs are valid:

```bash
# Test genesis manually
/tmp/fogbed_iota_bin/iota genesis --working-dir /tmp/test --force
```

### Issue: Nodes not synchronizing

Wait 30-60 seconds for initial sync. Check logs:

```bash
docker exec -it mn.validator1 cat /app/iota.log | grep -i "sync\|error"
```

## 📁 Project Structure

```
fogbed-iota/
├── fogbed_iota/           # Main Python package
│   ├── __init__.py        # Package initialization
│   ├── __version__.py     # Version information
│   └── network.py         # Core IotaNetwork orchestrator
├── docker/                # Docker configurations
│   ├── Dockerfile         # Production IOTA node image
│   └── Dockerfile.dev     # Development image with tools
├── examples/              # Usage examples
│   ├── 01_basic_network.py      # 4 validators + gateway
│   └── 02_complete_network.py   # Advanced example
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
