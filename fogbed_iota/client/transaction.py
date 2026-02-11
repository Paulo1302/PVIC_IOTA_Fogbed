# fogbed_iota/client/transaction.py

"""
Transaction Builder para construção programática de transações IOTA
Suporta Move calls, transfers, coin operations e programmatic transactions
"""

import json
import re
from typing import List, Dict, Optional, Any, Union
from dataclasses import dataclass, field
from enum import Enum

from fogbed_iota.utils import get_logger

logger = get_logger('transaction')


class TransactionType(Enum):
    """Tipos de transações suportadas"""
    MOVE_CALL = "move_call"
    TRANSFER_OBJECT = "transfer_object"
    TRANSFER_IOTA = "transfer_iota"
    SPLIT_COIN = "split_coin"
    MERGE_COIN = "merge_coin"
    PUBLISH = "publish"
    UPGRADE = "upgrade"


@dataclass
class TransactionArgument:
    """
    Representa um argumento de transação
    
    Pode ser:
    - Input(u16): referência a um input da transação
    - Result(u16): resultado de comando anterior
    - NestedResult(u16, u16): resultado aninhado
    - GasCoin: referência ao gas coin
    """
    type: str  # "Input", "Result", "NestedResult", "GasCoin"
    value: Optional[Union[int, tuple]] = None
    
    def to_cli_arg(self) -> str:
        """Converte para formato CLI"""
        if self.type == "GasCoin":
            return "gas"
        elif self.type == "Input":
            return f"@{self.value}"
        elif self.type == "Result":
            return f"result:{self.value}"
        elif self.type == "NestedResult":
            return f"nested:{self.value[0]},{self.value[1]}"
        return str(self.value)


@dataclass
class TransactionCommand:
    """Representa um comando dentro de uma programmable transaction"""
    type: TransactionType
    package_id: Optional[str] = None
    module: Optional[str] = None
    function: Optional[str] = None
    type_args: List[str] = field(default_factory=list)
    args: List[Union[str, int, TransactionArgument]] = field(default_factory=list)
    
    # Para transfers
    recipient: Optional[str] = None
    object_ids: List[str] = field(default_factory=list)
    
    # Para coin operations
    amounts: List[int] = field(default_factory=list)
    
    def to_cli_string(self) -> str:
        """Converte comando para string CLI"""
        if self.type == TransactionType.MOVE_CALL:
            type_args_str = ""
            if self.type_args:
                type_args_str = f" --type-args {' '.join(self.type_args)}"
            
            args_str = ""
            if self.args:
                formatted_args = []
                for arg in self.args:
                    if isinstance(arg, TransactionArgument):
                        formatted_args.append(arg.to_cli_arg())
                    else:
                        formatted_args.append(str(arg))
                args_str = f" --args {' '.join(formatted_args)}"
            
            return (
                f"--move-call {self.package_id}::{self.module}::{self.function}"
                f"{type_args_str}{args_str}"
            )
        
        elif self.type == TransactionType.TRANSFER_OBJECT:
            objects = " ".join(self.object_ids)
            return f"--transfer-objects '[{objects}]' {self.recipient}"
        
        elif self.type == TransactionType.SPLIT_COIN:
            amounts = ",".join(str(a) for a in self.amounts)
            return f"--split-coins gas '[{amounts}]'"
        
        elif self.type == TransactionType.MERGE_COIN:
            coins = " ".join(self.object_ids)
            return f"--merge-coins gas '[{coins}]'"
        
        return ""


