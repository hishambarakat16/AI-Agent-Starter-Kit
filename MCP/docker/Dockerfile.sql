FROM python:3.12-slim

WORKDIR /workspace
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv

COPY MCP/docker/requirements-mcp.txt /workspace/requirements-mcp.txt

RUN uv venv
RUN uv pip install --system -r /workspace/requirements-mcp.txt

COPY app /workspace/app
COPY MCP /workspace/MCP

ENV PYTHONPATH=/workspace

EXPOSE 8051

# CMD ["python", "-m", "MCP.server.sql_server"]
