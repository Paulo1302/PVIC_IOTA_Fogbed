import pytest

from fogbed_iota.client.transaction import TransactionBuilder


def test_transfer_iota_build_cli_command():
    sender = "0xSENDER"
    recipients = ["0xREC1", "0xREC2"]
    amounts = [100, 200]
    tx = TransactionBuilder(sender)
    tx.transfer_iota(recipients, amounts)
    cmd = tx.build_cli_command()
    assert "--split-coins gas '[100,200]'" in cmd
    assert "--transfer-objects '[result:0]'" in cmd
    assert "--transfer-objects '[result:1]'" in cmd
    assert f"--sender {sender}" in cmd


def test_parse_execution_result_success():
    tb = TransactionBuilder("0xS")
    out = "Some output\nTransaction Digest: ABC123\nStatus : Success\nGas Used: 12345\n"
    parsed = tb._parse_execution_result(out)
    assert parsed["success"] is True
    assert parsed["digest"] == "ABC123"
    assert parsed["gas_used"] == 12345


def test_parse_dry_run_result():
    tb = TransactionBuilder("0xS")
    out = "Estimated Gas: 5678\nSome other info\n"
    parsed = tb._parse_dry_run_result(out)
    assert parsed["success"] is True
    assert parsed["estimated_gas"] == 5678


def test_split_and_merge_respect_target_coin():
    tx = TransactionBuilder("0xSENDER")
    tx.split_coins([11, 22], coin_id="0xCOIN")
    tx.merge_coins(["0xA", "0xB"], into_coin="0xTARGET")
    cmd = tx.build_cli_command()

    assert "--split-coins 0xCOIN '[11,22]'" in cmd
    assert "--merge-coins 0xTARGET '[0xA,0xB]'" in cmd


def test_parse_execution_result_success_with_error_word_in_log_line():
    tb = TransactionBuilder("0xS")
    out = (
        "2026-03-16T00:00:00Z INFO iota: starting\n"
        "2026-03-16T00:00:01Z ERROR iota: transient telemetry log\n"
        "Transaction Digest: ABC999\n"
        "Status : Success\n"
    )
    parsed = tb._parse_execution_result(out)
    assert parsed["success"] is True
    assert parsed["digest"] == "ABC999"


def test_parse_dry_run_json_gas_used():
    tb = TransactionBuilder("0xS")
    out = (
        '{"effects":{"gasUsed":{"computationCost":"100",'
        '"storageCost":"40","storageRebate":"10"}}}'
    )
    parsed = tb._parse_dry_run_result(out)
    assert parsed["success"] is True
    assert parsed["estimated_gas"] == 130
