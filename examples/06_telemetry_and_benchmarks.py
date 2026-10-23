#!/usr/bin/env python3
"""examples/06_telemetry_and_benchmarks.py

Executa a avaliação quantitativa de desempenho e telemetria na rede IOTA v1.33.1 em 3 camadas:
1. CONSULTAS RPC (Carga de Leitura): Vazão (RPC req/s) e latência p50..p99 com amostragem >= 100 reqs
2. RAJADA DE TRANSAÇÕES L1 (Carga de Escrita): Transferências reais a partir da Borda (10-50 txs)
3. MEDIÇÃO DE FINALIDADE POR TRANSAÇÃO: Registro individual t_send -> t_inclusion BFT (Starfish)
4. CONSUMO DE RECURSOS COMPUTACIONAIS: CPU %, RAM MB, I/O monitorados via cgroup/Docker para todos os nós (inclusive mn.client)

Executar (requer root por causa do Mininet):

    sudo mn -c
    sudo PYTHONPATH="$(pwd)" ./venv/bin/python3 examples/06_telemetry_and_benchmarks.py --requests 100 --tx-count 20
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fogbed import Container, FogbedExperiment  # noqa: E402
from fogbed_iota import DockerExecShell, IotaNetwork, TelemetrySession  # noqa: E402
from fogbed_iota.client.cli import IotaCLI  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--requests",
        type=int,
        default=100,
        help="número de requisições JSON-RPC de leitura para amostragem estatística (default: 100, range 100-1000)",
    )
    parser.add_argument(
        "--tx-count",
        type=int,
        default=20,
        help="número de transferências L1 na rajada de transações (default: 20, range 10-50)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="nível de concorrência simultânea para RPC (default: 2)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="",
        help="diretório para relatórios CSV e JSON (default: results/telemetry_<timestamp>)",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="não aguarda input interativo após a conclusão",
    )
    args = parser.parse_args()

    out_dir = Path(args.output_dir) if args.output_dir else Path(f"results/telemetry_{int(time.time())}")

    print("=== Avaliação de Telemetria e Métricas Quantitativas (IOTA v1.33.1) ===\n")
    exp = FogbedExperiment()

    with IotaNetwork(exp, image="iota-dev:latest", auto_cleanup=True) as iota_net:
        # 1. Configura topologia em 3 camadas
        iota_net.use_three_tier_topology(
            edge_fog={"delay": "20ms", "bw": 50, "loss": 1},
            fog_cloud={"delay": "50ms", "bw": 100, "loss": 0.1},
            edge_access={"delay": "2ms"},
        )

        for i in range(1, 5):
            iota_net.add_validator(f"iota{i}", f"10.0.0.{i}", tier="cloud")
        iota_net.add_gateway("gateway", "10.0.0.5", tier="fog")

        client = Container(name="client", dimage="iota-dev:latest", ip="10.0.0.100", privileged=True)
        iota_net.set_client(client, tier="edge")

        iota_net.attach_to_experiment()
        exp.start()

        print("🚀 Iniciando rede IOTA e nós validadores...")
        iota_net.start()

        # 2. Validação inicial de saúde da topologia
        print("\n🔎 Verificando saúde da topologia...")
        report = iota_net.validate_topology(send_transaction=True)
        print("\n" + report.format())
        if not report.ok:
            print("\n❌ A rede não passou na verificação de conformidade inicial. Abortando benchmark.")
            return 1

        # 3. Inicializa IotaCLI no contêiner cliente da Borda
        client_cli = IotaCLI(
            DockerExecShell("client"),
            network="fogbed",
            client_config=iota_net.client_config_path,
        )

        # 4. Inicialização da Sessão de Telemetria
        # source_container="client" garante que as chamadas RPC cruzam os switches s1->s2 da topologia
        # e exercitam o cgroup/CPU/RAM do mn.client
        print(f"\n📊 Iniciando Telemetria Contínua (Saída: {out_dir})...")
        session = TelemetrySession(
            network=iota_net,
            source_container="client",
            output_dir=out_dir,
            sample_interval=0.5,
        )

        with session:
            # Fase A: Aquecimento (Warm-up)
            print("  [1/4] Aquecendo conexões e caches (warmup)...")
            session.run_rpc_workload(count=5, concurrency=1)
            time.sleep(1)

            # Fase B: Benchmark de Consultas JSON-RPC (Carga de Leitura)
            # Amostra >= 100 requisições para percentis confiáveis (especialmente p99)
            print(f"  [2/4] Executando benchmark RPC (Leitura): {args.requests} chamadas (concorrência: {args.concurrency})...")
            rpc_res = session.run_rpc_workload(
                count=args.requests,
                concurrency=args.concurrency,
                method="iota_getLatestCheckpointSequenceNumber",
            )
            print(
                f"       -> Vazão de Leitura: {rpc_res.throughput_tps:.2f} RPC req/s "
                f"({rpc_res.successful_requests}/{args.requests} sucessos em {rpc_res.elapsed_seconds:.2f}s)"
            )

            # Fase C: Rajada de Transações L1 (Carga de Escrita / Finalidade por Transação)
            print(f"  [3/4] Executando rajada de transações L1: {args.tx_count} transferências a partir da Borda...")
            recipient_addr = iota_net.client_recipient or client_cli.get_active_address()
            tx_res = session.run_transaction_burst(
                cli=client_cli,
                recipient=recipient_addr,
                count=args.tx_count,
                concurrency=1,
            )
            print(
                f"       -> Vazão de Escrita: {tx_res.throughput_tps:.2f} Confirmed tx/s "
                f"({tx_res.successful_requests}/{args.tx_count} confirmadas em {tx_res.elapsed_seconds:.2f}s)"
            )

            # Fase D: Finalização de telemetria
            print("  [4/4] Coletando métricas do Prometheus e finalizando monitoramento...")
            time.sleep(2)

        # 5. Impressão do Resumo Executivo
        print("\n" + session.stop().format_terminal_summary())
        print(f"\n📁 Arquivos de telemetria gerados com sucesso em: {out_dir.resolve()}")
        for f in sorted(out_dir.glob("*")):
            print(f"  - {f.name} ({f.stat().st_size} bytes)")

        if not args.no_wait:
            input("\nPressione ENTER para encerrar e limpar a emulação...")

    exp.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
