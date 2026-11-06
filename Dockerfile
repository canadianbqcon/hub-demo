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
# Transpile every .jsx now: the free instance's 512 MB cannot hold node at runtime.
RUN python -c "import json,jsx_build as j;fs=[f for f in j.HUB.rglob('*.jsx') if 'node_modules' not in f.parts];json.dump({str(f.resolve()):j.transpile(f) for f in fs},open('/app/jsx-cache.json','w'))"
# ponytail: one worker, since the reset lock and the JSX cache are per process.
# --timeout 120: the free tier's slow CPU can take past the 30 s default to boot.
CMD exec gunicorn -w 1 --threads 8 --timeout 120 -b 0.0.0.0:$PORT app:app
