# Multi-stage build using uv for dependency resolution (includes CTP extras)
FROM ghcr.io/ryanflavor/python-uv-build:3.13 AS builder

WORKDIR /app

# Proxy support for builds (optional)
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ENV HTTP_PROXY=${HTTP_PROXY}
ENV HTTPS_PROXY=${HTTPS_PROXY}
ENV NO_PROXY=${NO_PROXY}
ENV http_proxy=${HTTP_PROXY}
ENV https_proxy=${HTTPS_PROXY}
ENV no_proxy=${NO_PROXY}

# Copy project metadata and sources for dependency sync
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

# Sync dependencies with CTP extra to include vn.py bindings
# Use copy mode so resulting virtualenv doesn't depend on uv cache symlinks
ENV UV_LINK_MODE=copy
RUN uv sync --frozen --no-dev --extra ctp

# Remove GUI-heavy optional dependencies from the portable virtualenv
RUN rm -rf \
        /app/.venv/lib/python3.13/site-packages/PySide6 \
        /app/.venv/lib/python3.13/site-packages/PySide6-*.dist-info \
        /app/.venv/lib/python3.13/site-packages/shiboken6 \
        /app/.venv/lib/python3.13/site-packages/shiboken6-*.dist-info \
        /app/.venv/lib/python3.13/site-packages/plotly \
        /app/.venv/lib/python3.13/site-packages/plotly-*.dist-info \
        /app/.venv/lib/python3.13/site-packages/pyqtgraph \
        /app/.venv/lib/python3.13/site-packages/pyqtgraph-*.dist-info \
        /app/.venv/lib/python3.13/site-packages/qdarkstyle \
        /app/.venv/lib/python3.13/site-packages/qdarkstyle-*.dist-info \
        /app/.venv/lib/python3.13/site-packages/talib \
        /app/.venv/lib/python3.13/site-packages/TA_Lib-*.dist-info \
        /app/.venv/lib/python3.13/site-packages/Cython \
        /app/.venv/lib/python3.13/site-packages/Cython-*.dist-info || true

# Strip native extension binaries to shrink runtime footprint
RUN find /app/.venv -type f \( -name '*.so' -o -name '*.a' \) -exec strip --strip-unneeded {} + || true

# Runtime image
FROM python:3.13-slim AS runtime

# Proxy args for runtime installations (optional)
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ENV HTTP_PROXY=${HTTP_PROXY}
ENV HTTPS_PROXY=${HTTPS_PROXY}
ENV NO_PROXY=${NO_PROXY}
ENV http_proxy=${HTTP_PROXY}
ENV https_proxy=${HTTPS_PROXY}
ENV no_proxy=${NO_PROXY}

# Install locale and minimal build utilities needed at runtime (e.g., gb18030)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        locales && \
    (grep -q '^zh_CN.GB18030' /etc/locale.gen || echo 'zh_CN.GB18030 GB18030' >> /etc/locale.gen) && \
    locale-gen zh_CN.GB18030 && \
    rm -rf /var/lib/apt/lists/*

# Create non-root application user
RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g 1000 -m -s /bin/bash appuser

WORKDIR /app

# Copy pre-synced virtual environment from builder stage
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy sources for runtime execution
COPY --chown=appuser:appuser pyproject.toml README.md ./
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser scripts/ ./scripts/

# Runtime environment variables
ENV PYTHONPATH="/app"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Switch to non-root user
USER appuser

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)" || exit 1

ENTRYPOINT ["python", "-m", "src"]
