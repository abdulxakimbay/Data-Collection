# services/logging.py
import logging
import os
from logging.handlers import RotatingFileHandler

def setup_logging():
    os.makedirs("logs", exist_ok=True)

    fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    logger = logging.getLogger()
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

    sh = logging.StreamHandler()
    sh.setLevel(os.getenv("LOG_LEVEL_CONSOLE", "INFO").upper())
    sh.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))

    fh = RotatingFileHandler(
        filename="logs/app.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    fh.setLevel(os.getenv("LOG_LEVEL_FILE", "INFO").upper())
    fh.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))

    if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        logger.addHandler(fh)
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        logger.addHandler(sh)

    logging.getLogger("httpx").setLevel("WARNING")
    logging.getLogger("googleapiclient").setLevel("WARNING")
