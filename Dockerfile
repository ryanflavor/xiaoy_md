# Multi-stage build for optimized Docker image
# Stage 1: Build stage for dependency installation
FROM python:3.13-slim AS builder

# Set working directory
WORKDIR /app

# Set proxy for pip if provided as build arg
ARG HTTP_PROXY
ARG HTTPS_PROXY
ENV HTTP_PROXY=${HTTP_PROXY}
ENV HTTPS_PROXY=${HTTPS_PROXY}

# Install uv package manager (pinned version for reproducibility)
RUN pip install --no-cache-dir uv==0.5.13

# Copy dependency files for installation
COPY pyproject.toml uv.lock ./
# Copy README.md needed by hatchling build
COPY README.md ./

# Install dependencies using uv
RUN uv sync --frozen --no-dev

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
ENV PYTHONPATH="/app:$PYTHONPATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Switch to non-root user
USER appuser

# Health check for container orchestration
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)" || exit 1

# Set entry point to run the application
ENTRYPOINT ["python", "-m", "src"]
