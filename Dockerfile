# Cloud Run ready image for CloudPulse.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
EXPOSE 8080

# Cloud Run sets $PORT; gunicorn binds to it directly (see CMD below).
CMD exec gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 8 --timeout 0 main:app
