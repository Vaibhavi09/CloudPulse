"""CloudPulse entry point.

Local dev:   python main.py
Production:  gunicorn --bind 0.0.0.0:8080 main:app   (see Dockerfile)
"""
import os

from app import configure_logging, load_config
from app.dashboard import create_app

configure_logging()
app = create_app(load_config())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
