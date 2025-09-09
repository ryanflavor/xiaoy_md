# Multi-stage build for optimized Docker image
# Stage 1: Build stage for dependency installation
FROM ghcr.io/ryanflavor/python-uv-build:3.13 AS builder

# Set proxy for uv if provided as build arg (inherited from base)
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ENV HTTP_PROXY=${HTTP_PROXY}
ENV HTTPS_PROXY=${HTTPS_PROXY}
ENV NO_PROXY=${NO_PROXY}
ENV http_proxy=${HTTP_PROXY}
ENV https_proxy=${HTTPS_PROXY}
ENV no_proxy=${NO_PROXY}

# Copy project files for uv installation
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

# Install dependencies using uv (faster and better pyproject.toml support)
RUN uv sync --frozen

# Stage 2: Runtime stage
FROM python:3.13-slim AS runtime

# Create non-root user for security
RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g 1000 -m -s /bin/bash appuser

# Set working directory
WORKDIR /app

# Copy installed dependencies from builder stage
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

# Copy application code
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser scripts/ ./scripts/

# Set Python path to include virtual environment
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"
# Keep proxy envs in runtime if provided (optional)
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ENV HTTP_PROXY=${HTTP_PROXY}
ENV HTTPS_PROXY=${HTTPS_PROXY}
ENV NO_PROXY=${NO_PROXY}
ENV http_proxy=${HTTP_PROXY}
ENV https_proxy=${HTTPS_PROXY}
ENV no_proxy=${NO_PROXY}
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Switch to non-root user
USER appuser

# Health check for container orchestration
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)" || exit 1

# Set entry point to run the application
# Use module execution for the package entrypoint
ENTRYPOINT ["python", "-m", "src"]
