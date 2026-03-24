
import logging
import logging.handlers

# Configure logging
logging.basicConfig(level=logging.DEBUG,
                    format="%(asctime)s - %(levelname)s - %(filename)s - %(message)s",
                    handlers=[
                        logging.FileHandler("app.log"),
                        logging.StreamHandler(),
                        logging.handlers.RotatingFileHandler(
                            "app.log", maxBytes=1000000, backupCount=5
                        )
                    ])

def get_logger(name):
    return logging.getLogger(name)
