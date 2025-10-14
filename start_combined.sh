#!/bin/bash
# Combined startup script for Render free tier
# Runs both Flask web server and Celery worker in the same container

# Start Celery worker in the background
celery -A celery_config worker --loglevel=info --concurrency=2 &

# Start Gunicorn web server in the foreground
exec gunicorn wsgi:app --workers 2 --timeout 120 --bind 0.0.0.0:${PORT:-10000}
