import sys

from loguru import logger


def configure_logger() -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    )
