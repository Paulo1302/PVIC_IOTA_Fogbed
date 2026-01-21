import sys
import os
import shutil
import glob
import time
import re

# --- CONFIGURAÇÃO DO AMBIENTE VIRTUAL ---
try:
    from fogbed import FogbedExperiment, Container
    from mininet.log import setLogLevel as mininetSetLogLevel
except ImportError:
    print("ERRO CRÍTICO: Bibliotecas do Fogbed não encontradas.")
    print("Execute usando: sudo ./fog-env/bin/python experiment_fogbed.py")
    sys.exit(1)

mininetSetLogLevel('info')

# --- DEFINIÇÕES ---
IMAGE_TAG = "fogbed/iota:latest" 
NUM_VALIDATORS = 4

# Pastas de trabalho
BASE_DIR = os.path.abspath("iota_data")
TEMP_GEN_DIR = os.path.join(BASE_DIR, "genesis_temp")
DATA_HOST_PATH = os.path.join(BASE_DIR, "live_data")

def force_cleanup():
    print(f"[*] Limpeza do ambiente...")
    if os.path.exists(BASE_DIR):
        shutil.rmtree(BASE_DIR)
    # Limpa containers antigos
    os.system("docker rm -f $(docker ps -aq --filter name=mn.*) > /dev/null 2>&1")
    os.system("sudo mn -c > /dev/null 2>&1")

def run_genesis_generation():
    print(f"[*] [Passo 1] Gerando Genesis (via Docker)...")
    os.makedirs(TEMP_GEN_DIR, exist_ok=True)
    
    ips = [f"10.0.0.{i+1}" for i in range(NUM_VALIDATORS)]
    ips_args = " ".join(ips)
    
    # Monta volume para salvar o genesis na pasta local
    cmd = (
        f"docker run --rm -v {TEMP_GEN_DIR}:/data {IMAGE_TAG} "
        f"iota genesis --working-dir /data --force --benchmark-ips {ips_args}"
    )
    
    try:
        os.system(cmd)
        # Corrige permissões de root para o usuário atual
        os.system(f"sudo chown -R {os.environ.get('USER', 'root')} {BASE_DIR}")
        print("   -> Geração concluída.")
    except Exception as e:
        print(f"   [!] Erro ao gerar genesis: {e}")
        sys.exit(1)

def process_validator_yaml(source, dest, node_id):
    """Ajusta caminhos e IPs no YAML para o ambiente Docker"""
    new_lines = []
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
            elif "listen-address:" in line:
                new_lines.append(f'  listen-address: "0.0.0.0:{p2p_port}"\n')
            elif "external-address:" in line:
                new_lines.append(f'  external-address: /ip4/10.0.0.{node_id+1}/udp/{p2p_port}\n')
            elif "epoch-db-pruning-period-secs:" in line or "num-epochs-to-retain:" in line:
                 continue
            else:
                new_lines.append(line)
    
    with open(dest, 'w') as f:
        f.writelines(new_lines)

def prepare_node_configs():
    print(f"[*] [Passo 2] Processando configurações...")
    os.makedirs(DATA_HOST_PATH, exist_ok=True)
    yaml_files = glob.glob(f"{TEMP_GEN_DIR}/*.yaml")
    
    validator_files = [f for f in yaml_files if "fullnode" not in f and os.path.basename(f).endswith(".yaml")]
    validator_files.sort()

    # Prepara Validadores
    for i in range(min(len(validator_files), NUM_VALIDATORS)):
        node_dir = f"{DATA_HOST_PATH}/iota-{i}"
        os.makedirs(node_dir, exist_ok=True)
        shutil.copy(f"{TEMP_GEN_DIR}/genesis.blob", f"{node_dir}/genesis.blob")
        process_validator_yaml(validator_files[i], f"{node_dir}/validator.yaml", node_id=i)

    # Prepara Gateway
    fullnode_src = f"{TEMP_GEN_DIR}/fullnode.yaml"
    fullnode_dir = f"{DATA_HOST_PATH}/fullnode"
    os.makedirs(fullnode_dir, exist_ok=True)
    
    if os.path.exists(f"{TEMP_GEN_DIR}/genesis.blob"):
        shutil.copy(f"{TEMP_GEN_DIR}/genesis.blob", f"{fullnode_dir}/genesis.blob")
    
    if os.path.exists(fullnode_src):
        process_validator_yaml(fullnode_src, f"{fullnode_dir}/validator.yaml", node_id=0)
    else:
        process_validator_yaml(validator_files[0], f"{fullnode_dir}/validator.yaml", node_id=0)

def main():
    force_cleanup()
    run_genesis_generation()
    prepare_node_configs()

    print("[*] [Passo 3] Iniciando Topologia Fogbed...")
    exp = FogbedExperiment()
    
    # 1. Cria a instância virtual (Switch Central)
    cloud = exp.add_virtual_instance('cloud')
    
    nodes_list = []
    
    # 2. Validadores
    for i in range(NUM_VALIDATORS):
        node = Container(
            name=f"iota{i}", 
            dimage=IMAGE_TAG, 
            ip=f"10.0.0.{i+1}",
            environment={"RUST_LOG": "info,iota_node=info"}
        )
        nodes_list.append(node)
        # Ao adicionar ao datacenter, o Fogbed já conecta o container ao switch da cloud
        exp.add_docker(node, datacenter=cloud)

    # 3. Gateway
    print("   -> Adicionando Fullnode (Gateway)...")
    gateway = Container(
        name="gateway", 
        dimage=IMAGE_TAG, 
        ip="10.0.0.5",
        environment={"RUST_LOG": "info,iota_node=info"}
    )
    exp.add_docker(gateway, datacenter=cloud)
    
    # 4. Cliente
    client = Container(
        name="client", 
        dimage=IMAGE_TAG, 
        ip="10.0.0.100"
    )
    exp.add_docker(client, datacenter=cloud)

    # --- REMOVIDO: Links manuais ---
    # Como todos estão no 'datacenter=cloud', eles já estão conectados em estrela.

    try:
        exp.start()
        print("[*] Rede iniciada. Injetando configs e rodando...")
        
        # Inicia Validadores
        for i, node in enumerate(nodes_list):
            node.cmd("mkdir -p /custom_config")
            os.system(f"docker cp {DATA_HOST_PATH}/iota-{i}/. mn.iota{i}:/custom_config/")
            
            print(f"    -> Iniciando iota{i}")
            node.cmd("nohup iota-node --config-path /custom_config/validator.yaml > /app/iota.log 2>&1 &")

        # Inicia Gateway
        gateway.cmd("mkdir -p /custom_config")
        os.system(f"docker cp {DATA_HOST_PATH}/fullnode/. mn.gateway:/custom_config/")
        
        print(f"    -> Iniciando gateway")
        gateway.cmd("nohup iota-node --config-path /custom_config/validator.yaml > /app/iota.log 2>&1 &")

        print("\n=== AMBIENTE PRONTO ===")
        print("Para testar, abra outro terminal e rode:")
        print("docker exec mn.client curl -s -X POST -H 'Content-Type: application/json' -d '{\"jsonrpc\":\"2.0\", \"id\":1, \"method\":\"iota_getLatestCheckpointSequenceNumber\", \"params\":[]}' http://10.0.0.5:9000")
        
        input("\nPressione ENTER para encerrar a simulação...")
        
    except Exception as e:
        print(f"[!] Erro: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n[*] Encerrando...")
        exp.stop()

if __name__ == "__main__":
    main()