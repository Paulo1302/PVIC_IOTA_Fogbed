# fogbed_iota/utils/docker.py
"""
Docker operations com logging
Gerencia copy, exec, e status de containers
"""

import subprocess
import os
from pathlib import Path
from fogbed_iota.utils.logging import get_logger

logger = get_logger('docker')


def docker_copy(src, dst, container_name, retries=3):
    """
    Copiar arquivo/diretório para container
    
    Args:
        src: Caminho origem (host)
        dst: Caminho destino (container)
        container_name: Nome do container (ex: mn.validator1)
        retries: Número de tentativas
    
    Returns:
        bool: Sucesso ou falha
    """
    
    src_path = Path(src)
    if not src_path.exists():
        logger.error(f"Source path does not exist: {src}")
        return False
    
    cmd = ['docker', 'cp', f"{src}/.", f"{container_name}:{dst}"]
    logger.debug(f"Docker cp: {' '.join(cmd)}")
    
    for attempt in range(1, retries + 1):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                logger.info(f"✅ Copied {src} → {container_name}:{dst}")
                return True
            else:
                logger.warning(f"Attempt {attempt}/{retries} failed: {result.stderr.strip()}")
                if attempt < retries:
                    import time
                    time.sleep(2)
        
        except subprocess.TimeoutExpired:
            logger.warning(f"Attempt {attempt}/{retries} timeout (30s)")
            if attempt < retries:
                import time
                time.sleep(2)
        
        except Exception as e:
            logger.error(f"Docker cp error: {str(e)}")
            return False
    
    logger.error(f"Failed to copy {src} → {container_name}:{dst} after {retries} attempts")
    return False


def docker_exec(container_name, command, timeout=30):
    """
    Executar comando dentro de container
    
    Args:
        container_name: Nome do container
        command: Comando a executar
        timeout: Timeout em segundos
    
    Returns:
        tuple: (returncode, stdout, stderr)
    """
    
    cmd = ['docker', 'exec', container_name, 'bash', '-c', command]
    logger.debug(f"Docker exec: {' '.join(cmd[:4])} '{command}'")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        
        if result.returncode == 0:
            logger.debug(f"✅ Container {container_name}: Command succeeded")
            return (0, result.stdout, result.stderr)
        else:
            logger.warning(f"Container {container_name}: Command failed (exit {result.returncode})")
            return (result.returncode, result.stdout, result.stderr)
    
    except subprocess.TimeoutExpired:
        logger.error(f"Container {container_name}: Command timeout ({timeout}s)")
        return (124, "", f"Timeout after {timeout}s")
    
    except Exception as e:
        logger.error(f"Docker exec error: {str(e)}")
        return (1, "", str(e))# fogbed_iota/utils/docker.py
"""
Docker operations com logging
Gerencia copy, exec, e status de containers
"""

import subprocess
import os
from pathlib import Path
from fogbed_iota.utils.logging import get_logger

logger = get_logger('docker')


def docker_copy(src, dst, container_name, retries=3):
    """
    Copiar arquivo/diretório para container
    
    Args:
        src: Caminho origem (host)
        dst: Caminho destino (container)
        container_name: Nome do container (ex: mn.validator1)
        retries: Número de tentativas
    
    Returns:
        bool: Sucesso ou falha
    """
    
    src_path = Path(src)
    if not src_path.exists():
        logger.error(f"Source path does not exist: {src}")
        return False
    
    cmd = ['docker', 'cp', f"{src}/.", f"{container_name}:{dst}"]
    logger.debug(f"Docker cp: {' '.join(cmd)}")
    
    for attempt in range(1, retries + 1):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                logger.info(f"✅ Copied {src} → {container_name}:{dst}")
                return True
            else:
                logger.warning(f"Attempt {attempt}/{retries} failed: {result.stderr.strip()}")
                if attempt < retries:
                    import time
                    time.sleep(2)
        
        except subprocess.TimeoutExpired:
            logger.warning(f"Attempt {attempt}/{retries} timeout (30s)")
            if attempt < retries:
                import time
                time.sleep(2)
        
        except Exception as e:
            logger.error(f"Docker cp error: {str(e)}")
            return False
    
    logger.error(f"Failed to copy {src} → {container_name}:{dst} after {retries} attempts")
    return False


def docker_exec(container_name, command, timeout=30):
    """
    Executar comando dentro de container
    
    Args:
        container_name: Nome do container
        command: Comando a executar
        timeout: Timeout em segundos
    
    Returns:
        tuple: (returncode, stdout, stderr)
    """
    
    cmd = ['docker', 'exec', container_name, 'bash', '-c', command]
    logger.debug(f"Docker exec: {' '.join(cmd[:4])} '{command}'")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        
        if result.returncode == 0:
            logger.debug(f"✅ Container {container_name}: Command succeeded")
            return (0, result.stdout, result.stderr)
        else:
            logger.warning(f"Container {container_name}: Command failed (exit {result.returncode})")
            return (result.returncode, result.stdout, result.stderr)
    
    except subprocess.TimeoutExpired:
        logger.error(f"Container {container_name}: Command timeout ({timeout}s)")
        return (124, "", f"Timeout after {timeout}s")
    
    except Exception as e:
        logger.error(f"Docker exec error: {str(e)}")
        return (1, "", str(e))


