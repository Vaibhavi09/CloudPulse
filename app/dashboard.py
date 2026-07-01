"""Flask app: a background thread polls metrics on a timer, and the
dashboard / JSON endpoints read the latest snapshot from shared state.
"""
import logging
import os
import threading
import time

from flask import Flask, jsonify, render_template

from app.alerts import AlertManager
from app.metrics import MetricsCollector

logger = logging.getLogger("cloudpulse.dashboard")

# templates/ lives at the project root, one level above this app/ package -
# spell it out explicitly rather than relying on Flask's __name__ guess.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATE_FOLDER = os.path.join(_PROJECT_ROOT, "templates")


class PulseState:
    """Thread-safe holder for the most recent metrics snapshot."""

    def __init__(self):
        self._latest_metrics = None
        self._lock = threading.Lock()

    def update(self, metrics):
        with self._lock:
            self._latest_metrics = metrics

    def get(self):
        with self._lock:
            return self._latest_metrics


def _start_polling(collector, alert_manager, state, interval_seconds):
    def poll_loop():
        while True:
            metrics = collector.collect()
            state.update(metrics)
            alerts = alert_manager.evaluate(metrics)
            if alerts:
                logger.info("Alerts raised this cycle", extra={"count": len(alerts)})
            time.sleep(interval_seconds)

    thread = threading.Thread(target=poll_loop, name="metrics-poller", daemon=True)
    thread.start()
    return thread


def create_app(config):
    app = Flask(__name__, template_folder=_TEMPLATE_FOLDER)

    state = PulseState()
    collector = MetricsCollector(config)
    alert_manager = AlertManager(config)
    interval_seconds = (config.get("polling") or {}).get("interval_seconds", 15)

    # Collect one snapshot immediately so the dashboard isn't empty on first load.
    state.update(collector.collect())
    _start_polling(collector, alert_manager, state, interval_seconds)

    @app.route("/")
    def index():
        return render_template(
            "index.html",
            metrics=state.get(),
            alerts=alert_manager.get_history(),
            thresholds=alert_manager.thresholds,
            mock_mode=collector.mock_mode,
            refresh_seconds=max(5, min(interval_seconds, 30)),
        )

    @app.route("/api/metrics")
    def api_metrics():
        return jsonify(state.get() or {})

    @app.route("/api/alerts")
    def api_alerts():
        return jsonify(alert_manager.get_history())

    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "mock_mode": collector.mock_mode})

    return app
