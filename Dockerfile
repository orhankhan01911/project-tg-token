FROM python:3.12-slim

WORKDIR /app

# Build deps for cryptography / cffi
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev libssl-dev && \
    rm -rf /var/lib/apt/lists/*

# Install uv (fast pip replacement)
RUN pip install --no-cache-dir uv

# Copy manifest first so Docker can cache the dep layer
COPY pyproject.toml ./
COPY app/ ./app/

# Install runtime deps only (no dev extras)
RUN uv pip install --system --no-cache -e .

# Non-root user for safety
RUN useradd -m -u 1001 botuser && chown -R botuser:botuser /app
USER botuser

CMD ["python", "-m", "app"]
