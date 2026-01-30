# fogbed_iota/utils/logging.py
"""
Logging centralizado para fogbed-iota
Fornece logger estruturado com suporte a múltiplos níveis
"""

import logging
import sys
from datetime import datetime
from pathlib import Path


class ColoredFormatter(logging.Formatter):
    """Formatter com cores para terminal"""
    
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[92m',       # Green
        'WARNING': '\033[93m',    # Yellow
        'ERROR': '\033[91m',      # Red
        'CRITICAL': '\033[41m',   # Red background
    }
    RESET = '\033[0m'
    
    def format(self, record):
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}[{levelname}]{self.RESET}"
        return super().format(record)


def setup_logging(name='fogbed_iota', level=logging.INFO, log_file=None):
    """
    Configurar logger centralizado
    
    Args:
        name: Nome do logger
        level: Nível de logging (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Arquivo para salvar logs (opcional)
    
    Returns:
        logger: Logger configurado
    """
    
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Remover handlers anteriores (evitar duplicação)
    logger.handlers.clear()
    
    # ===== Console Handler (Colorido) =====
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    
    console_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    console_formatter = ColoredFormatter(console_format, datefmt='%H:%M:%S')
    console_handler.setFormatter(console_formatter)
    
    logger.addHandler(console_handler)
    
    # ===== File Handler (Completo) =====
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(logging.DEBUG)
        
        file_format = '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
        file_formatter = logging.Formatter(file_format)
        file_handler.setFormatter(file_formatter)
        
        logger.addHandler(file_handler)
    
    return logger


# Logger global padrão
logger = setup_logging(level=logging.INFO)


def get_logger(name):
    """Obter logger para um módulo específico"""
    return logging.getLogger(f'fogbed_iota.{name}')