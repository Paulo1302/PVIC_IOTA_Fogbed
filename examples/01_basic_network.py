#!/usr/bin/env python3
"""
examples/01_basic_network_clean.py
Exemplo com cleanup automático
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fogbed import FogbedExperiment, Container
from fogbed_iota import IotaNetwork

def main():
    print("=== Rede IOTA com Cleanup Automático ===\n")
    
    # Criar experimento Fogbed
    exp = FogbedExperiment()
    
    # O uso do context manager (with ...) garante que a rede será parada
    # adequadamente e o workdir (/tmp/fogbed_iota_workdir) será limpo,
    # mesmo que o script sofra um erro (ex: interrupção do usuário via CTRL+C).
    with IotaNetwork(exp, image="iota-dev:latest", auto_cleanup=True) as iota_net:
        
        # Configurar rede
        print("📦 Configurando rede...")
        for i in range(1, 5):
            iota_net.add_validator(f"iota{i}", f"10.0.0.{i}")
        
        iota_net.add_gateway("gateway", "10.0.0.5")
        
        client = Container(
            name="client",
            dimage="iota-dev:latest",
            ip="10.0.0.100",
            privileged=True
        )
        iota_net.set_client(client)
        
        # Anexar e iniciar
        iota_net.attach_to_experiment("cloud")
        exp.start()
        
        print("🚀 Iniciando rede IOTA...")
        iota_net.start()
        
        print("\n✅ Rede pronta!")
        print(f"RPC: {iota_net.get_rpc_url()}")
        print(f"Metrics: {iota_net.get_metrics_url()}")
        
        # Fazer testes interativos
        print("\n💡 Comandos úteis:")
        print("  docker exec -it mn.client bash")
        print("  curl -X POST http://10.0.0.5:9000 -H 'Content-Type: application/json' \\")
        print("    -d '{\"jsonrpc\":\"2.0\",\"method\":\"iota_getChainIdentifier\",\"params\":[],\"id\":1}'")
        
        input("\nPressione ENTER para encerrar (cleanup automático)...")
    
    # Cleanup automático acontece aqui (saída do context manager)
    print("\n🧹 Limpeza automática concluída!")
    exp.stop()
    print("✅ Experimento finalizado")

if __name__ == "__main__":
    main()
