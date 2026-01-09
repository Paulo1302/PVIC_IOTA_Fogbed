#!/usr/bin/env python3
import time
import sys
from fogbed import FogbedExperiment, Container
from iota_fogbed import IotaNetworkManager
from mininet.log import setLogLevel, info, error

def main():
    # Define o nível de log para INFO (limpo, mas informativo)
    # Se der erro, mude para 'debug'
    setLogLevel('info')
    
    info("=== INICIANDO EXPERIMENTO IOTA ===\n")

    try:
        exp = FogbedExperiment()
        cloud = exp.add_virtual_instance('cloud')
        
        iota_net = IotaNetworkManager(exp)
        
        info("=== Configurando Topologia ===\n")
        
        # Validadores
        v1 = iota_net.add_node("iota1", "10.0.0.1", role="validator")
        v2 = iota_net.add_node("iota2", "10.0.0.2", role="validator")
        v3 = iota_net.add_node("iota3", "10.0.0.3", role="validator")
        v4 = iota_net.add_node("iota4", "10.0.0.4", role="validator")
        
        # Gateway (Fullnode que recebe requisições)
        gateway = iota_net.add_node("gateway", "10.0.0.5", role="fullnode")
        
        # Cliente (Onde rodamos os comandos CLI)
        # privileged=True é essencial para evitar bloqueios de permissão
        client = Container(
            name="client", 
            dimage="iota-dev:latest", 
            ip="10.0.0.100",
            # Mapeia o binário compilado para dentro do container
            volumes=[f"/home/paulo/iota/target/release/iota:/usr/local/bin/iota"],
            privileged=True,
            environment={"DEBIAN_FRONTEND": "noninteractive"}
        )
        exp.add_docker(client, datacenter=cloud)
        iota_net.set_client(client)

        # Adiciona os nós IOTA à infraestrutura
        for node in iota_net.nodes:
            exp.add_docker(node, datacenter=cloud)
        
        info("=== Iniciando FogbedExperiment ===\n")
        exp.start()
        
        info("=== Iniciando IotaNetworkManager ===\n")
        iota_net.start()
        
        info("\n=== AMBIENTE PRONTO ===\n")
        info("Aguardando 15s para estabilização da rede e descoberta de peers...\n")
        time.sleep(15)
        
        # --- CORREÇÃO DO TRAVAMENTO ---
        info("1. Preparando Keystore e Endereço...\n")
        
        # Garante que a pasta existe
        client.cmd("mkdir -p /root/.iota")
        
        # Gera uma chave nova silenciosamente (yes evita perguntas de confirmação)
        # Se o comando 'keytool' for diferente na sua versão, avise.
        # Geralmente é 'iota keytool generate' ou 'iota address build'
        info("   Gerando chave Ed25519...\n")
        client.cmd("yes | iota keytool generate ed25519")
        
        # --- CONSULTA DE GÁS ---
        info("2. Consultando 'iota client gas'...\n")
        
        # --url: Força conexão no Gateway (evita menu interativo)
        # --json: Garante saída legível para automação
        cmd = "iota client gas  --json"
        
        info(f"   Executando: {cmd}\n")
        res = client.cmd(cmd)
        
        info("=== RESULTADO DA CONSULTA ===\n")
        info(f"{res}\n")
        info("=============================\n")
        
        input("\nPressione ENTER para encerrar a simulação...")
        
    except Exception as e:
        error(f"\nERRO FATAL CAPTURADO: {e}\n")
        import traceback
        traceback.print_exc()
    finally:
        info("=== Parando Experimento ===\n")
        exp.stop()

if __name__ == "__main__":
    main()