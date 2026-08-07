FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
# BuildKit cache mount: pip's wheel/HTTP cache lives outside the image layers,
# so rebuilds reuse downloads even when the layer itself is invalidated.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --only-binary=:all: -r requirements.txt

COPY . .

EXPOSE 8005

HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
  CMD curl -f http://localhost:${PORT:-8005}/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8005"]