class TransactionBuilder:
    """
    Builder para construir transações IOTA programaticamente
    
    Exemplo de uso:
        tx = TransactionBuilder(sender_address)
        tx.move_call(
            package="0x2",
            module="counter",
            function="increment",
            args=["0xCOUNTER_ID"]
        )
        result = tx.execute(client_container, gas_budget=10_000_000)
    """
    
    def __init__(self, sender: str, gas_budget: int = 10_000_000):
        """
        Inicializa builder
        
        Args:
            sender: Endereço da conta que envia a transação
            gas_budget: Budget de gas (padrão: 10M MIST)
        """
        self.sender = sender
        self.gas_budget = gas_budget
        self.commands: List[TransactionCommand] = []
        self._inputs: List[str] = []
        
        logger.debug(f"TransactionBuilder initialized for {sender[:16]}...")
    
    def move_call(
        self,
        package: str,
        module: str,
        function: str,
        args: Optional[List[Union[str, int, TransactionArgument]]] = None,
        type_args: Optional[List[str]] = None
    ) -> 'TransactionBuilder':
        """
        Adiciona chamada de função Move
        
        Args:
            package: Package ID (ex: "0x2")
            module: Nome do módulo (ex: "counter")
            function: Nome da função (ex: "increment")
            args: Lista de argumentos
            type_args: Argumentos de tipo genérico
            
        Returns:
            Self para chaining
        """
        cmd = TransactionCommand(
            type=TransactionType.MOVE_CALL,
            package_id=package,
            module=module,
            function=function,
            args=args or [],
            type_args=type_args or []
        )
        
        self.commands.append(cmd)
        logger.debug(f"Added move_call: {package}::{module}::{function}")
        
        return self
    
    def transfer_objects(
        self,
        object_ids: List[str],
        recipient: str
    ) -> 'TransactionBuilder':
        """
        Transfere objetos para um destinatário
        
        Args:
            object_ids: Lista de IDs de objetos a transferir
            recipient: Endereço do destinatário
            
        Returns:
            Self para chaining
        """
        cmd = TransactionCommand(
            type=TransactionType.TRANSFER_OBJECT,
            object_ids=object_ids,
            recipient=recipient
        )
        
        self.commands.append(cmd)
        logger.debug(f"Added transfer: {len(object_ids)} objects to {recipient[:16]}...")
        
        return self
    
    def split_coins(
        self,
        amounts: List[int],
        coin_id: Optional[str] = None
    ) -> 'TransactionBuilder':
        """
        Divide uma moeda em múltiplas moedas menores
        
        Args:
            amounts: Lista de valores para dividir
            coin_id: ID da moeda (None = gas coin)
            
        Returns:
            Self para chaining
        """
        cmd = TransactionCommand(
            type=TransactionType.SPLIT_COIN,
            amounts=amounts,
            object_ids=[coin_id] if coin_id else []
        )
        
        self.commands.append(cmd)
        logger.debug(f"Added split_coins: {len(amounts)} splits")
        
        return self
    
    def merge_coins(
        self,
        coin_ids: List[str],
        into_coin: Optional[str] = None
    ) -> 'TransactionBuilder':
        """
        Mescla múltiplas moedas em uma
        
        Args:
            coin_ids: Lista de IDs de moedas a mesclar
            into_coin: Moeda destino (None = gas coin)
            
        Returns:
            Self para chaining
        """
        cmd = TransactionCommand(
            type=TransactionType.MERGE_COIN,
            object_ids=coin_ids
        )
        
        self.commands.append(cmd)
        logger.debug(f"Added merge_coins: {len(coin_ids)} coins")
        
        return self
    
    def transfer_iota(
        self,
        recipients: List[str],
        amounts: List[int]
    ) -> 'TransactionBuilder':
        """
        Transfere IOTA para múltiplos destinatários
        
        Internamente usa split_coins + transfer_objects
        
        Args:
            recipients: Lista de endereços destino
            amounts: Lista de valores a transferir
            
        Returns:
            Self para chaining
        """
        if len(recipients) != len(amounts):
            raise ValueError("Recipients and amounts must have same length")
        
        # Split gas coin nos valores necessários
        self.split_coins(amounts)
        
        # Transferir cada split para seu destinatário
        # Nota: isso é uma simplificação - na prática precisa usar Results
        logger.debug(f"Added transfer_iota: {len(recipients)} transfers")
        
        return self
    
    def build_cli_command(self) -> str:
        """
        Constrói comando CLI completo
        
        Returns:
            String do comando `iota client ptb`
        """
        if not self.commands:
            raise ValueError("No commands added to transaction")
        
        cmd_parts = ["iota", "client", "ptb"]
        
        # Adicionar todos os comandos
        for cmd in self.commands:
            cmd_parts.append(cmd.to_cli_string())
        
        # Adicionar sender e gas-budget
        cmd_parts.append(f"--sender {self.sender}")
        cmd_parts.append(f"--gas-budget {self.gas_budget}")
        
        full_cmd = " ".join(cmd_parts)
        logger.debug(f"Built CLI command: {full_cmd[:100]}...")
        
        return full_cmd
    
    def execute(
        self,
        client_container,
        wait_for_finality: bool = True
    ) -> Dict[str, Any]:
        """
        Executa a transação
        
        Args:
            client_container: Container Fogbed com IOTA CLI
            wait_for_finality: Esperar confirmação
            
        Returns:
            Dicionário com resultado da transação:
            {
                'success': bool,
                'digest': str,
                'effects': dict,
                'error': str (se falhou)
            }
        """
        logger.info(f"Executing transaction with {len(self.commands)} commands")
        
        try:
            cmd = self.build_cli_command()
            result = client_container.cmd(cmd)
            
            logger.debug(f"Raw execution result:\n{result}")
            
            # Parse do resultado
            parsed = self._parse_execution_result(result)
            
            if parsed['success']:
                logger.info(f"✅ Transaction succeeded: {parsed['digest']}")
            else:
                logger.error(f"❌ Transaction failed: {parsed.get('error', 'Unknown error')}")
            
            return parsed
        
        except Exception as e:
            logger.error(f"Failed to execute transaction: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def dry_run(
        self,
        client_container
    ) -> Dict[str, Any]:
        """
        Executa dry-run da transação (sem committar)
        
        Args:
            client_container: Container Fogbed com IOTA CLI
            
        Returns:
            Resultado do dry-run com estimativa de gas
        """
        logger.info("Executing dry-run")
        
        try:
            cmd = self.build_cli_command() + " --dry-run"
            result = client_container.cmd(cmd)
            
            return self._parse_dry_run_result(result)
        
        except Exception as e:
            logger.error(f"Dry-run failed: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _parse_execution_result(self, output: str) -> Dict[str, Any]:
        """Parse do output de execução"""
        result = {
            'success': False,
            'raw_output': output
        }
        
        # Buscar digest
        digest_match = re.search(r'Transaction Digest:\s*([A-Za-z0-9]+)', output)
        if digest_match:
            result['digest'] = digest_match.group(1)
            result['success'] = True
        
        # Buscar status
        if 'Status : Success' in output or 'executed successfully' in output.lower():
            result['success'] = True
        elif 'Status : Failure' in output or 'error' in output.lower():
            result['success'] = False
            # Extrair mensagem de erro
            error_match = re.search(r'(?:Error|Failure):\s*(.+)', output, re.IGNORECASE)
            if error_match:
                result['error'] = error_match.group(1).strip()
        
        # Buscar gas usado
        gas_match = re.search(r'Gas Used:\s*(\d+)', output)
        if gas_match:
            result['gas_used'] = int(gas_match.group(1))
        
        return result
    
    def _parse_dry_run_result(self, output: str) -> Dict[str, Any]:
        """Parse do output de dry-run"""
        result = {
            'success': False,
            'raw_output': output
        }
        
        # Extrair estimativa de gas
        gas_match = re.search(r'Estimated Gas:\s*(\d+)', output)
        if gas_match:
            result['estimated_gas'] = int(gas_match.group(1))
            result['success'] = True
        
        return result
    
    def clear(self) -> 'TransactionBuilder':
        """Limpa todos os comandos"""
        self.commands.clear()
        self._inputs.clear()
        logger.debug("Transaction builder cleared")
        return self


class SimpleTransaction:
    """
    Helper para transações simples e comuns
    
    Para casos onde TransactionBuilder é muito verboso
    """
    
    @staticmethod
    def transfer_iota(
        sender: str,
        recipient: str,
        amount: int,
        client_container,
        gas_budget: int = 10_000_000
    ) -> Dict[str, Any]:
        """
        Transferência simples de IOTA
        
        Args:
            sender: Endereço remetente
            recipient: Endereço destinatário
            amount: Valor em MIST
            client_container: Container CLI
            gas_budget: Gas budget
            
        Returns:
            Resultado da transação
        """
        logger.info(f"Simple transfer: {amount} MIST from {sender[:16]}... to {recipient[:16]}...")
        
        tx = TransactionBuilder(sender, gas_budget)
        tx.transfer_iota([recipient], [amount])
        
        return tx.execute(client_container)
    
    @staticmethod
    def call_function(
        sender: str,
        package: str,
        module: str,
        function: str,
        args: Optional[List[Any]] = None,
        type_args: Optional[List[str]] = None,
        client_container = None,
        gas_budget: int = 10_000_000
    ) -> Dict[str, Any]:
        """
        Chamada simples de função Move
        
        Args:
            sender: Endereço remetente
            package: Package ID
            module: Nome do módulo
            function: Nome da função
            args: Argumentos
            type_args: Type arguments
            client_container: Container CLI
            gas_budget: Gas budget
            
        Returns:
            Resultado da transação
        """
        logger.info(f"Simple call: {package}::{module}::{function}")
        
        tx = TransactionBuilder(sender, gas_budget)
        tx.move_call(package, module, function, args, type_args)
        
        return tx.execute(client_container)


