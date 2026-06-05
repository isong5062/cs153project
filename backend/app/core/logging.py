"""Structured logging setup for the API and the worker.

Idempotent so importing it from both ``app.main`` and ``app.worker`` is safe.
"""

from __future__ import annotations

import logging

_CONFIGURED = False
_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def setup_logging(level: int | str = logging.INFO) -> None:
    """Configure root logging once; subsequent calls are no-ops."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(level=level, format=_FORMAT)
    _CONFIGURED = True
