# Blocco 6 — the web service: FastAPI API + the built React frontend, one
# process. Built by Render from render.yaml; locally:
#   docker build -f deploy/web.Dockerfile -t vo-web .

# 1. Frontend
FROM node:22-slim AS frontend
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# 2. API (+ the built frontend)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
# Editable on purpose: config.py resolves config/ and data/ relative to the
# source tree (ROOT = src/..), which a regular site-packages install breaks.
RUN pip install -e ".[webapi,postgres]"
# Seed data: the demo family and its knowledge, copied into the database on
# first start (shared mode); the YAML stays the fallback.
COPY config ./config
COPY data/knowledge ./data/knowledge
COPY --from=frontend /web/dist ./web/dist
RUN useradd --create-home app && chown -R app /app
USER app
EXPOSE 8000
# Render sets $PORT; --proxy-headers so the app sees https behind its proxy
# (the owner session cookie is marked Secure from that).
CMD ["sh", "-c", "uvicorn voice_orchestrator.webapi.app:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
