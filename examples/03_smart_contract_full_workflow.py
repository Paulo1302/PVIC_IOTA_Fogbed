#!/usr/bin/env python3
"""
Exemplo 3: Workflow completo de smart contracts com IOTA 1.15

Corrigido para:
- limpar containers/rede antes e depois da execucao
- derrubar ambiente automaticamente em qualquer erro
- evitar looping com mn.* sobrando
- corrigir contrato Move truncado/invalido
- usar fallback raw quando o wrapper do CLI retorna {}
- passar sender explicitamente nas chamadas de contrato
- abortar cedo se a rede subir de forma inconsistente
"""

import atexit
import json
import logging
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from fogbed import Container, FogbedExperiment
from fogbed_iota import IotaNetwork
from fogbed_iota.client.cli import IotaCLI


logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

NETWORK_STABILIZATION_TIME = 45
CLIENT_IP = "10.0.0.100"
GATEWAY_IP = "10.0.0.5"

PACKAGE_HOST_DIR = Path("contracts/counter")
PACKAGE_CONTAINER_DIR = "/contracts/counter"

MOVE_TOML = """[package]
name = "counter"
version = "0.1.0"
edition = "2024.beta"

[dependencies]
Iota = { git = "https://github.com/iotaledger/iota.git", subdir = "crates/iota-framework/packages/iota-framework", rev = "framework/mainnet" }

[addresses]
counter = "0x0"
"""

COUNTER_MOVE = """module counter::counter {
    use iota::event;
    use iota::object::{Self, ID, UID};
    use iota::transfer;
    use iota::tx_context::{Self, TxContext};

    public struct CounterCreated has copy, drop {
        counter_id: ID,
        owner: address,
    }

    public struct CounterIncremented has copy, drop {
        counter_id: ID,
        new_value: u64,
    }

    public struct CounterReset has copy, drop {
        counter_id: ID,
    }

    public struct AdminCap has key, store {
        id: UID,
    }

    public struct Counter has key, store {
        id: UID,
        value: u64,
    }

    fun init(ctx: &mut TxContext) {
        transfer::transfer(
            AdminCap { id: object::new(ctx) },
            tx_context::sender(ctx),
        );
    }

    public entry fun create(ctx: &mut TxContext) {
        let counter = Counter {
            id: object::new(ctx),
            value: 0,
        };

        event::emit(CounterCreated {
            counter_id: object::id(&counter),
            owner: tx_context::sender(ctx),
        });

        transfer::share_object(counter);
    }

    public entry fun increment(counter: &mut Counter) {
        counter.value = counter.value + 1;

        event::emit(CounterIncremented {
            counter_id: object::id(counter),
            new_value: counter.value,
        });
    }

    public entry fun reset(counter: &mut Counter, _cap: &AdminCap) {
        counter.value = 0;

        event::emit(CounterReset {
            counter_id: object::id(counter),
        });
    }

    public fun get_value(counter: &Counter): u64 {
        counter.value
    }
}
"""


class WorkflowGuard:
    def __init__(self) -> None:
        self.exp: Optional[FogbedExperiment] = None
        self.cleaned = False

    def attach_experiment(self, exp: FogbedExperiment) -> None:
        self.exp = exp

    def _run(self, cmd: str) -> None:
        try:
            subprocess.run(
                cmd,
                shell=True,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    def cleanup(self, reason: str = "unknown") -> None:
        if self.cleaned:
            return
        self.cleaned = True

        print(f"\n[cleanup] iniciando cleanup ({reason})...")

        if self.exp is not None:
            try:
                self.exp.stop()
            except Exception as exc:
                print(f"[cleanup] exp.stop() falhou: {exc}")

        cmds = [
            r"docker ps -aq --filter 'name=^mn\.' | xargs -r docker rm -f",
            r"pkill -9 -f 'mininet:' || true",
            r"pkill -9 -f 'mnexec' || true",
            r"sudo mn -c || true",
        ]

        for cmd in cmds:
            self._run(cmd)

        print("[cleanup] finalizado.")

    def preflight_cleanup(self) -> None:
        self.cleaned = False
        self.cleanup("preflight")
        self.cleaned = False


guard = WorkflowGuard()


def _handle_signal(signum, frame) -> None:
    guard.cleanup(f"signal {signum}")
    raise SystemExit(128 + signum)


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)
atexit.register(lambda: guard.cleanup("atexit"))


