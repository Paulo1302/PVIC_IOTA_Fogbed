#!/usr/bin/env python3

"""
Exemplo completo usando a classe IotaNetwork existente ✅
"""

from fogbed import FogbedExperiment, Container
from fogbed_iota import IotaNetwork
from mininet.log import setLogLevel
import time

def main():
    # ⚠️ AVISO DE LIMPEZA MANUAL
    print("=" * 70)
    print("⚠️  IMPORTANTE: Verifique Containers Anteriores".center(70))
    print("=" * 70)
    print("\n🔒 Por segurança, verifique manualmente se há containers anteriores:")
    print("   docker ps -a --filter 'name=mn.'")
    print("\nSe houver containers deste projeto, remova manualmente:")
    print("   docker rm -f <container_id>")
    print("   sudo mn -c")
    print("\n" + "=" * 70 + "\n")
    import time
    time.sleep(2)

    setLogLevel('info')

    print("🚀 Criando rede IOTA completa com Fogbed...\n")

    # 1. Criar experimento Fogbed
    exp = FogbedExperiment()

    # 2. Criar datacenter (topologia automática)
    print("☁️ Criando datacenter 'cloud'...")
    cloud = exp.add_virtual_instance("cloud")
    print(" ✅ Datacenter criado")

    # 3. Criar rede IOTA
    iota_net = IotaNetwork(experiment=exp, image='iota-dev:latest')

    # 4. Adicionar 4 validadores
    print("📦 Adicionando validadores...")
    for i in range(1, 5):
        validator = iota_net.add_validator(
            name=f'validator{i}',
            ip=f'10.0.0.{10+i}'
        )
        print(f" ✅ {validator.name} - {validator.ip_addr}")

    # 5. Adicionar gateway (fullnode)
    print("\n📦 Adicionando gateway...")
    gateway = iota_net.add_gateway(
        name='gateway',
        ip='10.0.0.100'
    )
    print(f" ✅ {gateway.name} - {gateway.ip_addr} (RPC: {gateway.rpc_port})")

    # 6. Adicionar cliente CLI
    print("\n📦 Adicionando cliente CLI...")
    client = Container(
        name='client',
        dimage='iota-dev:latest',
        ip='10.0.0.200',
        dcmd='tail -f /dev/null'
    )
    iota_net.set_client(client)

    # 7. ✅ ANEXAR NO DATACENTER (inclui client automaticamente)
    print("\n🔗 Anexando nós ao datacenter 'cloud'...")
    iota_net.attach_to_experiment(datacenter_name="cloud")
    print(" ✅ Todos conectados automaticamente (topologia estrela)")

    # 8. Iniciar rede Fogbed
    print("\n▶️ Iniciando rede Fogbed...")
    exp.start()
    print(" ✅ Rede iniciada")

    # 9. Configurar e iniciar nós IOTA
    print("\n⚙️ Configurando e iniciando nós IOTA...")
    print(" (gerando genesis, patcheando configs, subindo processos...)")
    iota_net.start()

    print(f"\n🌐 RPC Gateway: http://{gateway.ip_addr}:{gateway.rpc_port} ✅")
    print(f"📊 Prometheus Metrics: http://{gateway.ip_addr}:9184/metrics")

    print("\n✅ Rede IOTA totalmente operacional!")

    print(f"\n📊 Resumo:")
    print(f" Validadores: {len([n for n in iota_net.nodes if n.role == 'validator'])}")
    print(f" Gateway: {gateway.name} @ {gateway.ip_addr}:{gateway.rpc_port}")
    print(f" Cliente: {client.name} @ {client.ip}")

    print("\n💡 Comandos úteis:")
    print(f" # Testar RPC")
    print(f" curl -X POST http://{gateway.ip_addr}:{gateway.rpc_port} \\")
    print(f"   -H 'Content-Type: application/json' \\")
    print(f"   -d '{{\"jsonrpc\":\"2.0\",\"method\":\"iota_getChainIdentifier\",\"params\":[],\"id\":1}}'")
    print(f"")
    print(f" # Acessar cliente CLI")
    print(f" docker exec -it mn.client iota client --help")
    print(f"")
    print(f" # Ver logs do gateway")
    print(f" docker exec -it mn.gateway tail -f /app/iota.log")
    print(f"")
    print(f" # Ver métricas Prometheus")
    print(f" curl http://{gateway.ip_addr}:9184/metrics")

    print("\n⏸️ CTRL+C para parar...")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Encerrando...")
        exp.stop()
        print("✅ Finalizado!")

if __name__ == '__main__':
    main()