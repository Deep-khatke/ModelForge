FROM python:3.11-slim

WORKDIR /app

# Install security and build dependencies if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .

# Create unprivileged user for security
RUN useradd -u 1000 -m modelforge && chown -R modelforge:modelforge /app
USER modelforge

# Expose container HTTP port
EXPOSE 8000

# Container healthcheck
HEALTHCHECK --interval=5s --timeout=3s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Launch uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
