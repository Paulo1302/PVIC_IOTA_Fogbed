#!/usr/bin/env python3
"""
CLI para gerenciar ambiente IOTA+Fogbed
"""

import argparse
import sys
import os
import subprocess  # FALTAVA ESTE IMPORT

# Adicionar path do projeto
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fogbed_iota.utils.system import check_system_state, cleanup_system


def cmd_status(args):
    """Mostra estado atual do sistema"""
    state = check_system_state()
    
    print("📊 Estado do Sistema IOTA+Fogbed\n")
    print(f"Containers Mininet: {len(state['mininet_containers'])}")
    if state['mininet_containers']:
        for c in state['mininet_containers']:
            print(f"  - {c}")
    
    print(f"\nDiretórios de trabalho: {'Sim' if state['work_dirs_exist'] else 'Não'}")
    if state['work_dirs_exist']:
        print(f"  Tamanho: {state['work_dir_size']} MB")
    
    print(f"\nArquivos temporários: {len(state['temp_files'])}")


def cmd_clean(args):
    """Limpa sistema"""
    cleanup_system(force=args.force)


def cmd_check(args):
    """Verifica pré-requisitos"""
    print("🔍 Verificando pré-requisitos...\n")
    
    checks = {
        "Docker": ["docker", "--version"],
        "Python 3.8+": ["python3", "--version"],
        "Fogbed": ["python3", "-c", "import fogbed"],
        "sudo": ["sudo", "-n", "true"]
    }
    
    all_ok = True
    for name, cmd in checks.items():
        try:
            result = subprocess.run(cmd, capture_output=True, check=True, timeout=5)
            print(f"✅ {name}")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            print(f"❌ {name}")
            all_ok = False
    
    if all_ok:
        print("\n✅ Todos os pré-requisitos atendidos!")
    else:
        print("\n⚠️  Alguns pré-requisitos estão faltando")
        print("\n💡 Dica: Execute 'sudo -v' para atualizar credenciais sudo")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Gerenciador IOTA+Fogbed",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Comandos')
    
    # status
    subparsers.add_parser('status', help='Mostra estado do sistema')
    
    # clean
    clean_parser = subparsers.add_parser('clean', help='Limpa sistema')
    clean_parser.add_argument('-f', '--force', action='store_true',
                             help='Não pedir confirmação')
    
    # check
    subparsers.add_parser('check', help='Verifica pré-requisitos')
    
    args = parser.parse_args()
    
    if args.command == 'status':
        cmd_status(args)
    elif args.command == 'clean':
        cmd_clean(args)
    elif args.command == 'check':
        cmd_check(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
