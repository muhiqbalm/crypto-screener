# ============================================================
# Crypto Screener API — Production Docker Image
# ============================================================
# Multi-stage build for minimal image size.
# Stage 1: install Python dependencies
# Stage 2: copy only the runtime artifacts
# ============================================================

# --------------- Stage 1: Builder ---------------
FROM python:3.12-slim AS builder

WORKDIR /build

# Install only production dependencies into a virtual-env
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && . /opt/venv/bin/activate \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# --------------- Stage 2: Runtime ---------------
FROM python:3.12-slim AS runtime

# Prevent Python from writing .pyc files and enable unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Copy virtual-env from builder stage
COPY --from=builder /opt/venv /opt/venv

# Copy application source code
COPY src/ ./src/
COPY main_api.py .

# Install gosu for privilege de-escalation in entrypoint
# Create non-root user for security
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid 1000 --no-create-home appuser \
    && mkdir -p /app/output/logs /app/output/dashboards \
    && chown -R appuser:appuser /app

# Copy entrypoint script (runs as root to fix volume permissions, then drops to appuser)
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Expose the default API port
EXPOSE 8000

# Health check — polls the /api/v1/health endpoint every 30s
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1

# Use entrypoint to fix permissions before dropping to appuser
ENTRYPOINT ["docker-entrypoint.sh"]

# Run the API server via Uvicorn with sensible production defaults
CMD ["uvicorn", "src.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--access-log"]
