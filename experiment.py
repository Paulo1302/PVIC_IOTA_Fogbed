import os
import shutil
import glob
import subprocess
import time
import re
from fogbed import FogbedExperiment, Container

# --- CAMINHOS ---
IOTA_REPO_DIR = "/home/paulo/iota"
GEN_TOOL = f"{IOTA_REPO_DIR}/target/release/iota"
NODE_BIN = f"{IOTA_REPO_DIR}/target/release/iota-node"

# Pastas
TEMP_GEN_DIR = "/tmp/iota_gen_v11" 
DATA_HOST_PATH = "/tmp/iota-live-data" 

NUM_VALIDATORS = 4
IMAGE_TAG = "iota-dev:latest" 

def force_cleanup():
    print(f"[*] Limpeza Nuclear...")
    os.system(f"sudo rm -rf {TEMP_GEN_DIR}")
    os.system(f"sudo rm -rf {DATA_HOST_PATH}")
    os.system("sudo killall -9 mn iota-node > /dev/null 2>&1")
    os.system("docker rm -f $(docker ps -aq) > /dev/null 2>&1")
    os.system("sudo service openvswitch-switch restart") 
    os.system("sudo mn -c > /dev/null 2>&1")

def run_genesis_generation():
    print(f"[*] [Passo 1] Gerando Genesis...")
    os.makedirs(TEMP_GEN_DIR, exist_ok=True)
    ips = [f"10.0.0.{i+1}" for i in range(NUM_VALIDATORS)]
    cmd = [GEN_TOOL, "genesis", "--working-dir", TEMP_GEN_DIR, "--force", "--benchmark-ips"] + ips
    try:
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("   -> Geração concluída.")
    except Exception as e:
        print(f"   [!] Erro ao gerar genesis: {e}")
        exit(1)

def extract_key_value(content, key_name):
    pattern = re.compile(rf"{key_name}:\s*\n\s*value:\s*(.+)")
    match = pattern.search(content)
    if match:
        return match.group(1).strip()
    return ""

def create_clean_gateway_config(source_path, dest_path):
    """Cria config do Gateway (Fullnode). Aponta para portas corretas (2001, 2011...)"""
    with open(source_path, 'r') as f:
        content = f.read()
    
    auth_key = extract_key_value(content, "authority-key-pair")
    prot_key = extract_key_value(content, "protocol-key-pair")
    acct_key = extract_key_value(content, "account-key-pair")
    net_key = extract_key_value(content, "network-key-pair")
    
    # Gateway continua na porta 15600 para não conflitar, ele é passivo.
    template = f"""---
authority-key-pair:
  value: {auth_key}
protocol-key-pair:
  value: {prot_key}
account-key-pair:
  value: {acct_key}
network-key-pair:
  value: {net_key}
db-path: "/app/db"
network-address: /ip4/0.0.0.0/tcp/8080/http
json-rpc-address: "0.0.0.0:9000"
enable-rest-api: true
metrics-address: "0.0.0.0:9184"
admin-interface-address: "0.0.0.0:1337"
enable-index-processing: false
grpc-concurrency-limit: 20000000000
p2p-config:
  listen-address: "0.0.0.0:15600"
  external-address: /ip4/10.0.0.5/udp/15600
  seed-peers:
"""
    # CORREÇÃO P2P: Aponta para as portas que o Genesis definiu
    for i in range(NUM_VALIDATORS):
        p2p_port = 2001 + (i * 10) # 2001, 2011, 2021...
        template += f"    - address: /ip4/10.0.0.{i+1}/udp/{p2p_port}\n"

    template += """genesis:
  genesis-file-location: "/custom_config/genesis.blob"
"""
    with open(dest_path, 'w') as f:
        f.write(template)
    os.system(f"chmod 777 {dest_path}")

def process_validator_yaml(source, dest, node_id):
    """Configura Validadores nas portas CERTAS (2001+) e Pruning OFF"""
    new_lines = []
    # Calcula a porta P2P correta para este nó
    p2p_port = 2001 + (node_id * 10)
    
    with open(source, 'r') as f:
        for line in f:
            if "db-path:" in line and "consensus" not in line:
                new_lines.append('db-path: "/app/db"\n')
            elif "db-path:" in line and "consensus" in line:
                new_lines.append('  db-path: "/app/consensus_db"\n')
            elif "genesis-file-location:" in line:
                new_lines.append('  genesis-file-location: "/custom_config/genesis.blob"\n')
            elif "network-address:" in line:
                new_lines.append('network-address: /ip4/0.0.0.0/tcp/8080/http\n')
            elif "metrics-address:" in line:
                new_lines.append('metrics-address: "0.0.0.0:9184"\n')
            
            # --- MUDANÇA CRÍTICA: Porta Dinâmica ---
            elif "listen-address:" in line:
                new_lines.append(f'  listen-address: "0.0.0.0:{p2p_port}"\n')
            
            elif "external-address:" in line:
                new_lines.append(f'  external-address: /ip4/10.0.0.{node_id+1}/udp/{p2p_port}\n')
            
            # Pruning Off
            elif "epoch-db-pruning-period-secs:" in line:
                 new_lines.append('  epoch-db-pruning-period-secs: 100000000\n')
            elif "num-epochs-to-retain:" in line:
                 new_lines.append('  num-epochs-to-retain: 1000000\n')
            elif "num-latest-epoch-dbs-to-retain:" in line:
                 new_lines.append('  num-latest-epoch-dbs-to-retain: 1000000\n')
            
            elif "migration-tx-data-path:" in line:
                continue 
            else:
                new_lines.append(line)
    
    with open(dest, 'w') as f:
        f.writelines(new_lines)
    os.system(f"chmod 777 {dest}")

