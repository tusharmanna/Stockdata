import logging
import sys
from pathlib import Path

_loggers: dict[str, logging.Logger] = {}

def get_logger(name: str) -> logging.Logger:
    if name in _loggers:
        return _loggers[name]

    from old.nasdaq_ml_trader.config import LOG_DIR
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(f"nasdaq_ml.{name}")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    fh = logging.FileHandler(LOG_DIR / f"{name}.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    sh.setLevel(logging.WARNING)
    logger.addHandler(sh)


    _loggers[name] = logger
    return logger
