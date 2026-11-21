# Tuition API image. Build from the repository root:
#   docker build -f api/Dockerfile -t tuition-api .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY api/requirements.txt .
RUN pip install -r requirements.txt

COPY api/app ./app
COPY api/docker-entrypoint.sh /docker-entrypoint.sh

RUN chmod +x /docker-entrypoint.sh \
    && useradd --system --no-create-home appuser
USER appuser

EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=5s --retries=10 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/v1/health')" || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
