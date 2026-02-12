# fogbed_iota/smart_contracts.py

"""
Gerenciamento de smart contracts Move na IOTA
Deploy, chamadas e queries - SEM funding automático
"""

import json
import os
import time
from typing import Dict, List, Optional, Any
from pathlib import Path

from fogbed_iota.utils import get_logger

logger = get_logger('smart_contracts')


class MovePackage:
    """Representa um pacote Move publicado"""
    
    def __init__(
        self,
        package_id: str,
        name: str,
        modules: List[str],
        digest: str,
        publisher: str
    ):
        self.package_id = package_id
        self.name = name
        self.modules = modules
        self.digest = digest
        self.publisher = publisher
        self.deployed_at = time.time()
    
    def __repr__(self):
        return f"MovePackage(name='{self.name}', id='{self.package_id[:16]}...')"


class SmartContractManager:
    """
    Gerencia ciclo de vida de smart contracts Move
    
    Operações:
    - Build de pacotes Move
    - Publish na chain (requer gas do usuário)
    - Chamadas de função (requer gas)
    - Queries de objetos
    """
    
    def __init__(self, client_container, account_manager):
        self.client = client_container
        self.accounts = account_manager
        self.deployed_packages: Dict[str, MovePackage] = {}
        self.contracts_dir = "/contracts"
    
    def copy_package_to_container(self, local_path: str, package_name: str) -> str:
        """
        Copia pacote Move do host para container
        
        Args:
            local_path: Caminho local do pacote (com Move.toml)
            package_name: Nome para o diretório no container
            
        Returns:
            Caminho do pacote dentro do container
        """
        logger.info(f"Copying package '{package_name}' to container")
        
        container_path = f"{self.contracts_dir}/{package_name}"
        
        # Criar diretório
        self.client.cmd(f"mkdir -p {container_path}")
        
        # Copiar via docker cp
        cmd = (
            f"docker cp {local_path}/. "
            f"mn.{self.client.name}:{container_path}/"
        )
        result = os.system(cmd)
        
        if result != 0:
            raise RuntimeError(f"Failed to copy package to container")
        
        logger.info(f"✅ Package copied to {container_path}")
        return container_path
    
    def build_package(self, package_path: str) -> Dict[str, Any]:
        """
        Compila pacote Move
        
        Args:
            package_path: Caminho do pacote DENTRO do container
            
        Returns:
            Dict com build info (modules, bytecode paths, etc.)
        """
        logger.info(f"Building Move package: {package_path}")
        
        # Verificar Move.toml
        check_cmd = f"test -f {package_path}/Move.toml && echo 'OK' || echo 'NOT_FOUND'"
        check = self.client.cmd(check_cmd).strip()
        
        if check != 'OK':
            raise FileNotFoundError(
                f"Move.toml not found in {package_path}. "
                f"Ensure package structure is correct."
            )
        
        # Build
        build_cmd = f"cd {package_path} && iota move build --dump-bytecode-as-base64 2>&1"
        output = self.client.cmd(build_cmd)
        
        # Verificar sucesso
        if "BUILD SUCCESSFUL" in output or "Successfully built" in output:
            logger.info("✅ Build completed successfully")
            
            # Parse módulos compilados
            modules = self._extract_modules_from_build(package_path)
            
            return {
                'success': True,
                'package_path': package_path,
                'build_path': f"{package_path}/build",
                'modules': modules,
                'output': output
            }
        else:
            logger.error(f"Build failed:\n{output}")
            raise RuntimeError(f"Move build failed: {output}")
    
    def publish_package(
        self,
        package_path: str,
        sender_alias: str,
        gas_budget: int = 100_000_000,
        skip_dependency_verification: bool = False
    ) -> MovePackage:
        """
        Publica pacote Move na chain
        
        IMPORTANTE: Requer que sender_alias tenha saldo suficiente
        
        Args:
            package_path: Caminho do pacote no container
            sender_alias: Alias da conta que paga gas
            gas_budget: Orçamento de gas em MIST
            skip_dependency_verification: Pular verificação de deps
            
        Returns:
            MovePackage com package_id e metadata
            
        Raises:
            RuntimeError: Se sender não tem saldo ou publish falha
        """
        logger.info(f"Publishing package from {sender_alias}")
        
        # Verificar saldo
        account = self.accounts.get_account(sender_alias)
        if not account:
            raise ValueError(f"Account '{sender_alias}' not found")
        
        balance = self.accounts.get_balance(sender_alias)
        if balance < gas_budget:
            raise RuntimeError(
                f"Insufficient balance for {sender_alias}. "
                f"Has {balance} MIST, needs {gas_budget} MIST. "
                f"Please fund the account first via genesis bank transfer."
            )
        
        # Construir comando publish
        cmd = (
            f"cd {package_path} && "
            f"iota client publish "
            f"--gas-budget {gas_budget} "
            f"--json"
        )
        
        if skip_dependency_verification:
            cmd += " --skip-dependency-verification"
        
        logger.debug(f"Executing: {cmd}")
        result = self.client.cmd(cmd)
        
        try:
            tx_result = json.loads(result)
            
            # Verificar status da transação primeiro
            status = tx_result.get('effects', {}).get('status', {})
            if status.get('status') != 'success':
                error = status.get('error', 'Unknown error')
                raise RuntimeError(f"Publish transaction failed: {error}")
            
            # Extrair package_id dos objectChanges
            published_changes = [
                c for c in tx_result.get('objectChanges', [])
                if c.get('type') == 'published'
            ]
            
            if not published_changes:
                raise RuntimeError(f"No published packages in transaction: {result}")
            
            # Pegar primeiro package publicado
            package_obj = published_changes[0]
            package_id = package_obj['packageId']
            modules = package_obj.get('modules', [])
            digest = tx_result.get('digest', '')
            
            # Extrair nome do pacote
            package_name = os.path.basename(package_path)
            
            move_pkg = MovePackage(
                package_id=package_id,
                name=package_name,
                modules=modules,
                digest=digest,
                publisher=account.address
            )
            
            self.deployed_packages[package_name] = move_pkg
            
            logger.info(f"✅ Package published: {package_id}")
            logger.info(f"   Transaction: {digest}")
            logger.info(f"   Modules: {', '.join(modules)}")
            
            return move_pkg
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse publish result: {result}")
            raise RuntimeError(f"Publish output parsing failed: {e}")
    
    def call_function(
        self,
        package_id: str,
        module: str,
        function: str,
        sender_alias: str,
        type_args: Optional[List[str]] = None,
        args: Optional[List[str]] = None,
        gas_budget: int = 10_000_000
    ) -> Dict[str, Any]:
        """
        Chama função pública de um contrato Move
        
        Args:
            package_id: ID do pacote (0xABC...)
            module: Nome do módulo
            function: Nome da função
            sender_alias: Conta que executa (e paga gas)
            type_args: Type arguments para função genérica
            args: Argumentos da função
            gas_budget: Orçamento de gas
            
        Returns:
            Dict com resultado da transação
            
        Example:
            manager.call_function(
                package_id="0x123...",
                module="counter",
                function="increment",
                sender_alias="alice",
                args=[]
            )
        """
        logger.info(f"Calling {package_id}::{module}::{function}")
        
        # Verificar conta
        account = self.accounts.get_account(sender_alias)
        if not account:
            raise ValueError(f"Account '{sender_alias}' not found")
        
        # Construir comando
        cmd = (
            f"iota client call "
            f"--package {package_id} "
            f"--module {module} "
            f"--function {function} "
            f"--gas-budget {gas_budget} "
            f"--json"
        )
        
        # Type arguments
        if type_args:
            for targ in type_args:
                cmd += f" --type-args {targ}"
        
        # Arguments
        if args:
            for arg in args:
                cmd += f" --args {arg}"
        
        logger.debug(f"Executing: {cmd}")
        result = self.client.cmd(cmd)
        
        try:
            tx_result = json.loads(result)
            
            status = tx_result.get('effects', {}).get('status', {})
            if status.get('status') != 'success':
                error = status.get('error', 'Unknown error')
                raise RuntimeError(f"Transaction failed: {error}")
            
            logger.info(f"✅ Function executed: {tx_result.get('digest', 'N/A')}")
            
            return tx_result
            
        except json.JSONDecodeError:
            logger.error(f"Failed to parse call result: {result}")
            raise RuntimeError(f"Call output parsing failed")
    
    def get_object(self, object_id: str) -> Dict[str, Any]:
        """
        Busca objeto on-chain por ID
        
        Args:
            object_id: ID do objeto (0x...)
            
        Returns:
            Dict com dados do objeto
        """
        logger.debug(f"Fetching object: {object_id}")
        
        cmd = f"iota client object {object_id} --json"
        result = self.client.cmd(cmd)
        
        try:
            obj_data = json.loads(result)
            return obj_data
        except json.JSONDecodeError:
            raise RuntimeError(f"Failed to parse object data: {result}")
    
    def get_package_info(self, package_name: str) -> Optional[MovePackage]:
        """Busca informações de pacote publicado"""
        return self.deployed_packages.get(package_name)
    
    def fund_account_from_bank(self, target_alias: str, amount_iota: float = 10.0) -> str:
        """
        Transfere IOTA do banco do genesis para uma conta
        
        Args:
            target_alias: Alias da conta destino
            amount_iota: Quantidade em IOTA (será convertida para MIST)
            
        Returns:
            Transaction digest
        """
        logger.info(f"Funding account '{target_alias}' with {amount_iota} IOTA from genesis bank")
        
        target_account = self.accounts.get_account(target_alias)
        if not target_account:
            raise ValueError(f"Target account '{target_alias}' not found")
        
        # Converter IOTA para MIST (1 IOTA = 10^9 MIST)
        amount_mist = int(amount_iota * 1_000_000_000)
        
        # Usar keystore do genesis (banco)
        cmd = (
            f"iota client transfer "
            f"--to {target_account.address} "
            f"--amount {amount_mist} "
            f"--gas-budget 10000000 "
            f"--json"
        )
        
        logger.debug(f"Executing: {cmd}")
        result = self.client.cmd(cmd)
        
        try:
            tx_result = json.loads(result)
            
            status = tx_result.get('effects', {}).get('status', {})
            if status.get('status') != 'success':
                error = status.get('error', 'Unknown')
                raise RuntimeError(f"Transfer failed: {error}")
            
            digest = tx_result.get('digest', 'N/A')
            logger.info(f"✅ Funded {target_alias} with {amount_iota} IOTA (tx: {digest})")
            
            return digest
            
        except json.JSONDecodeError:
            logger.error(f"Failed to parse transfer result: {result}")
            raise RuntimeError("Transfer output parsing failed")
    
    def _extract_modules_from_build(self, package_path: str) -> List[str]:
        """Extrai lista de módulos do build output"""
        # Listar arquivos .mv no build/
        cmd = f"find {package_path}/build -name '*.mv' -exec basename {{}} .mv \\; 2>/dev/null || true"
        result = self.client.cmd(cmd)
        
        modules = [m.strip() for m in result.split('\n') if m.strip()]
        return modules
