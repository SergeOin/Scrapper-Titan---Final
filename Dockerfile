# ==============================================
# Base image with Python and system deps for Playwright
# ==============================================
FROM mcr.microsoft.com/playwright/python:v1.46.0-jammy AS base

# Prevent Python from writing .pyc and enable stdout flushing
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system packages (minimal; playwright base already has browsers deps)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       curl tzdata dumb-init \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ==============================================
# Builder stage for dependency caching
# ==============================================
FROM base AS builder

# Copy only requirements first for better layer caching
COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install --prefix=/install -r requirements.txt

# ==============================================
# Runtime image
# ==============================================
FROM base AS runtime

# Create non-root user
RUN useradd -ms /bin/bash appuser

# Copy installed dependencies from builder
COPY --from=builder /install /usr/local

# Create required directories
RUN mkdir -p logs screenshots traces exports server/templates \
    && chown -R appuser:appuser /app

# Copy project files
COPY . .

# Adjust permissions
RUN chown -R appuser:appuser /app

USER appuser

# Expose default port
EXPOSE 8000

# Healthcheck (simple HTTP ping)
HEALTHCHECK --interval=30s --timeout=5s --retries=5 CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# Default environment (can be overridden)
ENV PLAYWRIGHT_HEADLESS=1 \
    SCRAPING_ENABLED=1 \
    LOG_LEVEL=INFO

# Entrypoint script uses dumb-init for proper signal handling
ENTRYPOINT ["dumb-init", "python", "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Alternative run examples:
# docker run --rm --env-file .env linkedin-scraper python -m scraper.worker
# docker run --rm --env-file .env linkedin-scraper python scripts/run_once.py --keywords "python;ai"

# ==============================================
# Notes:
# - Browsers already installed with the playwright base image.
# - If you add heavy deps (e.g., pandas), ensure layer caching by editing only requirements.
# - For multi-service deploy, run a separate container for worker vs API.
# ==============================================
