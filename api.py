# A simple Flask-based transaction enrichment API
# We'll use this to demonstrate Kubernetes features like health checks and scaling.
import os
from flask import Flask, jsonify, request
from prometheus_client import generate_latest, Counter, Histogram

app = Flask(__name__)

# Prometheus metrics for RED (Rate, Errors, Duration)
REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP Requests', ['method', 'endpoint', 'status'])
API_LATENCY_HIST = Histogram('http_request_duration_seconds', 'HTTP Request Duration', ['endpoint'])

@app.route('/')
@API_LATENCY_HIST.labels(endpoint='/').time()
def index():
    """A basic endpoint for the API."""
    REQUEST_COUNT.labels(method='GET', endpoint='/', status='200').inc()
    return jsonify({"message": "Hello from the Enrichment API!"}), 200

@app.route('/healthz')
def healthz():
    """Liveness and readiness probe endpoint."""
    return 'ok', 200

@app.route('/enrich', methods=['POST'])
@API_LATENCY_HIST.labels(endpoint='/enrich').time()
def enrich():
    """An endpoint that simulates a transaction enrichment."""
    data = request.get_json()
    if not data or 'transactionId' not in data:
        REQUEST_COUNT.labels(method='POST', endpoint='/enrich', status='400').inc()
        return jsonify({"error": "Missing transactionId"}), 400
    
    # Simulate some work
    import time
    time.sleep(0.1)

    REQUEST_COUNT.labels(method='POST', endpoint='/enrich', status='200').inc()
    return jsonify({"enriched_transaction": f"Enriched transaction {data['transactionId']}"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=os.environ.get('PORT', 8080))
