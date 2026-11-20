FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY services/sim-orchestrator/requirements.txt .
# BuildKit cache mount: pip's wheel/HTTP cache lives outside the image layers,
# so rebuilds reuse downloads even when the layer itself is invalidated.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --only-binary=:all: -r requirements.txt

COPY services/sim-orchestrator/ .
COPY services/_common/ /app/_common/
COPY config/ /app/config/

# Fixed packaging tools: keep inherited base-image advisories out of runtime.
RUN pip install --no-cache-dir --only-binary=:all: pip==26.2.1 setuptools==83.0.0


ARG ART_REVISION=unversioned
ARG ART_SOURCE_DIRTY=true
LABEL org.opencontainers.image.revision=$ART_REVISION
RUN python /app/_common/build_identity.py --service sim-orchestrator --revision "$ART_REVISION" --dirty "$ART_SOURCE_DIRTY"
ENV ART_REQUIRE_BUILD_IDENTITY=1

EXPOSE 8006

HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
  CMD curl -f http://localhost:${PORT:-8006}/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8006"]
