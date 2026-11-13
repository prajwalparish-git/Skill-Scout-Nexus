# Backend only: server.py (FastAPI) for the Next.js front end. The Streamlit app (app.py) is
# not served from this image; deploy the frontend separately (see README.md > Deployment).
FROM python:3.13-slim

WORKDIR /app

# System packages: none needed — psycopg[binary] bundles libpq, and every other dependency in
# requirements.txt is pure Python or ships its own wheel.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render (and most PaaS hosts) inject PORT at runtime; 8000 is only the local-run fallback.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
