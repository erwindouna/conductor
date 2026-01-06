import logging
import logging.config
import os

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

def setup_logging() -> None:
    """Set up logging configuration."""
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                },
            },
            "root": {
                "level": LOG_LEVEL,
                "handlers": ["console"],
            },
            "loggers": {
                "uvicorn": {"level": "INFO"},
                "uvicorn.error": {"level": "INFO"},
                "uvicorn.access": {"level": "WARNING"},
            },
        }
    )
