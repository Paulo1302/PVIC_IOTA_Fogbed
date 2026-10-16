#!/usr/bin/env python3
"""
examples/01_basic_network_clean.py
Exemplo com cleanup automático
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fogbed import FogbedExperiment, Container
from fogbed_iota.network import IotaNetwork

def main():
    print("=== Rede IOTA com Cleanup Automático ===\n")
    
    # Criar experimento Fogbed
    exp = FogbedExperiment()
    
    # Usar context manager para garantir cleanup
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
        print(f"🌐 Acesso via Host / Navegador:")
        print(f"   RPC:     {iota_net.get_rpc_url(host=True)}  (JSON-RPC 2.0 / WebSocket via POST)")
        print(f"   Metrics: {iota_net.get_metrics_url(host=True)}  (Abre no navegador)")
        print(f"\n📦 Acesso interno Fogbed (outros containers):")
        print(f"   RPC:     {iota_net.get_rpc_url(host=False)}")
        print(f"   Metrics: {iota_net.get_metrics_url(host=False)}")
        
        # Fazer testes interativos
        print("\n💡 Comandos úteis para testar:")
        print("  # 1. No seu terminal Host:")
        print("  curl -X POST http://localhost:9000 -H 'Content-Type: application/json' \\")
        print("    -d '{\"jsonrpc\":\"2.0\",\"method\":\"iota_getChainIdentifier\",\"params\":[],\"id\":1}'")
        print("  curl -s http://localhost:9184/metrics | head -n 15")
        print("\n  # 2. De dentro do container cliente (mn.client):")
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