def print_header(title: str) -> None:
    print("\n" + "=" * 70)
    print(title.center(70))
    print("=" * 70 + "\n")


def print_step(step_num: int, description: str) -> None:
    print("\n" + "─" * 70)
    print(f"STEP {step_num}: {description}")
    print("─" * 70 + "\n")


def format_balance(mist: int) -> str:
    iota = mist / 1_000_000_000
    return f"{mist:,} MIST ({iota:.4f} IOTA)"


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1B\[[0-?]*[ -/]*[@-~]", "", text or "")


def extract_json_from_output(output: str) -> dict[str, Any]:
    output_clean = strip_ansi(output)

    clean_lines = []
    for line in output_clean.splitlines():
        stripped = line.strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}T", stripped):
            continue
        if stripped.startswith(("[note]", "FETCHING", "Cloning", "Updating", "Compiling")):
            continue
        clean_lines.append(line)

    output_clean = "\n".join(clean_lines).strip()

    if output_clean.startswith("{") or output_clean.startswith("["):
        try:
            data = json.loads(output_clean)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    decoder = json.JSONDecoder()
    for pos, ch in enumerate(output_clean):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(output_clean, pos)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue

    raise ValueError(f"Nenhum JSON valido encontrado. Preview:\n{output_clean[:800]}")


def tx_digest(tx: dict[str, Any]) -> str:
    effects = tx.get("effects") or {}
    return tx.get("digest") or effects.get("transactionDigest") or "N/A"


def tx_error_message(tx: dict[str, Any]) -> str:
    effects = tx.get("effects") or {}
    status = effects.get("status") or {}
    if isinstance(status, dict) and status.get("error"):
        return str(status["error"])
    if tx.get("error"):
        return str(tx["error"])
    return str(tx)


def tx_looks_successful(tx: dict[str, Any]) -> bool:
    if not isinstance(tx, dict) or not tx:
        return False

    effects = tx.get("effects") or {}
    status = effects.get("status") or {}
    top_status = tx.get("status")
    error_msg = tx.get("error")

    if isinstance(status, dict):
        effects_status = status.get("status")
        error_msg = error_msg or status.get("error")
    else:
        effects_status = str(status) if status else ""

    digest = tx.get("digest") or effects.get("transactionDigest")

    return any([
        top_status == "success",
        effects_status == "success",
        bool(tx.get("confirmedLocalExecution")),
        "objectChanges" in tx,
        "balanceChanges" in tx,
        bool(digest) and not error_msg,
    ])


def extract_first_address(text: str) -> Optional[str]:
    match = re.search(r"(0x[a-fA-F0-9]{64})", text or "")
    return match.group(1) if match else None


def assert_client_network_ready(client_container) -> None:
    ip_output = client_container.cmd("ip -4 addr show 2>/dev/null || true")
    if CLIENT_IP not in ip_output:
        raise RuntimeError(
            f"Rede inconsistente: container client nao recebeu o IP esperado {CLIENT_IP}.\n"
            f"Saida:\n{ip_output}"
        )

    ping_output = client_container.cmd(
        f"ping -c 1 -W 3 {GATEWAY_IP} >/dev/null 2>&1 && echo OK || echo FAIL"
    )
    if "OK" not in ping_output:
        raise RuntimeError(
            f"Rede inconsistente: client nao alcança gateway {GATEWAY_IP}."
        )


def get_funder_address(client_container) -> str:
    logger.info("Descobrindo funder address do genesis keystore...")

    raw = client_container.cmd(
        "iota client --client.config /app/config/client.yaml addresses --json 2>/dev/null"
    )

    try:
        data = json.loads(strip_ansi(raw))
        if isinstance(data, dict):
            active = data.get("activeAddress") or data.get("active_address")
            if isinstance(active, str) and active.startswith("0x"):
                return active

            addresses = data.get("addresses", [])
            if addresses:
                first = addresses[0]
                candidate = first[1] if isinstance(first, list) and len(first) > 1 else first
                if isinstance(candidate, str) and candidate.startswith("0x"):
                    return candidate

        if isinstance(data, list) and data:
            candidate = data[0] if isinstance(data[0], str) else str(data[0])
            if candidate.startswith("0x"):
                return candidate
    except Exception:
        pass

    for cmd in [
        "iota client --client.config /app/config/client.yaml addresses 2>/dev/null",
        "iota client --client.config /app/config/client.yaml active-address 2>/dev/null",
    ]:
        out = client_container.cmd(cmd)
        candidate = extract_first_address(out)
        if candidate:
            return candidate

    raise RuntimeError(
        "Nao foi possivel descobrir o funder address. "
        "Verifique o client.yaml e o keystore copiado para o container."
    )


