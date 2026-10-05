# Blocco 6 — the LiveKit voice worker. Reads the agent family, tools and
# knowledge from the shared database at every call. Locally:
#   docker build -f deploy/worker.Dockerfile -t vo-worker .
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
# Editable for the same reason as web.Dockerfile (config.py's ROOT).
RUN pip install -e ".[voice,webapi,postgres]"
COPY config ./config
COPY data/knowledge ./data/knowledge
RUN useradd --create-home app && chown -R app /app
USER app
# Model files (Silero VAD, turn detector) baked into the image, so a call
# never waits on a download.
RUN python -m livekit.agents download-files
CMD ["python", "-m", "voice_orchestrator.voice.worker", "start"]
