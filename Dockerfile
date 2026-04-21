FROM python:3.12-slim

WORKDIR /app

# poppler-utils: required by pdf2image for PDF-to-image conversion
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies as a separate layer so code changes don't bust the cache
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# Application code
COPY . .

# Persistent upload storage (overridden by a named volume in compose)
RUN mkdir -p /app/uploads

EXPOSE 8000

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
