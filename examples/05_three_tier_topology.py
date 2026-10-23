#!/usr/bin/env python3
"""examples/05_three_tier_topology.py

Topologia experimental de 3 camadas (Borda · Névoa · Nuvem) sobre a rede IOTA:

    [edge: client] ──(20ms,50Mbit,1%)── [fog: gateway] ──(50ms,100Mbit,0.1%)── [cloud: iota1..4]
          s1                                   s2                                       s3

* cada camada é um switch OVS (um `VirtualInstance` do Fogbed), encadeados em árvore (sem ciclos);
* todos os nós mantêm IPs estáticos 10.0.0.x (um único domínio L2 do Mininet);
* após subir, `validate_topology()` prova — A PARTIR DO CONTÊINER DE BORDA — IP, RTT ≈ atrasos
  configurados, RPC :9000, métricas :9184, TCP :8080 aos validadores, UDP :8084, avanço de
  checkpoints (consenso atravessando os switches) e uma transação PTB em L1.

Executar (requer root, por causa do Mininet):

    sudo mn -c
    sudo PYTHONPATH="$(pwd)" /opt/fogbed/venv/bin/python3 examples/05_three_tier_topology.py
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fogbed import Container, FogbedExperiment  # noqa: E402

from fogbed_iota import IotaNetwork  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-tx", action="store_true", help="não envia a transação PTB de teste")
    parser.add_argument("--publish", metavar="PATH", help="caminho (DENTRO do cliente) de um pacote Move a publicar (opcional)")
    parser.add_argument("--no-wait", action="store_true", help="encerra logo após a verificação (CI)")
    args = parser.parse_args()

    print("=== Rede IOTA em 3 camadas (Borda · Névoa · Nuvem) ===\n")
    exp = FogbedExperiment()

    with IotaNetwork(exp, image="iota-dev:latest", auto_cleanup=True) as iota_net:
        # Camadas e enlaces heterogêneos (valores ilustrativos: ajuste ao seu experimento)
        iota_net.use_three_tier_topology(
            edge_fog={"delay": "20ms", "bw": 50, "loss": 1},
            fog_cloud={"delay": "50ms", "bw": 100, "loss": 0.1},
            edge_access={"delay": "2ms"},  # último salto de rádio do dispositivo de borda
        )

        for i in range(1, 5):
            iota_net.add_validator(f"iota{i}", f"10.0.0.{i}", tier="cloud")
        iota_net.add_gateway("gateway", "10.0.0.5", tier="fog")

        client = Container(name="client", dimage="iota-dev:latest", ip="10.0.0.100", privileged=True)
        iota_net.set_client(client, tier="edge")

        iota_net.attach_to_experiment()      # cria s1/s2/s3 e os enlaces (antes de exp.start)
        print(json.dumps(iota_net.describe_topology(), indent=2))

        exp.start()
        print("\n🚀 Iniciando rede IOTA...")
        iota_net.start()                     # gênese 2 passos + nós + provisionamento do cliente de borda

        print("\n🔎 Verificando a topologia a partir da Borda...\n")
        report = iota_net.validate_topology(
            send_transaction=not args.skip_tx,
            publish_package_path=args.publish,
        )
        print("\n" + report.format())

        if not args.no_wait:
            print("\n💡 Comandos úteis:")
            print("  docker exec -it mn.client iota client gas")
            print("  docker exec -it mn.client ping -c 3 10.0.0.1      # borda -> nuvem (~140ms+)")
            print(f"  curl -s {iota_net.get_metrics_url(host=True)} | head")
            input("\nPressione ENTER para encerrar (cleanup automático)...")

    exp.stop()
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
