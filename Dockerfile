# Public Hub demo. Python serves the pages; node transpiles the JSX once at boot.
FROM python:3.14-slim
RUN apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY . .
ENV DEMO_MODE=1 VAULT_PATH=/app/demo-vault PYTHONDONTWRITEBYTECODE=1 PORT=10000
WORKDIR /app/dashboard/hub
# ponytail: one worker, since the reset lock and the JSX cache are per process.
CMD exec gunicorn -w 1 --threads 8 -b 0.0.0.0:$PORT app:app
