FROM python:3.11-slim

WORKDIR /app

# Install system utilities & database client libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY storage/ ./storage/

# Ensure storage directories exist and configure unprivileged user
RUN mkdir -p /app/storage/models && \
    useradd -u 1000 -m modelforge && \
    chown -R modelforge:modelforge /app

USER modelforge

# Expose backend API port
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD curl -f http://localhost:8000/api/health || exit 1

# Launch FastAPI application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
