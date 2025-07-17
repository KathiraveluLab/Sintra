import logging

logger = logging.getLogger("sintra")
logger.setLevel(logging.INFO)

ch = logging.StreamHandler()
ch.setLevel(logging.INFO)

formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s')
ch.setFormatter(formatter)

if not logger.hasHandlers():
    logger.addHandler(ch)

def error(msg, *args, **kwargs):
    logger.error(msg, *args, **kwargs)

def warning(msg, *args, **kwargs):
    logger.warning(msg, *args, **kwargs)

def info(msg, *args, **kwargs):
    logger.info(msg, *args, **kwargs)

def success(msg, *args, **kwargs):
    logger.info("SUCCESS: " + msg, *args, **kwargs)
