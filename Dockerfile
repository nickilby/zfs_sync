# Build stage
FROM python:3.12-slim as builder

# Set working directory
WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --user -r requirements.txt

# Runtime stage
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security (UID/GID 1001 to match host user)
RUN groupadd -r -g 1001 zfssync && useradd -r -g zfssync -u 1001 zfssync

# Copy Python dependencies from builder
COPY --from=builder /root/.local /home/zfssync/.local

# Copy application code
COPY --chown=zfssync:zfssync . .

# Create directories for config, logs, and data with proper permissions
RUN mkdir -p /config /logs /data && \
    chown -R zfssync:zfssync /app /config /logs /data

# Make sure scripts in .local are usable
ENV PATH=/home/zfssync/.local/bin:$PATH

# Switch to non-root user
USER zfssync

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# Default command (will be overridden by docker-compose or runtime)
CMD ["python", "-m", "uvicorn", "zfs_sync.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

