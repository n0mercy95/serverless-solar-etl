# ==========================================
# Stage 1: Build & Dependencies
# ==========================================
FROM python:3.11-slim-bullseye AS builder

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1

# Install required build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for deterministic dependency resolution
RUN pip install uv

WORKDIR /app

# Copy dependency definition
COPY requirements.txt .

# Install dependencies using uv into the system site-packages
RUN uv pip install --system -r requirements.txt

# ==========================================
# Stage 2: Runtime Environment
# ==========================================
FROM python:3.11-slim-bullseye AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

# Create a non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy source code
COPY ./src /app/src

# Change ownership to non-root user
RUN chown -R appuser:appuser /app

# Run as non-root
USER appuser

# Expose port (Cloud Run standard)
EXPOSE 8080

# Execute FastAPI via uvicorn
ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
