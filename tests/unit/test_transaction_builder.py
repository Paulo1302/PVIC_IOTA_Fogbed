from fogbed_iota.client.transaction import TransactionBuilder


def test_transfer_iota_build_cli_command():
    sender = "0xSENDER"
    recipients = ["0xREC1", "0xREC2"]
    amounts = [100, 200]
    tx = TransactionBuilder(sender)
    tx.transfer_iota(recipients, amounts)
    cmd = tx.build_cli_command()
    assert "--split-coins gas '[100,200]'" in cmd
    assert "--assign coins" in cmd
    assert "--transfer-objects '[coins.0]'" in cmd
    assert "--transfer-objects '[coins.1]'" in cmd
    assert f"--sender @{sender}" in cmd


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


def test_parse_execution_result_json_success_with_log_prefix():
    tb = TransactionBuilder("0xS")
    out = (
        "2026-03-23T20:05:02.826180Z DEBUG iota::client_commands: Transaction executed\n"
        "{\n"
        "  \"digest\": \"5Jd8bKWB3vayghHYcNzkYYmYogc6rZBa4AjLZadNkMMC\",\n"
        "  \"effects\": {\n"
        "    \"status\": {\"status\": \"success\", \"error\": null},\n"
        "    \"gasUsed\": {\"computationCost\": \"1000000\", \"storageCost\": \"1960800\", \"storageRebate\": \"980400\"},\n"
        "    \"transactionDigest\": \"5Jd8bKWB3vayghHYcNzkYYmYogc6rZBa4AjLZadNkMMC\"\n"
        "  },\n"
        "  \"confirmedLocalExecution\": true\n"
        "}\n"
    )
    parsed = tb._parse_execution_result(out)
    assert parsed["success"] is True
    assert parsed["digest"] == "5Jd8bKWB3vayghHYcNzkYYmYogc6rZBa4AjLZadNkMMC"
    assert parsed["gas_used"] == 1980400


def test_parse_execution_result_json_failure_with_explicit_error():
    tb = TransactionBuilder("0xS")
    out = (
        "{\n"
        "  \"error\": \"Cannot find key for address: [0xabc]\",\n"
        "  \"effects\": {\"status\": {\"status\": \"failure\"}}\n"
        "}\n"
    )
    parsed = tb._parse_execution_result(out)
    assert parsed["success"] is False
    assert "Cannot find key" in parsed["error"]


def test_parse_dry_run_json_gas_used():
    tb = TransactionBuilder("0xS")
    out = (
        '{"effects":{"gasUsed":{"computationCost":"100",'
        '"storageCost":"40","storageRebate":"10"}}}'
    )
    parsed = tb._parse_dry_run_result(out)
    assert parsed["success"] is True
    assert parsed["estimated_gas"] == 130
