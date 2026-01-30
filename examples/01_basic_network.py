#!/usr/bin/env python3

import sys
import os
# Adiciona o diretório pai ao path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import time
from fogbed import FogbedExperiment, Container
from mininet.log import setLogLevel, info
from fogbed_iota import IotaNetwork

def main():
    setLogLevel("info")

    exp = FogbedExperiment()
    cloud = exp.add_virtual_instance("cloud")

    # Cria a rede IOTA
    iota_net = IotaNetwork(exp, image="iota-dev:latest")

    # 4 validadores + 1 gateway
    iota_net.add_validator("iota1", "10.0.0.1")
    iota_net.add_validator("iota2", "10.0.0.2")
    iota_net.add_validator("iota3", "10.0.0.3")
    iota_net.add_validator("iota4", "10.0.0.4")
    iota_net.add_gateway("gateway", "10.0.0.5")

    # cliente CLI
    client = Container(
        name="client",
        dimage="iota-dev:latest",
        ip="10.0.0.100",
        privileged=True,
        environment={"DEBIAN_FRONTEND": "noninteractive"},
    )
    iota_net.set_client(client)

    # anexa tudo ao experimento
    iota_net.attach_to_experiment(datacenter_name="cloud")

    info("=== Iniciando FogbedExperiment ===\n")
    exp.start()

    info("=== Iniciando IotaNetwork ===\n")
    iota_net.start()

    info("=== Ambiente pronto, aguardando estabilização ===\n")
    time.sleep(15)

    # Teste simples de gas
    info("Consultando 'iota client gas'...\n")
    print("🔍 Testando IOTA CLI...")
    res = client.cmd("iota --version")
    print(f"IOTA Version: {res}")

    print("🔍 Testando conectividade RPC...")
    rpc_test = client.cmd('curl -s http://10.0.0.5:9000')
    print(f"RPC Response: {rpc_test[:100]}...")

    print("🔍 Testando client com parâmetros explícitos...")
    gas_test = client.cmd('iota client gas --network devnet --output json')
    print(f"Gas Query: {gas_test}")

    input("Pressione ENTER para encerrar...")
    info(f"{res}\n")

    input("Pressione ENTER para encerrar...\n")
    exp.stop()


if __name__ == "__main__":
    main()
