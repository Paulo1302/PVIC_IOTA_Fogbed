# fogbed_iota/utils/system.py

"""
Utilitários para verificar e limpar estado do sistema
"""

import os
import subprocess
import shutil
from typing import List, Dict

def check_system_state() -> Dict[str, any]:
    """
    Verifica estado atual do sistema
    
    Returns:
        Dict com informações sobre containers, arquivos, etc.
    """
    state = {
        "mininet_containers": [],
        "temp_files": [],
        "docker_networks": [],
        "work_dirs_exist": False
    }
    
    # Containers Mininet
    result = subprocess.run(
        ["docker", "ps", "-a", "--filter", "name=mn.", "--format", "{{.Names}}"],
        capture_output=True,
        text=True
    )
    if result.stdout:
        state["mininet_containers"] = result.stdout.strip().split('\n')
    
    # Diretórios de trabalho
    work_dir = "/tmp/fogbed_iota_workdir"
    if os.path.exists(work_dir):
        state["work_dirs_exist"] = True
        state["work_dir_size"] = _get_dir_size(work_dir)
    
    # Binários temporários
    temp_bin = "/tmp/fogbed_iota_bin"
    if os.path.exists(temp_bin):
        state["temp_files"].append(temp_bin)
    
    return state


def cleanup_system(force: bool = False) -> None:
    """
    Limpa completamente o sistema de restos de execuções anteriores
    
    Args:
        force: Se True, não pede confirmação
    """
    print("🔍 Verificando estado do sistema...")
    state = check_system_state()
    
    if not any([
        state["mininet_containers"],
        state["work_dirs_exist"],
        state["temp_files"]
    ]):
        print("✅ Sistema já está limpo!")
        return
    
    print("\n📋 Itens a serem removidos:")
    if state["mininet_containers"]:
        print(f"  - {len(state['mininet_containers'])} container(s) Mininet")
    if state["work_dirs_exist"]:
        print(f"  - Diretório de trabalho ({state['work_dir_size']} MB)")
    if state["temp_files"]:
        print(f"  - {len(state['temp_files'])} arquivo(s) temporário(s)")
    
    if not force:
        response = input("\n⚠️  Confirma limpeza? (y/N): ")
        if response.lower() != 'y':
            print("Cancelado.")
            return
    
    print("\n🧹 Limpando...")
    
    # Limpar Mininet
    subprocess.run(["sudo", "mn", "-c"], capture_output=True)
    
    # Remover containers
    if state["mininet_containers"]:
        subprocess.run(
            ["docker", "rm", "-f"] + state["mininet_containers"],
            capture_output=True
        )
    
    # Remover diretórios
    for path in ["/tmp/fogbed_iota_workdir", "/tmp/fogbed_iota_bin"]:
        if os.path.exists(path):
            shutil.rmtree(path)
    
    print("✅ Limpeza concluída!")


def _get_dir_size(path: str) -> float:
    """Retorna tamanho do diretório em MB"""
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.exists(fp):
                total += os.path.getsize(fp)
    return round(total / (1024 * 1024), 2)
