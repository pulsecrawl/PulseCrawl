FROM python:3.15.0-slim-bookworm@sha256:0e019bbdfb5d9874cb2389f1c2884b64aa2ac97c99960b5bc521cef978c0617d

LABEL org.opencontainers.image.source="https://github.com/pulsecrawl/PulseCrawl" \
      org.opencontainers.image.description="PulseCrawl local workspace scheduler" \
      org.opencontainers.image.licenses="AGPL-3.0-only"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/pulsecrawl
COPY . /opt/pulsecrawl/package
RUN python -m pip install --no-cache-dir --upgrade "pip==26.2.1" \
    && python -m pip install --no-cache-dir \
      --constraint /opt/pulsecrawl/package/requirements-workspace.txt \
      '/opt/pulsecrawl/package[workspace]'

RUN useradd --create-home --uid 10001 pulsecrawl \
    && mkdir -p /workspace \
    && chown pulsecrawl:pulsecrawl /workspace
USER pulsecrawl

ENTRYPOINT ["pulsecrawl"]
CMD ["--workspace", "/workspace", "schedule", "start"]
