FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install uv for faster package management
RUN pip install --no-cache-dir uv

# Copy requirements and install deps into a venv managed by uv
COPY requirements_app.txt .

RUN uv venv
ENV PATH="/app/.venv/bin:$PATH"
RUN uv pip install -r requirements_app.txt

# Copy application code
COPY app ./app

EXPOSE 8000

