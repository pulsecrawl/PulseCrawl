FROM python:3.13.16-slim-bookworm@sha256:55e31428469cbd0e20d52b2b514e8ec20ca4742254ed2b9dbe0f0b2d39cc2d65

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
