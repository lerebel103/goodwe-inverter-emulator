FROM python:3.14-slim

WORKDIR /app

LABEL org.opencontainers.image.title="GoodWe ET Inverter Emulator"
LABEL org.opencontainers.image.description="Aggregates EM540 bridge, Fronius Symo and Victron GX data and emulates GoodWe ET over Modbus/TCP"
LABEL org.opencontainers.image.url="https://github.com/lerebel103/goodwe-et-inverter-emulator"
LABEL org.opencontainers.image.source="https://github.com/lerebel103/goodwe-et-inverter-emulator"
LABEL org.opencontainers.image.vendor="lerebel103"
LABEL org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN groupadd -r appuser && useradd -r -g appuser appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

ARG VERSION=dev
ENV GOODWE_EMULATOR_VERSION=${VERSION}

RUN chown -R appuser:appuser /app

EXPOSE 8899

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ps aux | grep -v grep | grep -q 'python -m app' || exit 1

USER appuser
ENV PYTHONPATH=/app
CMD ["python", "-m", "app", "--config", "/etc/goodwe-emulator/config.yaml"]
