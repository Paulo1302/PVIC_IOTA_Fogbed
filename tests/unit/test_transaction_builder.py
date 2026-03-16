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
