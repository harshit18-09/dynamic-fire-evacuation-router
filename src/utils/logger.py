import logging
import sys

COLORS = {
    'DEBUG': '\033[94m',    
    'INFO': '\033[92m',     
    'WARNING': '\033[93m',  
    'ERROR': '\033[91m',    
    'CRITICAL': '\033[95m', 
    'RESET': '\033[0m'
}

class ColoredFormatter(logging.Formatter):
    def format(self, record):
        color = COLORS.get(record.levelname, COLORS['RESET'])
        record.levelname = f"{color}{record.levelname}{COLORS['RESET']}"
        return super().format(record)

def setup_logger(name: str = "EvacRouter") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    
    if not logger.handlers:
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG)
        formatter = ColoredFormatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        ch.setFormatter(formatter)
        logger.addHandler(ch)
    return logger