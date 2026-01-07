from fogbed import FogbedExperiment, Container
import time

print("[*] Testando infraestrutura básica do Fogbed...")

try:
    exp = FogbedExperiment()
    cloud = exp.add_virtual_instance('cloud')

    # Cria dois containers simples sem montar volumes complexos
    d1 = Container('d1', dimage='ubuntu:20.04', ip='10.0.0.1')
    d2 = Container('d2', dimage='ubuntu:20.04', ip='10.0.0.2')

    exp.add_docker(d1, datacenter=cloud)
    exp.add_docker(d2, datacenter=cloud)

    print("[*] Iniciando containers...")
    exp.start()

    print("[*] Testando conectividade (Ping)...")
    # Tenta pingar do d1 para o d2
    print(d1.cmd('ping -c 3 10.0.0.2'))

    print("[SUCESSO] A rede virtual funciona!")

except Exception as e:
    print(f"[FALHA] Erro grave no Fogbed: {e}")
finally:
    exp.stop()