def check_account_balance(client_container, address: str) -> int:
    cli = IotaCLI(client_container, network="localnet")
    try:
        coins = cli.get_gas(address)
        return sum(int(c.get("balance", 0)) for c in coins)
    except Exception as exc:
        logger.warning(f"Falha ao consultar saldo de {address}: {exc}")
        return 0


def safe_ptb_transfer(
    client_container,
    sender: str,
    recipient: str,
    amount_mist: int,
    gas_budget: int = 50_000_000,
) -> dict[str, Any]:
    cmd = (
        "iota client ptb"
        f" --split-coins gas '[{amount_mist}]'"
        " --assign coins"
        f" --transfer-objects '[coins.0]' @{recipient}"
        f" --sender @{sender}"
        f" --gas-budget {gas_budget}"
        " --json 2>&1"
    )

    raw = client_container.cmd(cmd)
    tx = extract_json_from_output(raw)

    if not tx_looks_successful(tx):
        raise RuntimeError(f"Transferencia falhou: {tx_error_message(tx)}")

    return tx


def fund_accounts_via_transfer(client_container, accounts: list, funder_address: str) -> int:
    print("Financiando contas via genesis transfer...\n")
    amount_mist = 400_000_000
    funded_count = 0
    account_names = ["Alice", "Bob", "Charlie", "Dave"]

    for i, account in enumerate(accounts):
        name = account_names[i] if i < len(account_names) else f"Account{i + 1}"

        if account.address.lower() == funder_address.lower():
            print(f" {name} ja e o funder -- pulando")
            funded_count += 1
            continue

        print(f" Transferindo para {name}...", end="", flush=True)
        try:
            tx = safe_ptb_transfer(
                client_container=client_container,
                sender=funder_address,
                recipient=account.address,
                amount_mist=amount_mist,
                gas_budget=50_000_000,
            )
            time.sleep(2)
            balance = check_account_balance(client_container, account.address)
            print(f" OK {format_balance(balance)} ({tx_digest(tx)})")
            funded_count += 1
        except Exception as exc:
            print(f" Error: {exc}")

    return funded_count


def create_contract_files_on_host() -> None:
    PACKAGE_HOST_DIR.joinpath("sources").mkdir(parents=True, exist_ok=True)
    PACKAGE_HOST_DIR.joinpath("Move.toml").write_text(MOVE_TOML, encoding="utf-8")
    PACKAGE_HOST_DIR.joinpath("sources/counter.move").write_text(COUNTER_MOVE, encoding="utf-8")

    print("Arquivos criados no host:")
    print(f" - {PACKAGE_HOST_DIR / 'Move.toml'}")
    print(f" - {PACKAGE_HOST_DIR / 'sources/counter.move'}")


def create_contract_files_in_container(client_container) -> bool:
    client_container.cmd("mkdir -p /contracts/counter/sources")
    client_container.cmd("cat > /contracts/counter/Move.toml <<'EOF'\n" + MOVE_TOML + "\nEOF")
    client_container.cmd(
        "cat > /contracts/counter/sources/counter.move <<'EOF'\n" + COUNTER_MOVE + "\nEOF"
    )
    verify = client_container.cmd(
        'test -f /contracts/counter/Move.toml && echo "OK" || echo "FAILED"'
    )
    return "OK" in verify


