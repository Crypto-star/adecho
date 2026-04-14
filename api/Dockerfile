# Troopod API — Python + Playwright Chromium
#
# Base: Microsoft's official Playwright Python image (Chromium pre-installed,
# all Linux deps present). Saves ~2-3 minutes of cold-start install time.
FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    LOG_TO_STDOUT=1

# Install Python deps first so requirements changes don't bust the Chromium layer.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Reinstall Chromium with --with-deps to ensure no missing shared libs
# (playwright image has Chromium already; this is belt-and-suspenders).
RUN python -m playwright install --with-deps chromium

# Application code (app/ only — tests, logs, venv, .env are .dockerignore'd).
COPY app ./app

# Railway sets PORT; locally defaults to 8000.
ENV PORT=8000
EXPOSE 8000

# Single worker — pipeline is I/O-bound and has in-memory state; Railway
# auto-scales horizontally by spawning more instances if needed.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
