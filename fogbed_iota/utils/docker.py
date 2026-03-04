# fogbed_iota/utils/docker.py

"""
Docker operations com logging

Gerencia copy, exec, logs e status de containers Docker.
"""

import subprocess
import time
from pathlib import Path

from fogbed_iota.utils.logging import get_logger

logger = get_logger('docker')


def docker_copy(src, dst, container_name, retries=3):
    """
    Copiar arquivo/diretório para container.

    Args:
        src: Caminho origem (host)
        dst: Caminho destino (container)
        container_name: Nome do container (ex: mn.validator1)
        retries: Número de tentativas

    Returns:
        bool: Sucesso ou falha

    Raises:
        ValueError: Se caminho origem ou container não existem
    """
    src_path = Path(src)

    if not src_path.exists():
        logger.error(f"Source path does not exist: {src}")
        raise ValueError(f"Source path does not exist: {src}")

    if not container_exists(container_name):
        logger.error(f"Container does not exist: {container_name}")
        raise ValueError(f"Container does not exist: {container_name}")

    cmd = ['docker', 'cp', f"{src}/.", f"{container_name}:{dst}"]
    logger.debug(f"Docker cp: {' '.join(cmd)}")

    for attempt in range(1, retries + 1):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                logger.info(f"✅ Copied {src} → {container_name}:{dst}")
                return True
            else:
                logger.warning(
                    f"Attempt {attempt}/{retries} failed: {result.stderr.strip()}"
                )
                if attempt < retries:
                    time.sleep(2)

        except subprocess.TimeoutExpired:
            logger.warning(f"Attempt {attempt}/{retries} timeout (30s)")
            if attempt < retries:
                time.sleep(2)

        except Exception as e:
            logger.error(f"Docker cp error: {str(e)}")
            return False

    logger.error(
        f"Failed to copy {src} → {container_name}:{dst} after {retries} attempts"
    )
    return False


def docker_exec(container_name, command, timeout=30):
    """
    Executar comando dentro de container.

    Args:
        container_name: Nome do container
        command: Comando a executar
        timeout: Timeout em segundos

    Returns:
        tuple: (returncode, stdout, stderr)

    Raises:
        ValueError: Se container não existe ou não está running
    """
    if not container_exists(container_name):
        logger.error(f"Container does not exist: {container_name}")
        raise ValueError(f"Container does not exist: {container_name}")

    if not is_container_running(container_name):
        logger.error(f"Container is not running: {container_name}")
        raise ValueError(f"Container is not running: {container_name}")

    cmd = ['docker', 'exec', container_name, 'bash', '-c', command]
    logger.debug(f"Docker exec: {' '.join(cmd[:4])} '{command}'")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            logger.debug(f"✅ Container {container_name}: Command succeeded")
            return (0, result.stdout, result.stderr)
        else:
            logger.warning(
                f"Container {container_name}: Command failed (exit {result.returncode})"
            )
            return (result.returncode, result.stdout, result.stderr)

    except subprocess.TimeoutExpired:
        logger.error(f"Container {container_name}: Command timeout ({timeout}s)")
        return (124, "", f"Timeout after {timeout}s")

    except Exception as e:
        logger.error(f"Docker exec error: {str(e)}")
        return (1, "", str(e))


def docker_logs(container_name, tail=50):
    """
    Obter últimos logs do container.

    Args:
        container_name: Nome do container
        tail: Número de linhas

    Returns:
        str: Logs do container
    """
    if not container_exists(container_name):
        logger.warning(f"Container does not exist: {container_name}")
        return ""

    cmd = ['docker', 'logs', f'--tail={tail}', container_name]
    logger.debug(f"Getting logs: {container_name} (last {tail} lines)")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return result.stdout
        else:
            logger.warning(
                f"Failed to get logs from {container_name}: {result.stderr}"
            )
            return ""

    except Exception as e:
        logger.error(f"Error getting logs: {str(e)}")
        return ""


def container_exists(container_name):
    """
    Verificar se container existe (running ou stopped).

    Args:
        container_name: Nome do container

    Returns:
        bool: True se existe
    """
    cmd = ['docker', 'ps', '-a', '--format', '{{.Names}}']

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            logger.warning(f"Failed to list containers: {result.stderr}")
            return False

        containers = result.stdout.strip().split('\n')
        exists = container_name in containers
        logger.debug(f"Container {container_name} exists: {exists}")
        return exists

    except Exception as e:
        logger.error(f"Error checking container: {str(e)}")
        return False