def docker_logs(container_name, tail=50):
    """
    Obter últimos logs do container
    
    Args:
        container_name: Nome do container
        tail: Número de linhas
    
    Returns:
        str: Logs do container
    """
    
    cmd = ['docker', 'logs', f'--tail={tail}', container_name]
    logger.debug(f"Getting logs: {container_name} (last {tail} lines)")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return result.stdout
        else:
            logger.warning(f"Failed to get logs from {container_name}: {result.stderr}")
            return ""
    
    except Exception as e:
        logger.error(f"Error getting logs: {str(e)}")
        return ""


def container_exists(container_name):
    """
    Verificar se container existe
    
    Args:
        container_name: Nome do container
    
    Returns:
        bool: True se existe
    """
    
    cmd = ['docker', 'ps', '-a', '--format', 'table {{.Names}}']
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        containers = result.stdout.strip().split('\n')
        exists = container_name in containers
        
        logger.debug(f"Container {container_name} exists: {exists}")
        return exists
    
    except Exception as e:
        logger.error(f"Error checking container: {str(e)}")
        return False


def wait_for_container(container_name, timeout=60):
    """
    Aguardar container ficar pronto
    
    Args:
        container_name: Nome do container
        timeout: Timeout em segundos
    
    Returns:
        bool: True se container ficou pronto
    """
    
    import time
    start_time = time.time()
    
    logger.info(f"Waiting for container {container_name} to be ready...")
    
    while time.time() - start_time < timeout:
        if container_exists(container_name):
            # Verificar se está rodando
            cmd = ['docker', 'inspect', '-f', '{{.State.Running}}', container_name]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if 'true' in result.stdout:
                logger.info(f"✅ Container {container_name} is ready")
                return True
        
        time.sleep(1)
    
    logger.error(f"Container {container_name} did not become ready within {timeout}s")
    return False


def get_container_ip(container_name):
    """
    Obter IP do container
    
    Args:
        container_name: Nome do container
    
    Returns:
        str: IP address ou None
    """
    
    cmd = ['docker', 'inspect', '-f', '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}', container_name]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            ip = result.stdout.strip()
            logger.debug(f"Container {container_name} IP: {ip}")
            return ip
    
    except Exception as e:
        logger.error(f"Error getting container IP: {str(e)}")
    
    return None


def docker_logs(container_name, tail=50):
    """
    Obter últimos logs do container
    
    Args:
        container_name: Nome do container
        tail: Número de linhas
    
    Returns:
        str: Logs do container
    """
    
    cmd = ['docker', 'logs', f'--tail={tail}', container_name]
    logger.debug(f"Getting logs: {container_name} (last {tail} lines)")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return result.stdout
        else:
            logger.warning(f"Failed to get logs from {container_name}: {result.stderr}")
            return ""
    
    except Exception as e:
        logger.error(f"Error getting logs: {str(e)}")
        return ""


def container_exists(container_name):
    """
    Verificar se container existe
    
    Args:
        container_name: Nome do container
    
    Returns:
        bool: True se existe
    """
    
    cmd = ['docker', 'ps', '-a', '--format', 'table {{.Names}}']
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        containers = result.stdout.strip().split('\n')
        exists = container_name in containers
        
        logger.debug(f"Container {container_name} exists: {exists}")
        return exists
    
    except Exception as e:
        logger.error(f"Error checking container: {str(e)}")
        return False


def wait_for_container(container_name, timeout=60):
    """
    Aguardar container ficar pronto
    
    Args:
        container_name: Nome do container
        timeout: Timeout em segundos
    
    Returns:
        bool: True se container ficou pronto
    """
    
    import time
    start_time = time.time()
    
    logger.info(f"Waiting for container {container_name} to be ready...")
    
    while time.time() - start_time < timeout:
        if container_exists(container_name):
            # Verificar se está rodando
            cmd = ['docker', 'inspect', '-f', '{{.State.Running}}', container_name]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if 'true' in result.stdout:
                logger.info(f"✅ Container {container_name} is ready")
                return True
        
        time.sleep(1)
    
    logger.error(f"Container {container_name} did not become ready within {timeout}s")
    return False


def get_container_ip(container_name):
    """
    Obter IP do container
    
    Args:
        container_name: Nome do container
    
    Returns:
        str: IP address ou None
    """
    
    cmd = ['docker', 'inspect', '-f', '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}', container_name]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            ip = result.stdout.strip()
            logger.debug(f"Container {container_name} IP: {ip}")
            return ip
    
    except Exception as e:
        logger.error(f"Error getting container IP: {str(e)}")
    
    return None