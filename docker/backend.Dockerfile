FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy all three packages (backend imports worker via sys.path)
COPY ibkr_show_common/ /app/ibkr_show_common/
COPY ibkr_show_worker/  /app/ibkr_show_worker/
COPY ibkr_show_backend/ /app/ibkr_show_backend/

RUN pip install --no-cache-dir -r /app/ibkr_show_backend/requirements.txt && \
    pip install --no-cache-dir -r /app/ibkr_show_worker/requirements.txt

# Shared data volume mount point
RUN mkdir -p /app/ibkr_show_backend/data/config

ENV PYTHONPATH=/app:/app/ibkr_show_backend:/app/ibkr_show_worker:/app/ibkr_show_common
ENV APP_ENV=production

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
