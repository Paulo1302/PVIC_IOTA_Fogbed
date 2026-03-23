#!/usr/bin/env python3
"""
test_transaction_fix.py

Teste para validar se o TransactionBuilder está gerando o comando correto
com as correções implementadas.

Uso:
    python3 test_transaction_fix.py
"""

from fogbed_iota.client.transaction import TransactionBuilder


def test_transfer_iota_command_generation():
    """Testa se o comando PTB é gerado corretamente"""

    print("\n" + "="*80)
    print("🧪 TESTE: Validação do Comando PTB")
    print("="*80 + "\n")

    # Dados de teste
    sender = "0x5d7e08e992c370d541774b77a8dd0e1f7047a757c047ae19733a4d3975ef9e33"
    recipient = "0xeb60e26e1ce4b82a5371ed67bdc192fb26cf5c2b6175c410d0878266e657ae41"
    amount = 100_000

    print(f"📝 Parâmetros:")
    print(f"   Sender:    {sender[:16]}...")
    print(f"   Recipient: {recipient[:16]}...")
    print(f"   Amount:    {amount} MIST\n")

    # Criar e executar TransactionBuilder
    tx = TransactionBuilder(sender=sender, gas_budget=10_000_000)
    tx.transfer_iota([recipient], [amount])

    cmd = tx.build_cli_command()

    print("📋 Comando Gerado:")
    print("-" * 80)
    print(cmd)
    print("-" * 80 + "\n")

    # Validações
    checks = {
        "✅ Tem 'iota client ptb'": cmd.startswith("iota client ptb"),
        "✅ Tem '--split-coins gas'": "--split-coins gas" in cmd,
        "✅ Tem '--transfer-objects'": "--transfer-objects" in cmd,
        "✅ Tem '--sender @'": "--sender @" in cmd,
        "✅ Tem '--gas-budget'": "--gas-budget" in cmd,
        "✅ Tem '--json'": "--json" in cmd,
        "✅ Sender com @ prefix": f"@{sender}" in cmd,
        "✅ Recipient com @ prefix": f"@{recipient}" in cmd,
    }

    print("🔍 Validações:")
    all_passed = True
    for check, result in checks.items():
        status = "✅" if result else "❌"
        print(f"   {status} {check}")
        if not result:
            all_passed = False

    print("\n" + "="*80)
    if all_passed:
        print("✅ TODOS OS TESTES PASSARAM!")
        print("="*80)
        print("\n🚀 O TransactionBuilder está gerando comandos corretos.")
        print("   Você pode agora executar o exemplo 04 com segurança:\n")
        print("   sudo PYTHONPATH=\"$(pwd)\" /opt/fogbed/venv/bin/python3 examples/04_auto_transfer_network.py\n")
        return True
    else:
        print("❌ ALGUM TESTE FALHOU!")
        print("="*80)
        return False


def test_recipient_prefix():
    """Testa adição de @ ao recipient"""

    print("\n" + "="*80)
    print("🧪 TESTE: Prefixo @ no Recipient")
    print("="*80 + "\n")

    sender = "0xabc123"
    recipient = "0xdef456"

    tx = TransactionBuilder(sender=sender, gas_budget=10_000_000)
    tx.transfer_iota([recipient], [50_000])

    cmd = tx.build_cli_command()

    # Verificar se recipient tem @
    if f"@{recipient}" in cmd:
        print(f"✅ Recipient corretamente prefixado: @{recipient}")
        return True
    else:
        print(f"❌ Recipient NOT prefixado corretamente")
        print(f"   Procurando por: @{recipient}")
        print(f"   Comando: {cmd}")
        return False


def test_sender_prefix():
    """Testa adição de @ ao sender"""

    print("\n" + "="*80)
    print("🧪 TESTE: Prefixo @ no Sender")
    print("="*80 + "\n")

    sender = "0xabc123"
    recipient = "0xdef456"

    tx = TransactionBuilder(sender=sender, gas_budget=10_000_000)
    tx.transfer_iota([recipient], [50_000])

    cmd = tx.build_cli_command()

    # Verificar se sender tem @ no flag --sender
    if f"--sender @{sender}" in cmd:
        print(f"✅ Sender corretamente prefixado: --sender @{sender}")
        return True
    else:
        print(f"❌ Sender NOT prefixado corretamente")
        print(f"   Procurando por: --sender @{sender}")
        print(f"   Comando: {cmd}")
        return False


def main():
    print("\n")
    print("╔" + "="*78 + "╗")
    print("║" + " "*78 + "║")
    print("║" + "  🧪 TESTE DE VALIDAÇÃO: TransactionBuilder PTB Command Generation".center(78) + "║")
    print("║" + " "*78 + "║")
    print("╚" + "="*78 + "╝")

    test1 = test_transfer_iota_command_generation()
    test2 = test_recipient_prefix()
    test3 = test_sender_prefix()

    print("\n" + "="*80)
    print("📊 RESULTADO GERAL")
    print("="*80)

    if test1 and test2 and test3:
        print("\n✅ TODOS OS TESTES PASSARAM! ✅")
        print("\nA correção foi implementada com sucesso.")
        print("TransactionBuilder está gerando comandos PTB válidos.")
        print("\nPróximo passo: Executar exemplo 04 completo\n")
        return 0
    else:
        print("\n❌ Alguns testes falharam. Verifique a implementação.\n")
        return 1


if __name__ == "__main__":
    exit(main())