def is_container_running(container_name):
    """
    Verificar se container está running.

    Args:
        container_name: Nome do container

    Returns:
        bool: True se está running
    """
    if not container_exists(container_name):
        return False

    cmd = ['docker', 'inspect', '-f', '{{.State.Running}}', container_name]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            running = 'true' in result.stdout.lower()
            logger.debug(f"Container {container_name} running: {running}")
            return running
        else:
            logger.warning(f"Failed to check container status: {result.stderr}")
            return False

    except Exception as e:
        logger.error(f"Error checking container status: {str(e)}")
        return False


def wait_for_container(container_name, timeout=60):
    """
    Aguardar container ficar pronto (running).

    Args:
        container_name: Nome do container
        timeout: Timeout em segundos

    Returns:
        bool: True se container ficou pronto

    Raises:
        ValueError: Se container não existe
    """
    if not container_exists(container_name):
        logger.error(f"Container does not exist: {container_name}")
        raise ValueError(f"Container does not exist: {container_name}")

    start_time = time.time()
    logger.info(
        f"Waiting for container {container_name} to be ready (timeout: {timeout}s)..."
    )

    while time.time() - start_time < timeout:
        if is_container_running(container_name):
            elapsed = time.time() - start_time
            logger.info(
                f"✅ Container {container_name} is ready (took {elapsed:.1f}s)"
            )
            return True

        time.sleep(1)

    elapsed = time.time() - start_time
    logger.error(
        f"Container {container_name} did not become ready within {timeout}s "
        f"(waited {elapsed:.1f}s)"
    )
    return False


def get_container_ip(container_name, network=None):
    """
    Obter IP do container.

    Args:
        container_name: Nome do container
        network: Nome da rede (opcional)

    Returns:
        str: IP address ou None
    """
    if not container_exists(container_name):
        logger.warning(f"Container does not exist: {container_name}")
        return None

    if network:
        cmd = [
            'docker', 'inspect', '-f',
            f'{{{{index .NetworkSettings.Networks "{network}" "IPAddress"}}}}',
            container_name,
        ]
    else:
        cmd = [
            'docker', 'inspect', '-f',
            '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}',
            container_name,
        ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            ip = result.stdout.strip()
            if ip:
                logger.debug(f"Container {container_name} IP: {ip}")
                return ip
            else:
                logger.warning(f"Container {container_name} has no IP assigned")
                return None
        else:
            logger.warning(f"Failed to get container IP: {result.stderr}")
            return None

    except Exception as e:
        logger.error(f"Error getting container IP: {str(e)}")
        return None


def wait_for_port(container_name, port, timeout=30):
    """
    Aguardar porta estar listen no container.

    Args:
        container_name: Nome do container
        port: Porta a verificar
        timeout: Timeout em segundos

    Returns:
        bool: True se porta está ouvindo

    Raises:
        ValueError: Se container não está running
    """
    if not is_container_running(container_name):
        logger.error(f"Container is not running: {container_name}")
        raise ValueError(f"Container is not running: {container_name}")

    start_time = time.time()
    logger.info(
        f"Waiting for port {port} on {container_name} (timeout: {timeout}s)..."
    )

    while time.time() - start_time < timeout:
        cmd = (
            f"netstat -tlnp 2>/dev/null | grep ':{port}' || "
            f"ss -tlnp 2>/dev/null | grep ':{port}'"
        )
        returncode, stdout, stderr = docker_exec(container_name, cmd, timeout=5)

        if returncode == 0 and stdout:
            elapsed = time.time() - start_time
            logger.info(
                f"✅ Port {port} on {container_name} is listening (took {elapsed:.1f}s)"
            )
            return True

        time.sleep(1)

    elapsed = time.time() - start_time
    logger.error(
        f"Port {port} on {container_name} did not become ready within {timeout}s"
    )
    return False


def healthcheck_container(container_name):
    """
    Executar healthcheck básico no container.

    Args:
        container_name: Nome do container

    Returns:
        dict: {'healthy': bool, 'details': str}
    """
    if not is_container_running(container_name):
        return {'healthy': False, 'details': 'Container not running'}

    try:
        # Verificar acesso básico ao container
        returncode, stdout, stderr = docker_exec(
            container_name, "echo 'OK'", timeout=5
        )
        if returncode != 0:
            return {'healthy': False, 'details': 'Docker exec failed'}

        # Verificar status
        cmd = ['docker', 'inspect', '-f', '{{.State.Status}}', container_name]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        status = result.stdout.strip() if result.returncode == 0 else 'unknown'

        logger.info(f"Container {container_name} healthcheck: {status}")
        return {'healthy': status == 'running', 'details': f'Status: {status}'}

    except Exception as e:
        logger.error(f"Healthcheck error: {str(e)}")
        return {'healthy': False, 'details': f'Error: {str(e)}'}
