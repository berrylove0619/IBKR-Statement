FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Worker needs ibkr_show_backend for shared data/config volume path resolution
COPY ibkr_show_common/ /app/ibkr_show_common/
COPY ibkr_show_backend/ /app/ibkr_show_backend/
COPY ibkr_show_worker/  /app/ibkr_show_worker/

RUN pip install --no-cache-dir -r /app/ibkr_show_worker/requirements.txt && \
    pip install --no-cache-dir -r /app/ibkr_show_backend/requirements.txt

COPY docker/entrypoint-worker-init.sh /app/docker/entrypoint-worker-init.sh
RUN chmod +x /app/docker/entrypoint-worker-init.sh

RUN mkdir -p /app/ibkr_show_backend/data/config

ENV PYTHONPATH=/app:/app/ibkr_show_worker:/app/ibkr_show_backend:/app/ibkr_show_common
ENV APP_ENV=production

CMD ["python", "-m", "worker.main", "run-scheduler"]