def prepare_node_configs():
    print(f"[*] [Passo 2] Configurando portas corretas (2001+)...")
    os.makedirs(DATA_HOST_PATH, exist_ok=True)
    yaml_files = glob.glob(f"{TEMP_GEN_DIR}/*.yaml")
    validator_files = [f for f in yaml_files if os.path.basename(f)[0].isdigit()]
    validator_files.sort()

    for i in range(NUM_VALIDATORS):
        node_dir = f"{DATA_HOST_PATH}/iota-{i}"
        os.makedirs(node_dir, exist_ok=True)
        shutil.copy(f"{TEMP_GEN_DIR}/genesis.blob", f"{node_dir}/genesis.blob")
        process_validator_yaml(validator_files[i], f"{node_dir}/validator.yaml", node_id=i)

    fullnode_dir = f"{DATA_HOST_PATH}/fullnode"
    os.makedirs(fullnode_dir, exist_ok=True)
    shutil.copy(f"{TEMP_GEN_DIR}/genesis.blob", f"{fullnode_dir}/genesis.blob")
    create_clean_gateway_config(f"{TEMP_GEN_DIR}/fullnode.yaml", f"{fullnode_dir}/validator.yaml")

def main():
    force_cleanup()
    run_genesis_generation()
    prepare_node_configs()

    print("[*] [Passo 3] Construindo Topologia Fogbed...")
    exp = FogbedExperiment()
    cloud = exp.add_virtual_instance('cloud')
    
    nodes_list = []
    
    # 1. Validadores
    for i in range(NUM_VALIDATORS):
        node = Container(
            name=f"iota{i}", dimage=IMAGE_TAG, ip=f"10.0.0.{i+1}",
            volumes=[f"{NODE_BIN}:/usr/local/bin/iota-node"],
            environment={"RUST_LOG": "info,iota_node=info"}
        )
        exp.add_docker(container=node, datacenter=cloud)
        nodes_list.append(node)

    # 2. Gateway
    print("   -> Adicionando Fullnode (Gateway)...")
    gateway = Container(
        name="gateway", dimage=IMAGE_TAG, ip="10.0.0.5",
        volumes=[f"{NODE_BIN}:/usr/local/bin/iota-node"],
        environment={"RUST_LOG": "info,iota_node=info"}
    )
    exp.add_docker(container=gateway, datacenter=cloud)
    
    # 3. VM Cliente
    print("   -> Adicionando VM Cliente...")
    client_vm = Container(
        name="client-vm", dimage=IMAGE_TAG, ip="10.0.0.100",
        volumes=[f"{GEN_TOOL}:/usr/local/bin/iota"]
    )
    exp.add_docker(container=client_vm, datacenter=cloud)

    try:
        exp.start()
        print("[*] Rede iniciada. Injetando configs...")
        
        for i, node in enumerate(nodes_list):
            node.cmd("mkdir -p /custom_config")
            os.system(f"docker cp {DATA_HOST_PATH}/iota-{i}/. mn.iota{i}:/custom_config/")
            node.cmd("nohup /usr/local/bin/iota-node --config-path /custom_config/validator.yaml > /app/iota.log 2>&1 &")

        # Inicia Gateway IMEDIATAMENTE
        gateway.cmd("mkdir -p /custom_config")
        os.system(f"docker cp {DATA_HOST_PATH}/fullnode/. mn.gateway:/custom_config/")
        gateway.cmd("nohup /usr/local/bin/iota-node --config-path /custom_config/validator.yaml > /app/iota.log 2>&1 &")

        print("\n=== AGUARDANDO 40 SEGUNDOS (Sincronização Pós-Época) ===")
        time.sleep(40)
        
        print("\n[*] [Passo 4] Testando API do Gateway...")
        setup_cmd = """
        mkdir -p /root/.iota/iota_config
        echo '---
keystore:
  File: /root/.iota/iota.keystore
envs:
  fognet:
    rpc: "http://10.0.0.5:9000"
    ws: ~
    basic_auth: ~
active_env: fognet
' > /root/.iota/client.yaml
        """
        client_vm.cmd(setup_cmd)

        api_cmd = "curl -s -X POST -H 'Content-Type: application/json' -d '{\"jsonrpc\":\"2.0\", \"id\":1, \"method\":\"iota_getLatestCheckpointSequenceNumber\", \"params\":[]}' http://10.0.0.5:9000"
        json_res = client_vm.cmd(api_cmd)
        
        print(f"   [Resposta da API]: {json_res}")
        if "result" in json_res:
            print("\n✅ SUCESSO! A API JSON-RPC está viva!")
        else:
            print("\n⚠️ Verifique logs do Gateway (ainda sincronizando?).")

        print("\n[ENTER para sair]")
        input()
        
    except Exception as e:
        print(f"[!] Erro: {e}")
    finally:
        exp.stop()

if __name__ == "__main__":
    main()