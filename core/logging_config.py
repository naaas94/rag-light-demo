import logging
from rich.logging import RichHandler

def setup_logger(file_name: str = "rag_system.log", log_level: str = "INFO"):
    """
    Sets up a structured logger using Rich for console output and a file handler for persistence.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)
    
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(rich_tracebacks=True),
            logging.FileHandler(file_name)
        ]
    )
    
    logger = logging.getLogger("rag_core")
    return logger

logger = setup_logger()
