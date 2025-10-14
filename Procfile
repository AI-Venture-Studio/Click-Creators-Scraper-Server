web: gunicorn wsgi:app --workers 4 --timeout 120 --log-file -
worker: celery -A celery_config worker --loglevel=info --concurrency=4
beat: celery -A celery_config beat --loglevel=info
