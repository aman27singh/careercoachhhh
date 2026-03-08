# ── Build stage ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Install only what pip needs to resolve packages
RUN pip install --upgrade pip

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Copy installed packages from the builder layer
COPY --from=builder /install /usr/local

# Copy application source
COPY app/      ./app/
COPY scripts/  ./scripts/

# ── Environment variables ─────────────────────────────────────────────────────
# These can be overridden at `docker run` time or via ECS task-definition env:
ENV AWS_REGION=us-east-1 \
    OPENSEARCH_ENDPOINT="" \
    OPENSEARCH_INDEX="careercoach-docs" \
    OPENSEARCH_VECTOR_FIELD="embedding" \
    OPENSEARCH_TEXT_FIELD="text" \
    DYNAMODB_TABLE="careercoach-users" \
    PORT=8000

EXPOSE 8000

# Production start command – no --reload in production
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
