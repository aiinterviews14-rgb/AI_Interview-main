"""
Basic structured logging; replaces ad-hoc print in critical paths over time.
"""
import logging
import os
import sys


def setup_logging() -> None:
    level = (os.environ.get("LOG_LEVEL") or "INFO").upper()
    numeric = getattr(logging, level, logging.INFO)
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(numeric)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root.addHandler(h)
