# api.py
# Flask-based Enrichment API with Prometheus metrics and structured logging

import os
import time
import json
import logging
from logging import StreamHandler
from flask import Flask, jsonify, request
from prometheus_client import generate_latest, Counter, Histogram, CONTENT_TYPE_LATEST

APP_NAME = "enrichment-api"
APP_VERSION = os.environ.get("APP_VERSION", "v1.0.0")

app = Flask(__name__)

# -------- Structured logging (JSON) ----------
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "app": APP_NAME,
            "version": APP_VERSION,
        }
        if record.exc_info:
            log_record["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(log_record)

handler = StreamHandler()
handler.setFormatter(JsonFormatter())
app.logger.handlers = []
app.logger.addHandler(handler)
app.logger.setLevel(logging.INFO)

# -------- Prometheus metrics (RED) ----------
REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP Requests", ["method", "endpoint", "status"]
)
API_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP Request Duration", ["endpoint"]
)

@app.route("/")
@API_LATENCY.labels(endpoint="/").time()
def index():
    REQUEST_COUNT.labels(method="GET", endpoint="/", status="200").inc()
    return jsonify({"message": "Hello from the Enrichment API!", "version": APP_VERSION}), 200

@app.route("/healthz")
def healthz():
    # Lightweight check used by liveness/readiness probes
    return "ok", 200

@app.route("/enrich", methods=["POST"])
@API_LATENCY.labels(endpoint="/enrich").time()
def enrich():
    data = request.get_json(silent=True) or {}
    tx_id = data.get("transactionId")
    if not tx_id:
        REQUEST_COUNT.labels(method="POST", endpoint="/enrich", status="400").inc()
        return jsonify({"error": "Missing transactionId"}), 400

    # Simulate work (e.g., enrichment call)
    time.sleep(0.05)

    REQUEST_COUNT.labels(method="POST", endpoint="/enrich", status="200").inc()
    return jsonify({"enriched_transaction": f"Enriched transaction {tx_id}"}), 200

@app.route("/metrics")
def metrics():
    # Expose Prometheus metrics
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
