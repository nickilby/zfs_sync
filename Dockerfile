FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories for config, logs, and data
RUN mkdir -p /config /logs /data

# Expose port
EXPOSE 8000

# Default command (will be overridden by docker-compose or runtime)
CMD ["python", "-m", "uvicorn", "zfs_sync.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

