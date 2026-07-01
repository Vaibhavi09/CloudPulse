"""Checks metrics against configured thresholds and publishes breaches as
alerts - to Pub/Sub when it's configured and reachable, and always to the
in-memory history the dashboard reads from.
"""
import json
import logging
from collections import deque
from datetime import datetime, timezone

from app import has_real_gcp_project

logger = logging.getLogger("cloudpulse.alerts")

try:
    from google.cloud import pubsub_v1

    PUBSUB_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised when the GCP extras aren't installed
    PUBSUB_SDK_AVAILABLE = False

# metric key in the collector's snapshot -> human label used in alert messages
_MONITORED_METRICS = {
    "cpu_utilization_percent": "CPU utilization",
    "memory_utilization_percent": "Memory utilization",
    "latency_ms": "Latency",
}


class AlertManager:
    """Evaluates metric snapshots against thresholds and records/publishes alerts."""

    def __init__(self, config):
        self.thresholds = config.get("thresholds") or {}
        history_size = (config.get("alerts") or {}).get("history_size", 100)
        self.history = deque(maxlen=history_size)

        self._publisher = None
        self._topic_path = None
        self._init_pubsub(config)

    def _init_pubsub(self, config):
        gcp_config = config.get("gcp") or {}
        project_id = gcp_config.get("project_id")
        topic_name = gcp_config.get("pubsub_topic")

        if not (PUBSUB_SDK_AVAILABLE and topic_name and has_real_gcp_project(project_id)):
            logger.info("Pub/Sub publishing disabled; alerts will only be logged and kept in memory")
            return

        try:
            self._publisher = pubsub_v1.PublisherClient()
            self._topic_path = self._publisher.topic_path(project_id, topic_name)
            logger.info("Pub/Sub publishing enabled", extra={"topic": self._topic_path})
        except Exception as e:
            logger.warning("Pub/Sub unavailable, alerts will only be logged", extra={"error": str(e)})
            self._publisher = None

    def evaluate(self, metrics):
        """Returns the list of alerts raised by this metrics snapshot (may be empty)."""
        raised = []
        for metric_key, label in _MONITORED_METRICS.items():
            threshold = self.thresholds.get(metric_key)
            value = metrics.get(metric_key)
            if threshold is None or value is None or value <= threshold:
                continue
            alert = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metric": metric_key,
                "value": value,
                "threshold": threshold,
                "message": f"{label} breached threshold: {value} > {threshold}",
            }
            raised.append(alert)

        for alert in raised:
            self._record(alert)
        return raised

    def _record(self, alert):
        self.history.append(alert)
        logger.warning(alert["message"], extra={"metric": alert["metric"], "value": alert["value"],
                                                  "threshold": alert["threshold"]})
        self._publish(alert)

    def _publish(self, alert):
        if not self._publisher:
            return
        try:
            self._publisher.publish(self._topic_path, json.dumps(alert).encode("utf-8"))
        except Exception as e:
            logger.error("Failed to publish alert to Pub/Sub", extra={"error": str(e)})

    def get_history(self, limit=50):
        """Most recent alerts first."""
        return list(self.history)[-limit:][::-1]