def safe_call_move_function(
    cli: IotaCLI,
    client_container,
    package_id: str,
    module: str,
    function: str,
    sender: str,
    args: Optional[list[str]] = None,
    type_args: Optional[list[str]] = None,
    gas_budget: int = 10_000_000,
    wrapper_retries: int = 2,
) -> dict[str, Any]:
    args = args or []
    type_args = type_args or []

    last_error: Optional[Exception] = None

    for attempt in range(1, wrapper_retries + 1):
        try:
            result = cli.call_function(
                package=package_id,
                module=module,
                function=function,
                args=args,
                type_args=type_args,
                gas_budget=gas_budget,
                sender=sender,
            ) or {}

            if tx_looks_successful(result):
                return result

            logger.warning(
                "call_function wrapper retornou payload vazio/incompleto "
                f"(tentativa {attempt}/{wrapper_retries}): {result}"
            )
            last_error = RuntimeError(f"Wrapper retornou payload invalido: {result}")
        except Exception as exc:
            logger.warning(
                "call_function wrapper falhou "
                f"(tentativa {attempt}/{wrapper_retries}): {exc}"
            )
            last_error = exc

        time.sleep(2)

    cmd = (
        "iota client call "
        f"--package {shlex.quote(package_id)} "
        f"--module {shlex.quote(module)} "
        f"--function {shlex.quote(function)} "
        f"--sender {shlex.quote(sender)} "
        f"--gas-budget {gas_budget} "
        "--json"
    )

    for targ in type_args:
        cmd += f" --type-args {shlex.quote(targ)}"

    for arg in args:
        cmd += f" --args {shlex.quote(arg)}"

    cmd += " 2>&1"

    logger.warning(
        "Usando fallback raw para chamada Move "
        f"{package_id}::{module}::{function}"
    )

    raw = client_container.cmd(cmd)
    tx = extract_json_from_output(raw)

    if not tx_looks_successful(tx):
        suffix = f" | erro anterior: {last_error}" if last_error else ""
        raise RuntimeError(f"Transaction failed: {tx_error_message(tx)}{suffix}")

    return tx


def find_counter_from_create_result(cli: IotaCLI, create_result: dict, owner_address: str | None = None) -> tuple[str | None, str | None]:
    def is_counter_type(text: str) -> bool:
        return "counter::counter::Counter" in text or "counter::Counter" in text

    # 1) objectChanges
    for change in create_result.get("objectChanges", []) or []:
        object_type = str(change.get("objectType", "") or "")
        if is_counter_type(object_type):
            obj_id = change.get("objectId") or change.get("object_id")
            version = change.get("initialSharedVersion") or change.get("version")
            if obj_id:
                return obj_id, str(version) if version is not None else None

    # 2) effects.created / effects.mutated
    effects = create_result.get("effects", {}) or {}
    for bucket_name in ("created", "mutated"):
        for item in effects.get(bucket_name, []) or []:
            ref = item.get("reference", {}) or {}
            obj_id = (
                item.get("objectId")
                or item.get("object_id")
                or ref.get("objectId")
                or ref.get("object_id")
            )
            if not obj_id:
                continue
            try:
                details = cli.get_object(obj_id)
                details_str = json.dumps(details, default=str)
                if is_counter_type(details_str):
                    shared_version = None
                    owner = details.get("owner") if isinstance(details, dict) else None
                    if isinstance(owner, dict):
                        shared = owner.get("Shared") or owner.get("shared")
                        if isinstance(shared, dict):
                            shared_version = shared.get("initial_shared_version") or shared.get("initialSharedVersion")
                    return obj_id, str(shared_version) if shared_version is not None else None
            except Exception:
                continue

    # 3) procurar qualquer object id citado no payload bruto
    payload_text = json.dumps(create_result, default=str)
    candidate_ids = set(re.findall(r"0x[a-fA-F0-9]{64}", payload_text))
    for obj_id in candidate_ids:
        try:
            details = cli.get_object(obj_id)
            details_str = json.dumps(details, default=str)
            if is_counter_type(details_str):
                shared_version = None
                owner = details.get("owner") if isinstance(details, dict) else None
                if isinstance(owner, dict):
                    shared = owner.get("Shared") or owner.get("shared")
                    if isinstance(shared, dict):
                        shared_version = shared.get("initial_shared_version") or shared.get("initialSharedVersion")
                return obj_id, str(shared_version) if shared_version is not None else None
        except Exception:
            continue

    # 4) fallback: listar objetos do owner e inspecionar
    if owner_address:
        try:
            owned = cli.get_objects(owner_address)
            for item in owned or []:
                obj_id = item.get("objectId") or item.get("object_id") or item.get("objectId")
                if not obj_id:
                    continue
                try:
                    details = cli.get_object(obj_id)
                    details_str = json.dumps(details, default=str)
                    if is_counter_type(details_str):
                        return obj_id, None
                except Exception:
                    continue
        except Exception:
            pass

    return None, None


def wait_for_counter_object(cli: IotaCLI, create_result: dict[str, Any], retries: int = 8) -> tuple[Optional[str], Optional[str]]:
    for _ in range(retries):
        counter_id, shared_version = find_counter_from_create_result(cli, create_result)
        if counter_id:
            return counter_id, shared_version
        time.sleep(2)
    return None, None

