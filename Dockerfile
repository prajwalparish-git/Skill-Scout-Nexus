# Backend only: server.py (FastAPI) for the Next.js front end. The Streamlit app (app.py) is
# not served from this image; deploy the frontend separately (see README.md > Deployment).
FROM python:3.13-slim

# Logs reach the host at once (no buffering), and no .pyc files are written at runtime.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System packages: none needed — psycopg[binary] bundles libpq, and every other dependency in
# requirements.txt is pure Python or ships its own wheel. Requirements first, so code changes
# reuse the cached dependency layer.
COPY requirements.txt .
RUN pip install -r requirements.txt

# .dockerignore keeps local databases, caches, secrets and the frontend out of the image.
COPY . .

# Render (and most PaaS hosts) inject PORT at runtime; 8000 is only the local-run fallback.
ENV PORT=8000
EXPOSE 8000

# The same check render.yaml's healthCheckPath runs, for `docker run` and compose (stdlib only:
# the slim image has no curl).
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/api/health', timeout=4)"

# exec: uvicorn replaces the shell, so it receives the host's SIGTERM and shuts down cleanly.
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
