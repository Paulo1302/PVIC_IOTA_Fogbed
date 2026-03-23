#!/usr/bin/env python3
"""
test_transaction_fix_v2.py

Teste COMPLETO para validar a correção de transferências automáticas.
Inclui testes de:
1. Geração de comando PTB
2. Parsing de JSON response
3. Parsing de texto formatado (fallback)
"""

import json
from fogbed_iota.client.transaction import TransactionBuilder


def test_command_generation():
    """Teste 1: Validar geração de comando PTB"""
    print("\n" + "="*80)
    print("TESTE 1: Geração de Comando PTB")
    print("="*80 + "\n")

    sender = "0x5d7e08e992c370d541774b77a8dd0e1f7047a757c047ae19733a4d3975ef9e33"
    recipient = "0xeb60e26e1ce4b82a5371ed67bdc192fb26cf5c2b6175c410d0878266e657ae41"
    amount = 100_000

    tx = TransactionBuilder(sender=sender, gas_budget=10_000_000)
    tx.transfer_iota([recipient], [amount])

    cmd = tx.build_cli_command()

    print(f"Comando gerado:")
    print(f"  {cmd}\n")

    checks = {
        "✅ Tem @ no sender": f"@{sender}" in cmd,
        "✅ Tem @ no recipient": f"@{recipient}" in cmd,
        "✅ Tem --json": "--json" in cmd,
    }

    all_pass = all(checks.values())
    for check, result in checks.items():
        print(f"  {check if result else check.replace('✅', '❌')}")

    return all_pass


def test_json_parsing():
    """Teste 2: Validar parsing de JSON response"""
    print("\n" + "="*80)
    print("TESTE 2: Parsing de JSON Response (Sucesso)")
    print("="*80 + "\n")

    success_response = json.dumps({
        "digest": "ABC123DEF456GHI789",
        "status": "success",
        "effects": {
            "gasUsed": {
                "computationCost": 1000000,
                "storageCost": 500000,
                "storageRebate": 100000
            }
        }
    })

    tx = TransactionBuilder(sender="0xtest", gas_budget=10_000_000)
    result = tx._parse_execution_result(success_response)

    print(f"Response parseado:")
    print(f"  Success: {result['success']}")
    print(f"  Digest: {result.get('digest', 'N/A')}")
    print(f"  Gas Used: {result.get('gas_used', 'N/A')}\n")

    checks = {
        "✅ Success = True": result['success'] == True,
        "✅ Digest extraído": result.get('digest') == "ABC123DEF456GHI789",
        "✅ Gas calculado": result.get('gas_used') == 1400000,
    }

    all_pass = all(checks.values())
    for check, result_val in checks.items():
        print(f"  {check if result_val else check.replace('✅', '❌')}")

    return all_pass


def test_json_error_parsing():
    """Teste 3: Validar parsing de JSON com erro"""
    print("\n" + "="*80)
    print("TESTE 3: Parsing de JSON Response (Erro)")
    print("="*80 + "\n")

    error_response = json.dumps({
        "error": "Insufficient gas",
        "status": "failure"
    })

    tx = TransactionBuilder(sender="0xtest", gas_budget=10_000_000)
    result = tx._parse_execution_result(error_response)

    print(f"Response parseado (com erro):")
    print(f"  Success: {result['success']}")
    print(f"  Error: {result.get('error', 'N/A')}\n")

    checks = {
        "✅ Success = False": result['success'] == False,
        "✅ Erro extraído": result.get('error') == "Insufficient gas",
    }

    all_pass = all(checks.values())
    for check, result_val in checks.items():
        print(f"  {check if result_val else check.replace('✅', '❌')}")

    return all_pass


def test_fallback_parsing():
    """Teste 4: Validar fallback para parsing de texto"""
    print("\n" + "="*80)
    print("TESTE 4: Fallback Parsing de Texto Formatado")
    print("="*80 + "\n")

    text_response = """
Transaction Digest: XYZ789ABC123
Status: Success
Gas Used: 2,500,000
"""

    tx = TransactionBuilder(sender="0xtest", gas_budget=10_000_000)
    result = tx._parse_execution_result(text_response)

    print(f"Response parseado (texto):")
    print(f"  Success: {result['success']}")
    print(f"  Digest: {result.get('digest', 'N/A')}")
    print(f"  Gas Used: {result.get('gas_used', 'N/A')}\n")

    checks = {
        "✅ Success = True": result['success'] == True,
        "✅ Digest extraído": result.get('digest') == "XYZ789ABC123",
        "✅ Gas parseado": result.get('gas_used') == 2500000,
    }

    all_pass = all(checks.values())
    for check, result_val in checks.items():
        print(f"  {check if result_val else check.replace('✅', '❌')}")

    return all_pass


def main():
    print("\n")
    print("╔" + "="*78 + "╗")
    print("║" + " "*78 + "║")
    print("║" + "  🧪 TESTE COMPLETO: Transferências Automáticas IOTA v2".center(78) + "║")
    print("║" + " "*78 + "║")
    print("╚" + "="*78 + "╝")

    results = {
        "Geração de comando PTB": test_command_generation(),
        "Parsing JSON sucesso": test_json_parsing(),
        "Parsing JSON erro": test_json_error_parsing(),
        "Parsing texto fallback": test_fallback_parsing(),
    }

    print("\n" + "="*80)
    print("📊 RESULTADO GERAL")
    print("="*80 + "\n")

    for test_name, passed in results.items():
        status = "✅ PASSOU" if passed else "❌ FALHOU"
        print(f"  {status} - {test_name}")

    all_passed = all(results.values())

    print("\n" + "="*80)
    if all_passed:
        print("✅ TODOS OS TESTES PASSARAM! ✅")
        print("\nA solução está pronta para usar:")
        print("  sudo PYTHONPATH=\"$(pwd)\" /opt/fogbed/venv/bin/python3 examples/04_auto_transfer_network.py")
    else:
        print("❌ Alguns testes falharam. Verifique a implementação.")
    print("="*80 + "\n")

    return 0 if all_passed else 1


if __name__ == "__main__":
    exit(main())
