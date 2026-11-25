# Multi-stage production container for Skill Scout Nexus:
# Stage 1: Build the Next.js static export
FROM node:24-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
# No install scripts yet: postinstall needs frontend/scripts, which is copied next. The build's
# prebuild step then runs them (MediaPipe model and voice-detection files).
RUN npm ci --ignore-scripts
COPY frontend/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# Stage 2: Serve API and static frontend unified via FastAPI on port 8000
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

# Only what the API needs at runtime (tests, docs, scripts and the web app's source stay out).
COPY server.py ./
COPY routers/ ./routers/
COPY piq/ ./piq/
COPY core/ ./core/
COPY agents/ ./agents/
COPY database/ ./database/
COPY data/ ./data/
COPY static/ ./static/

# Copy static frontend export from Stage 1
COPY --from=frontend-builder /app/frontend/out ./frontend/out

# Render (and most PaaS hosts) inject PORT at runtime; 8000 is the unified single-port default.
ENV PORT=8000
EXPOSE 8000

# Health check against unified FastAPI server
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/api/health', timeout=4)"

# exec: uvicorn replaces the shell, so it receives the host's SIGTERM and shuts down cleanly.
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
