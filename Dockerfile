# ==========================================
# SMARTTT Backend Production Dockerfile
# ==========================================
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    netcat-traditional \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//g' /entrypoint.sh && \
    chmod +x /entrypoint.sh

# Copy project source code
COPY . /app/

# Collect (and compress) static files at build time so container startup
# stays well inside the platform's healthcheck window
RUN DJANGO_SETTINGS_MODULE=config.settings.production python manage.py collectstatic --noinput

# Create non-root user and setup directories with appropriate permissions
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/staticfiles /app/media && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose Django Gunicorn port
EXPOSE 8000

# Set entrypoint
ENTRYPOINT ["/entrypoint.sh"]

# Default command to run with Gunicorn
# Shell form so $PORT (injected by Railway and similar hosts) is honoured; defaults to 8000
CMD gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers ${WEB_CONCURRENCY:-3} --timeout 120 --access-logfile - --error-logfile -
