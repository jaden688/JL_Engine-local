import logging
import logging.handlers

# Configure logging with rotation (self-cleaning)
logging.basicConfig(
    # Default to INFO so we don't flood logs with token-level debug noise.
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            "app.log",
            maxBytes=1_000_000,  # ~1MB per file
            backupCount=3,  # keep last 3 rotations
            encoding="utf-8",
        ),
    ],
)


def get_logger(name):
    return logging.getLogger(name)


# Dedicated backend log (for direct/backend-only runs)
_backend_logger = logging.getLogger("backend")
if not _backend_logger.handlers:
    _backend_logger.setLevel(logging.INFO)
    _backend_logger.propagate = False
    backend_handler = logging.handlers.RotatingFileHandler(
        "app_backend.log",
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    backend_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    _backend_logger.addHandler(backend_handler)


def get_backend_logger():
    return _backend_logger
