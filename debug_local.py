import os
import subprocess
import time

# --- CONFIGURAÇÃO ---
BIN_PATH = "/home/paulo/iota/target/release/iota-node"
WORK_DIR = "/tmp/iota_debug"

print(f"--- INICIANDO LABORATÓRIO LOCAL ---")
if not os.path.exists(WORK_DIR): os.makedirs(WORK_DIR)

# 1. Cria Chave Falsa
with open(f"{WORK_DIR}/identity.key", "w") as f:
    f.write("A" * 44) # Chave base64 fake

# 2. Cria Genesis Falso
with open(f"{WORK_DIR}/genesis.blob", "w") as f:
    f.write("GENESIS_FAKE_DATA")

# 3. Cria o YAML (Vamos testar variações aqui)
# TENTATIVA ATUAL: Nome exato, com aspas, identado.
yaml_content = f"""
protocol-version: 1

p2p-config:
  bind-address: "/ip4/127.0.0.1/tcp/15600"
  external-address: "/ip4/127.0.0.1/tcp/15600"
  identity-file: "{WORK_DIR}/identity.key"

db-path: "{WORK_DIR}/db"

genesis:
  genesis-file-location: "{WORK_DIR}/genesis.blob"

consensus:
  max-submit-position: 10
"""

config_path = f"{WORK_DIR}/validator.yaml"
with open(config_path, "w") as f:
    f.write(yaml_content)

print("[*] Arquivos gerados. Executando binário...")
print(f"[*] Comando: {BIN_PATH} --config-path {config_path}")
print("-" * 40)

# 4. Executa o Binário e captura o output
try:
    # Rodamos por 2 segundos apenas, o suficiente para ver o erro de inicialização
    process = subprocess.Popen(
        [BIN_PATH, "--config-path", config_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, # Joga erro no mesmo lugar
        env={"RUST_LOG": "error"} # Só erros críticos
    )
    
    time.sleep(2)
    
    if process.poll() is None:
        print("[SUCESSO?] O processo continuou rodando! (Matando agora...)")
        process.terminate()
    else:
        print("[FALHA] O processo morreu cedo.")

    # Lê a saída
    out, _ = process.communicate()
    output_str = out.decode('utf-8', errors='ignore')
    
    if "no genesis location set" in output_str:
        print("\n❌ RESULTADO: ERRO PERSISTE (no genesis location set)")
    elif "failed to load genesis" in output_str or "No such file" in output_str:
        print("\n✅ RESULTADO: VITÓRIA! (Ele tentou ler o arquivo)")
    else:
        print(f"\n⚠️ RESULTADO INESPERADO:\n{output_str}")

except Exception as e:
    print(f"Erro: {e}")