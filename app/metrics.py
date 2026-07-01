"""Collects infrastructure metrics from GCP Cloud Monitoring, falling back
to synthetic (mock) metrics when no GCP credentials are configured - so the
whole app runs locally without any GCP setup.
"""
import logging
import random
import time
from datetime import datetime, timezone

from app import has_real_gcp_project

logger = logging.getLogger("cloudpulse.metrics")

try:
    import google.auth
    from google.auth.exceptions import DefaultCredentialsError
    from google.cloud import monitoring_v3

    GCP_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised when the GCP extras aren't installed
    GCP_SDK_AVAILABLE = False

# Cloud Monitoring metric types polled in real mode.
_METRIC_CPU = "compute.googleapis.com/instance/cpu/utilization"
_METRIC_MEMORY = "agent.googleapis.com/memory/percent_used"
_METRIC_LATENCY = "run.googleapis.com/request_latencies"

# Cloud Monitoring lookback window for the metrics query.
_LOOKBACK_SECONDS = 300


class MetricsCollector:
    """Produces one metrics snapshot per call to collect().

    Tries to talk to real Cloud Monitoring if a project id is configured
    and GCP credentials can be resolved; otherwise (and on any query
    failure) it falls back to a random-walk mock generator so the rest of
    the app - thresholds, alerts, dashboard - can always be exercised.
    """

    def __init__(self, config):
        self.project_id = (config.get("gcp") or {}).get("project_id")
        self.mock_mode = True
        self._client = None
        self._project_path = None
        # Mock state seeded near "healthy" values; _walk() drifts it over time
        # and occasionally spikes it past thresholds to produce alerts.
        self._mock_state = {"cpu": 30.0, "memory": 40.0, "latency": 120.0}

        if GCP_SDK_AVAILABLE and has_real_gcp_project(self.project_id):
            try:
                credentials, _ = google.auth.default()
                self._client = monitoring_v3.MetricServiceClient(credentials=credentials)
                self._project_path = f"projects/{self.project_id}"
                self.mock_mode = False
                logger.info("Connected to GCP Cloud Monitoring", extra={"project_id": self.project_id})
            except DefaultCredentialsError as e:
                logger.warning("No GCP credentials found, using mock metrics", extra={"error": str(e)})
        else:
            logger.info("Running in mock metrics mode (no project id or GCP SDK configured)")

    def collect(self):
        if self.mock_mode:
            return self._collect_mock()
        try:
            return self._collect_real()
        except Exception as e:
            logger.error("Cloud Monitoring query failed, using mock data for this cycle", extra={"error": str(e)})
            return self._collect_mock()

    # real GCP mode

    def _collect_real(self):
        now = time.time()
        interval = monitoring_v3.TimeInterval(
            {
                "end_time": {"seconds": int(now)},
                "start_time": {"seconds": int(now - _LOOKBACK_SECONDS)},
            }
        )

        cpu = self._average_metric(_METRIC_CPU, interval)
        memory = self._average_metric(_METRIC_MEMORY, interval)
        latency = self._average_metric(_METRIC_LATENCY, interval)

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cpu_utilization_percent": round((cpu or 0) * 100, 2),
            "memory_utilization_percent": round(memory or 0, 2),
            "latency_ms": round(latency or 0, 2),
            "source": "gcp",
        }

    def _average_metric(self, metric_type, interval):
        results = self._client.list_time_series(
            request={
                "name": self._project_path,
                "filter": f'metric.type = "{metric_type}"',
                "interval": interval,
                "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
            }
        )
        values = [
            point.value.double_value or point.value.int64_value
            for series in results
            for point in series.points
        ]
        return sum(values) / len(values) if values else None

    # mock mode

    def _collect_mock(self):
        state = self._mock_state
        state["cpu"] = self._walk(state["cpu"], lo=0, hi=100, volatility=8, spike_chance=0.12, spike_add=35)
        state["memory"] = self._walk(state["memory"], lo=0, hi=100, volatility=5, spike_chance=0.08, spike_add=30)
        state["latency"] = self._walk(state["latency"], lo=20, hi=2000, volatility=40, spike_chance=0.10, spike_add=600)

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cpu_utilization_percent": round(state["cpu"], 2),
            "memory_utilization_percent": round(state["memory"], 2),
            "latency_ms": round(state["latency"], 2),
            "source": "mock",
        }

    @staticmethod
    def _walk(value, lo, hi, volatility, spike_chance, spike_add):
        delta = random.uniform(-volatility, volatility)
        if random.random() < spike_chance:
            delta += spike_add
        return max(lo, min(hi, value + delta))
