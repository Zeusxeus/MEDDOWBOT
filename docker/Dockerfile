# Use python:3.12-slim-bookworm as base image
FROM python:3.12-slim-bookworm

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Create non-root user
RUN groupadd -r botgroup && useradd -r -g botgroup botuser

# Add .venv/bin to PATH
ENV PATH="/app/.venv/bin:$PATH"

# Create necessary directories and set permissions
RUN mkdir -p /tmp/bot /app/data/cookies /app/data/downloads /app/data/temp \
    && chown -R botuser:botgroup /tmp/bot /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies (frozen to lockfile, without dev dependencies)
RUN uv sync --frozen --no-dev

# Copy project files
COPY . .

# Ensure permissions for botuser
RUN chown -R botuser:botgroup /app

# Switch to non-root user
USER botuser

# Expose port 8080 (bot server)
EXPOSE 8080

# Default command (can be overridden in docker-compose)
CMD ["python", "-m", "bot.main"]
