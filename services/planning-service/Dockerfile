FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl libgomp1 && rm -rf /var/lib/apt/lists/*

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY services/planning-service/requirements.txt .
# BuildKit cache mount: pip's wheel/HTTP cache lives outside the image layers,
# so rebuilds reuse downloads even when the layer itself is invalidated.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --only-binary=:all: -r requirements.txt

COPY services/planning-service/ .
COPY services/_common/ /app/_common/
COPY config/ /app/config/


ARG ART_REVISION=unversioned
ARG ART_SOURCE_DIRTY=true
LABEL org.opencontainers.image.revision=$ART_REVISION
RUN python /app/_common/build_identity.py --service planning-service --revision "$ART_REVISION" --dirty "$ART_SOURCE_DIRTY"
ENV ART_REQUIRE_BUILD_IDENTITY=1

EXPOSE 8009

HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD curl -f http://localhost:8009/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8009"]
