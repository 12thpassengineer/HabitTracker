# AdatTracker Pro - Production Non-Root Container
FROM python:3.11-slim

# Create unprivileged application user & group (UID 1001)
RUN groupadd -r adattracker --gid 1001 && \
    useradd -r -g adattracker --uid 1001 --create-home adattracker

WORKDIR /app

# Install dependencies
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application backend & frontend
COPY backend/ ./
COPY frontend/index.html ./frontend/index.html
COPY frontend/index.html ./habit_tracker.html

# Setup data directory with non-root ownership
RUN mkdir -p /app/data && \
    chown -R adattracker:adattracker /app

# Switch to unprivileged user
USER adattracker

# Expose internal port
EXPOSE 8000

ENV PORT=8000
ENV HOST=0.0.0.0
ENV APP_ENV=production
ENV DATA_DIR=/app/data

# Container Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["python", "server.py"]
