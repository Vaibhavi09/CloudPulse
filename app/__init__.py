"""CloudPulse: polls GCP metrics (or synthetic ones when no credentials are
present), checks them against configurable thresholds, publishes alerts to
Pub/Sub, and serves a small Flask dashboard.
"""
import json
import logging
import os

import yaml

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")

PLACEHOLDER_PROJECT_ID = "your-gcp-project-id"


def load_config(path=None):
    """Loads config.yaml (or the path in CLOUDPULSE_CONFIG)."""
    path = path or os.environ.get("CLOUDPULSE_CONFIG", DEFAULT_CONFIG_PATH)
    with open(path, "r") as f:
        return yaml.safe_load(f)


def has_real_gcp_project(project_id):
    """False for an unset project_id or the config.yaml placeholder - used by
    metrics.py and alerts.py to decide whether to attempt real GCP calls."""
    return bool(project_id) and PLACEHOLDER_PROJECT_ID not in project_id


# LogRecord attributes present on every record; anything else attached via
# logger.info(..., extra={...}) is treated as structured context.
_RESERVED_RECORD_KEYS = set(vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Renders every log record as a single-line JSON object."""

    def format(self, record):
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED_RECORD_KEYS:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level=None):
    """Configures the root logger to emit structured JSON to stdout."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level or os.environ.get("LOG_LEVEL", "INFO"))
