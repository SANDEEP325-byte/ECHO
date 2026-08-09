import sys

from loguru import logger


logger.remove()

logger.add(
    sys.stdout,
    level="INFO",
    enqueue=True,
)

logger.add(
    "logs/echo.log",
    level="INFO",
    rotation="10 MB",
    retention="7 days",
    enqueue=True
)