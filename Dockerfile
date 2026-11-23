FROM python:3.15.2-slim-bookworm@sha256:96599df822d0e1c6bb700014a05c7f3c8cabc6e0f7ff3c4f9f69cee033b4b5d9

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
