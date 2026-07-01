# CloudPulse - GCP Infrastructure Monitor

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)
![Flask](https://img.shields.io/badge/Flask-3.x-black?logo=flask)
![GCP](https://img.shields.io/badge/GCP-Cloud%20Monitoring%20%7C%20Pub%2FSub-4285F4?logo=googlecloud)
![Cloud Run](https://img.shields.io/badge/Deploy-Cloud%20Run-4285F4?logo=googlecloud)
![License](https://img.shields.io/badge/License-MIT-lightgrey)

A lightweight infrastructure monitor: it polls GCP Cloud Monitoring for
CPU/memory/latency, checks the readings against configurable thresholds,
publishes anomaly alerts to Pub/Sub, and serves a live Flask dashboard -
all runnable locally with **zero GCP setup** thanks to a built-in mock
metrics generator.

## Overview

CloudPulse runs a background thread that polls metrics on a timer,
evaluates them against `config.yaml` thresholds, and records/publishes any
breaches as alerts. A Flask app exposes the current state as both an HTML
dashboard and a small JSON API.

When no GCP project/credentials are configured, it automatically falls
back to a random-walk **mock metrics generator** - with occasional spikes
so you can see alerts fire - so the whole thing works out of the box.

### Architecture

```
                        ┌─────────────────────────┐
                        │   Cloud Monitoring API   │  (real mode)
                        └────────────┬─────────────┘
                                     │ polls every N seconds
                                     ▼
 config.yaml ──thresholds──►  MetricsCollector  ◄── mock mode
                                     │              (random-walk generator,
                                     │               used when no GCP creds)
                                     ▼
                              PulseState (in-memory,
                               thread-safe snapshot)
                                     │
                    ┌────────────────┼───────────────────┐
                    ▼                ▼                   ▼
              AlertManager      Flask "/"           Flask "/api/*"
           (threshold checks)   (HTML dashboard)    (JSON: metrics, alerts)
                    │
                    ▼
            Pub/Sub topic "cloudpulse-alerts"
            (real mode) - or logged only (mock mode)
```

## Features

- **Metrics polling** - CPU utilization, memory utilization, request latency via `google-cloud-monitoring`.
- **Mock mode** - synthetic metrics with a random walk + occasional spikes, so alerts and the dashboard can be demoed with no GCP account.
- **Configurable thresholds** - set per-metric limits in `config.yaml`.
- **Pub/Sub alerting** - breaches are published to a Pub/Sub topic when GCP is configured; always recorded in an in-memory alert history either way.
- **Live dashboard** - metric cards and alert history at `/`, auto-refreshing via a small JS polling loop.
- **Structured JSON logging** - every log line is a single JSON object, ready for Cloud Logging.
- **Cloud Run ready** - Dockerfile runs the app under gunicorn, binding to `$PORT`.

## Tech Stack

- **Python 3.10+**, **Flask**
- **google-cloud-monitoring**, **google-cloud-pubsub**
- **PyYAML** for config
- **gunicorn** for production serving
- **Docker** / **Cloud Run**

## Getting Started

### Run locally in mock mode (no GCP setup required)

```bash
cd cloudpulse
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python3 main.py
```

Open http://localhost:8080 - you'll see the dashboard running in **MOCK
MODE**, with synthetic metrics that update on every poll cycle and
occasionally breach the configured thresholds to demonstrate alerting.

### Run against real GCP metrics

1. Set a real project id in `config.yaml`:
   ```yaml
   gcp:
     project_id: "my-real-project"
     pubsub_topic: "cloudpulse-alerts"
   ```
2. Create the Pub/Sub topic (if you want alert publishing):
   ```bash
   gcloud pubsub topics create cloudpulse-alerts
   ```
3. Authenticate locally with Application Default Credentials:
   ```bash
   gcloud auth application-default login
   ```
   If you're using a service account key instead, export
   `GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json` before starting the
   app so the GCP SDK can find it.
4. Run the app - it detects real credentials automatically and switches out of mock mode:
   ```bash
   python3 main.py
   ```

No credentials are ever read from a config file or hardcoded - CloudPulse
relies entirely on `GOOGLE_APPLICATION_CREDENTIALS` / Application Default
Credentials, resolved by the GCP SDK at runtime.

### Configuration (`config.yaml`)

| Key                                | Default                | Description                                    |
|-------------------------------------|-------------------------|-------------------------------------------------|
| `gcp.project_id`                    | *(placeholder)*         | GCP project id. Leave as the placeholder to force mock mode. |
| `gcp.pubsub_topic`                  | `cloudpulse-alerts`     | Pub/Sub topic alerts are published to.          |
| `polling.interval_seconds`          | `15`                    | Seconds between metric polls.                   |
| `thresholds.cpu_utilization_percent`| `80`                    | CPU % above which an alert fires.               |
| `thresholds.memory_utilization_percent` | `85`                | Memory % above which an alert fires.            |
| `thresholds.latency_ms`             | `500`                   | Latency (ms) above which an alert fires.        |
| `alerts.history_size`               | `100`                   | Number of recent alerts kept in memory.         |

Override the config file location with `CLOUDPULSE_CONFIG=/path/to/config.yaml`.

## Usage / API Reference

| Method | Path           | Description                          |
|--------|-----------------|---------------------------------------|
| GET    | `/`             | HTML dashboard                        |
| GET    | `/api/metrics`  | Latest metrics snapshot (JSON)        |
| GET    | `/api/alerts`   | Recent alert history (JSON)           |
| GET    | `/health`       | Liveness check (`{"status": "ok"}`)   |

```bash
curl http://localhost:8080/api/metrics
```

Sample response:

```json
{
  "timestamp": "2026-07-01T11:47:58.812444+00:00",
  "cpu_utilization_percent": 42.1,
  "memory_utilization_percent": 55.3,
  "latency_ms": 210.4,
  "source": "mock"
}
```

```bash
curl http://localhost:8080/api/alerts
# [{"timestamp": "...", "metric": "cpu_utilization_percent", "value": 91.2, "threshold": 80, "message": "..."}]
```

## Deployment to Cloud Run

```bash
# Build and push the image
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/cloudpulse

# Deploy
gcloud run deploy cloudpulse \
  --image gcr.io/YOUR_PROJECT_ID/cloudpulse \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars LOG_LEVEL=INFO
```

Cloud Run injects `$PORT` automatically; the Dockerfile's gunicorn command
binds to it. Grant the Cloud Run service account the `roles/monitoring.viewer`
and `roles/pubsub.publisher` IAM roles if you want real metrics and alert
publishing rather than mock mode.

### Run the container locally

```bash
docker build -t cloudpulse .
docker run -p 8080:8080 cloudpulse
```

## Project Structure

```
cloudpulse/
  app/
    __init__.py    config loader + structured JSON logging setup
    metrics.py      Cloud Monitoring polling + mock fallback
    alerts.py       threshold checks + Pub/Sub publish + history
    dashboard.py    Flask app factory, background poller, routes
  templates/
    index.html      dashboard UI
  config.yaml
  requirements.txt
  Dockerfile
  main.py           entry point (local dev + gunicorn target)
```

## License

MIT
