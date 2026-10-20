import logging
import sys


def configure_logging(app_env: str = "development"):
    level = logging.DEBUG if app_env == "development" else logging.INFO
    formatter = logging.Formatter(fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers = [handler]
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
