"""
Celery configuration for background task processing.
"""
import os
from celery import Celery
from kombu import Exchange, Queue

# Initialize Celery
celery = Celery('instagram_scraper')

# Redis configuration from Heroku or local
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

# SSL/TLS settings for secure Redis connections
broker_use_ssl = None
redis_backend_use_ssl = None

# Heroku Redis URLs use 'redis://' but SSL is required in production
if redis_url.startswith('redis://') and 'localhost' not in redis_url:
    redis_url = redis_url.replace('redis://', 'rediss://')
    # Configure SSL for secure Redis (rediss://)
    import ssl
    broker_use_ssl = {
        'ssl_cert_reqs': ssl.CERT_NONE  # Don't verify SSL certificates (Render managed Redis)
    }
    redis_backend_use_ssl = broker_use_ssl

# Celery configuration
celery.conf.update(
    broker_url=redis_url,
    result_backend=redis_url,
    broker_use_ssl=broker_use_ssl,
    redis_backend_use_ssl=redis_backend_use_ssl,
    
    # Task settings
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    timezone='UTC',
    enable_utc=True,
    
    # Task execution limits
    task_time_limit=7200,  # 2 hours hard limit
    task_soft_time_limit=6900,  # 1h 55m soft limit
    worker_max_tasks_per_child=50,  # Restart worker after 50 tasks (memory management)
    
    # Retry settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    
    # Result backend settings
    result_expires=86400,  # Results expire after 24 hours
    result_persistent=True,
    
    # Task routing
    task_default_queue='default',
    task_queues=(
        Queue('default', Exchange('default'), routing_key='default'),
        Queue('scraping', Exchange('scraping'), routing_key='scraping'),
        Queue('processing', Exchange('processing'), routing_key='processing'),
    ),
    
    # Connection settings
    broker_connection_retry_on_startup=True,
    broker_pool_limit=10,
)

# Export celery app
celery_app = celery