def assert_address_in_cli_keystore(client_container, address: str) -> None:
    raw = client_container.cmd(
        "iota client --client.config /app/config/client.yaml addresses --json 2>/dev/null"
    )

    try:
        data = json.loads(raw)
    except Exception:
        data = None

    found = False

    if isinstance(data, dict):
        active = data.get("activeAddress") or data.get("active_address")
        if active == address:
            found = True

        for item in data.get("addresses", []) or []:
            if isinstance(item, list) and len(item) > 1 and item[1] == address:
                found = True
            elif item == address:
                found = True

    elif isinstance(data, list):
        for item in data:
            if item == address:
                found = True
            elif isinstance(item, list) and len(item) > 1 and item[1] == address:
                found = True

    if not found:
        text_out = client_container.cmd(
            "iota client --client.config /app/config/client.yaml addresses 2>/dev/null"
        )
        if address not in text_out:
            raise RuntimeError(
                f"Endereco {address} nao esta no keystore do iota client dentro do container."
            )

def main() -> None:
    success = False
    exp: Optional[FogbedExperiment] = None

    guard.preflight_cleanup()

    

    try:
        print_header("IOTA Smart Contract Workflow - Move 2024")

        print_step(1, "Network Setup")
        exp = FogbedExperiment()
        guard.attach_experiment(exp)

        iota_net = IotaNetwork(exp, image="iota-dev:latest")
        iota_net.add_validator("iota1", "10.0.0.1")
        iota_net.add_validator("iota2", "10.0.0.2")
        iota_net.add_validator("iota3", "10.0.0.3")
        iota_net.add_validator("iota4", "10.0.0.4")
        iota_net.add_gateway("gateway", "10.0.0.5")

        client = Container(
            name="client",
            ip=CLIENT_IP,
            dimage="iota-dev:latest",
            dcmd="tail -f /dev/null",
        )

        iota_net.set_client(client)
        iota_net.attach_to_experiment()

        exp.start()
        iota_net.start()

        print(f"Aguardando estabilizacao da rede ({NETWORK_STABILIZATION_TIME}s)...")
        time.sleep(NETWORK_STABILIZATION_TIME)

        assert_client_network_ready(client)

        print_step(2, "Initialize CLI Tools and Managers")
        cli = IotaCLI(client, network="localnet")
        acct_mgr = iota_net.account_manager
        contract_mgr = iota_net.contract_manager

        gas_price = cli.get_reference_gas_price()
        print(f"Reference gas price: {gas_price} MIST")

        print_step(3, "Discover Genesis Funder Address")
        funder_address = get_funder_address(client)
        print(f"Funder address: {funder_address}")

        funder_balance = check_account_balance(client, funder_address)
        print(f"Funder balance: {format_balance(funder_balance)}")

        print_step(4, "Account Management")
        alice = acct_mgr.generate_account("alice")
        bob = acct_mgr.generate_account("bob")

        print(f"Alice: {alice.address}")
        print(f"Bob:   {bob.address}")

        assert_address_in_cli_keystore(client, alice.address)
        assert_address_in_cli_keystore(client, bob.address)

        print("Keystore do client confirmou Alice e Bob.")

        print_step(5, "Funding Accounts via Genesis Transfer")
        alice_balance = check_account_balance(client, alice.address)
        bob_balance = check_account_balance(client, bob.address)

        print(f"  Alice: {format_balance(alice_balance)}")
        print(f"  Bob:   {format_balance(bob_balance)}")

        if alice_balance < 100_000_000 or bob_balance < 100_000_000:
            funded = fund_accounts_via_transfer(client, [alice, bob], funder_address)
            print(f"\n{funded}/2 contas financiadas")
            time.sleep(2)

            alice_balance = check_account_balance(client, alice.address)
            bob_balance = check_account_balance(client, bob.address)

            print(f"  Alice: {format_balance(alice_balance)}")
            print(f"  Bob:   {format_balance(bob_balance)}")

        if alice_balance < 100_000_000:
            raise RuntimeError("Alice nao possui saldo suficiente para publicar/chamar o contrato.")

        print_step(6, "Prepare Smart Contract")
        create_contract_files_on_host()

        print("\nCopiando pacote para o container...")
        contract_mgr.copy_package_to_container(str(PACKAGE_HOST_DIR), "counter", debug=True)

        verify = client.cmd('test -f /contracts/counter/Move.toml && echo "OK" || echo "FAILED"')
        if "FAILED" in verify or "OK" not in verify:
            print("Copia via tar falhou -- usando fallback direto no container...")
            if not create_contract_files_in_container(client):
                raise RuntimeError("Fallback tambem falhou ao recriar o pacote no container.")
            print("Fallback bem-sucedido!")
        else:
            print("Copia verificada com sucesso!")

        print("\nArquivos no container:")
        print(client.cmd("ls -la /contracts/counter/ && ls -la /contracts/counter/sources/"))

        print("\nCompilando contrato...")
        build_result = contract_mgr.build_package(PACKAGE_CONTAINER_DIR, debug=True)
        print(f"Compilado: {', '.join(build_result['modules'])}")

        print_step(7, "Deploy Smart Contract")
        print("Publicando com Alice (alias registrado e financiado)...")
        # DICA: O SmartContractManager lida internamente com toda a abstração de
        # ler o JSON de output, extrair o Package ID, os Módulos e o Upgrade Cap!
        package = contract_mgr.publish_package(
            package_path=PACKAGE_CONTAINER_DIR,
            sender_alias="alice",
            gas_budget=100_000_000,
        )

        package_id = package.package_id

        print("Package publicado!")
        print(f" Package ID: {package_id}")
        print(f" Transaction: {package.digest}")
        print(f" Modules: {', '.join(package.modules)}")
        if package.upgrade_cap_id:
            print(f" UpgradeCap: {package.upgrade_cap_id}")

        print_step(8, "Create Counter Object")
        create_result = contract_mgr.call_function(
            package_id=package_id,
            module="counter",
            function="create",
            sender_alias="alice",
            gas_budget=10_000_000,
        )

        digest = create_result.get("digest") or ((create_result.get("effects") or {}).get("transactionDigest")) or "N/A"
        print(f"Counter criado! Digest: {digest}")

        counter_id, shared_version = find_counter_from_create_result(cli, create_result, owner_address=alice.address)

        if not counter_id:
            print("DEBUG create_result full:")
            print(json.dumps(create_result, indent=2, default=str)[:12000])
            raise RuntimeError("Counter nao foi localizado automaticamente apos o create().")

        print(f"Counter ID: {counter_id}")
        print(f"Shared version: {shared_version}")

        print_step(9, "Interact with Counter")
        print("Incrementando counter (3x) com Alice...")

        for i in range(3):
            result = safe_call_move_function(
                cli=cli,
                client_container=client,
                package_id=package_id,
                module="counter",
                function="increment",
                sender=alice.address,
                args=[counter_id],
                gas_budget=10_000_000,
            )
            print(f" Increment {i + 1}: {tx_digest(result)}")
            time.sleep(2)

        print_step(10, "Transfer Alice -> Bob via PTB")
        alice_balance = check_account_balance(client, alice.address)
        bob_balance = check_account_balance(client, bob.address)

        gas_budget = 10_000_000
        safety_margin = 20_000_000
        transfer_amount = min(100_000_000, max(0, alice_balance - gas_budget - safety_margin))

        print(f"Transferindo {transfer_amount:,} MIST de Alice para Bob...")

        if transfer_amount > 0:
            result = safe_ptb_transfer(
                client_container=client,
                sender=alice.address,
                recipient=bob.address,
                amount_mist=transfer_amount,
                gas_budget=10_000_000,
            )
            print(f"Transferencia concluida: {tx_digest(result)}")
        else:
            print("Transferencia pulada: saldo insuficiente apos reservar gas.")

        time.sleep(3)
        alice_balance = check_account_balance(client, alice.address)
        bob_balance = check_account_balance(client, bob.address)

        print(f" Alice: {format_balance(alice_balance)}")
        print(f" Bob:   {format_balance(bob_balance)}")

        print_step(11, "Workflow Complete")
        print("Resumo:")
        print(" Rede: 4 validators + 1 gateway")
        print(f" Funder: {funder_address[:20]}...")
        print(" Contas: Alice & Bob")
        print(f" Package: {package_id}")
        print(f" Counter: {counter_id}")
        print(" Transfer: Alice -> Bob")
        print("\nWorkflow concluido com sucesso!")
        print("\nRede ainda ativa. Voce pode:")
        print(" docker exec -it mn.client bash")
        print(" iota client objects")
        print("\nPressione ENTER para encerrar a rede...")
        input()

        success = True

    finally:
        guard.cleanup("success" if success else "error")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrompido pelo usuario")
        raise
    except Exception as exc:
        print(f"\nErro: {exc}")
        traceback.print_exc()
        raise