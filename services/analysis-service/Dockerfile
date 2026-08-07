FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl libgomp1 && rm -rf /var/lib/apt/lists/*

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
# CPU-only torch: stable-baselines3 pulls torch, and PyPI's default build bundles
# the ~2.5 GB CUDA runtime. Pinning the +cpu wheel keeps this image ~6 GB smaller.
# BuildKit cache mount: pip's wheel/HTTP cache lives outside the image layers,
# so rebuilds reuse downloads even when the layer itself is invalidated.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install "torch==2.13.0+cpu" --extra-index-url https://download.pytorch.org/whl/cpu
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --only-binary=:all: -r requirements.txt

COPY . .

EXPOSE 8007

HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD curl -f http://localhost:8007/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8007"]
