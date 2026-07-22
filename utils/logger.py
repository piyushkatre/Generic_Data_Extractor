"""
Logging module.
Configures structured JSON console outputs for tracking program steps and metrics,
while allowing fallback to plain text logs if needed.
"""

import logging
import os
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

class JsonFormatter(logging.Formatter):
    """
    Format standard log records and any custom attributes (e.g. metrics)
    into single-line JSON strings for structured log aggregators.
    """
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage()
        }
        
        # Capture metrics if injected via extra={'metrics': ...}
        if hasattr(record, "metrics"):
            log_record["metrics"] = record.metrics
            
        # Capture exceptions if present
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
            
        return json.dumps(log_record)

def get_logger(name: str) -> logging.Logger:
    """
    Sets up a logger instance with default configurations.
    Supports debug levels and dynamic switching between structured JSON or plain text formats.

    Args:
        name (str): Calling module name.

    Returns:
        logging.Logger: Configured logger instance.
    """
    logger = logging.getLogger(name)
    
    # Avoid duplicate handlers if already configured
    if logger.hasHandlers():
        return logger

    # Resolve log level dynamically (supports debug mode)
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)

    # Console Handler Setup
    ch = logging.StreamHandler()
    
    # Toggle JSON logging based on env variable
    use_json = os.getenv("JSON_LOGGING", "true").lower() == "true"
    if use_json:
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # File Handler Setup (outputs to logs/extractor.log)
    log_dir = "logs"
    if os.path.exists(log_dir):
        try:
            log_file = os.path.join(log_dir, "extractor.log")
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(formatter)
            logger.addHandler(fh)
        except Exception as e:
            # Fallback if file logging fails due to permissions or lock issues
            logger.warning(f"Failed to initialize file logger for logs/extractor.log: {e}")
    
    return logger
