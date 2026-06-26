FROM python:3.11-slim

WORKDIR /app

# Install system dependencies needed by some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project definition first so pip cache is reused when only code changes
COPY pyproject.toml ./

# Install runtime dependencies (no dev extras in production image)
RUN pip install --no-cache-dir -e "."

# Copy source
COPY . .

# Default: start the FastAPI serving layer
CMD ["uvicorn", "serving.main:app", "--host", "0.0.0.0", "--port", "8000"]
