# Dockerfile
FROM python:3.11-slim

# System prep: non-root user
RUN addgroup --gid 1001 appgroup \
 && adduser --uid 1001 --gid 1001 --home /app --shell /bin/sh --disabled-password appuser

WORKDIR /app

# Leverage Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Permissions
RUN chown -R appuser:appgroup /app

ENV PORT=8080 \
    APP_VERSION=v1.0.0 \
    PYTHONUNBUFFERED=1

EXPOSE 8080
USER appuser

# Gunicorn: 2 workers + 2 threads per core-ish is fine for demo; tune for prod
# Timeout short to surface probe issues quickly; keepalive reduces LB churn.
CMD ["gunicorn", "-w", "2", "--threads", "2", "-b", "0.0.0.0:8080", "--timeout", "30", "--keep-alive", "5", "api:app"]
