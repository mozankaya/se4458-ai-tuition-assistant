# MCP policy search server image. Build from the repository root (the policy document lives in docs/):
#   docker build -f mcp_server/Dockerfile -t tuition-mcp .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8001 \
    POLICY_DOCUMENT_PATH=/app/docs/University_Tuition_Policies.md

WORKDIR /app/mcp_server

COPY mcp_server/requirements.txt .
RUN pip install -r requirements.txt

COPY mcp_server/server.py ./server.py
COPY mcp_server/policy_search ./policy_search
COPY docs/University_Tuition_Policies.md /app/docs/University_Tuition_Policies.md

RUN useradd --system --no-create-home appuser
USER appuser

EXPOSE 8001
HEALTHCHECK --interval=10s --timeout=5s --retries=10 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')" || exit 1

CMD ["python", "server.py"]
