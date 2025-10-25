web: gunicorn wsgi:app --workers 2 --timeout 120 --log-file - --max-requests 1000 --max-requests-jitter 50
worker: celery -A celery_config worker --loglevel=info --concurrency=2 --max-tasks-per-child=50
beat: celery -A celery_config beat --loglevel=info
