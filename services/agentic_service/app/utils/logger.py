"""
Simple logger setup.

For MVP, Python's built-in logging is enough.

Later, for enterprise-level deployment, this can be upgraded to:
- structured JSON logs
- request tracing
- OpenTelemetry
- centralized log storage
"""

import logging


def get_logger(name: str) -> logging.Logger:
    """
    Return a configured logger instance.
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        )

    return logger