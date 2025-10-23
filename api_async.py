"""
Async API endpoints for Instagram scraping system.
This module contains refactored endpoints that use Celery background tasks.
"""
import os
import uuid
import logging
from typing import Dict, Any
from datetime import datetime, timezone
from flask import jsonify, request
from celery import chord

from tasks import (
    scrape_account_batch,
    aggregate_scrape_results,
    ingest_profiles_batch,
    daily_pipeline_orchestrator
)
from utils.base_id_utils import get_base_id_from_request, validate_base_id, get_default_base_id

logger = logging.getLogger(__name__)


def register_async_endpoints(app, get_supabase_client):
    """
    Register async endpoints to Flask app.
    
    Args:
        app: Flask application instance
        get_supabase_client: Function to get Supabase client
    """
    
    @app.route('/api/scrape-followers', methods=['POST'])
    def scrape_followers_async():
        """
        ASYNC: Queue Instagram follower scraping job.
        
        Expected JSON payload:
        {
            "accounts": ["username1", "username2", ...],
            "targetGender": "male" (optional, defaults to "male"),
            "totalScrapeCount": 150 (optional, total accounts to scrape),
            "base_id": "appXYZ123ABC" (optional, defaults to 'default_instagram')
        }
        
        OR pass base_id via header:
        X-Base-Id: appXYZ123ABC
        
        Returns:
        {
            "success": true,
            "job_id": "uuid",
            "base_id": "appXYZ123ABC",
            "status_url": "/api/job-status/uuid",
            "results_url": "/api/job-results/uuid",
            "message": "Job queued successfully. Poll status_url for progress."
        }
        """
        try:
            # Get JSON data from request
            data = request.get_json()
            
            if not data or 'accounts' not in data:
                return jsonify({
                    'success': False,
                    'error': 'Missing "accounts" field in request body'
                }), 400
            
            accounts = data['accounts']
            target_gender = data.get('targetGender', 'male')
            total_scrape_count = data.get('totalScrapeCount', None)
            
            if not isinstance(accounts, list) or len(accounts) == 0:
                return jsonify({
                    'success': False,
                    'error': 'Accounts must be a non-empty list'
                }), 400
            
            # Extract base_id with fallback to default
            base_id = get_base_id_from_request()
            
            if not validate_base_id(base_id):
                return jsonify({
                    'success': False,
                    'error': f'Invalid base_id format: {base_id}'
                }), 400
            
            # Compute per-account scrape count
            if total_scrape_count is not None:
                if total_scrape_count <= 0:
                    return jsonify({
                        'success': False,
                        'error': 'totalScrapeCount must be positive'
                    }), 400
                
                per_account_count = int(total_scrape_count / len(accounts))
                
                if per_account_count == 0:
                    return jsonify({
                        'success': False,
                        'error': 'totalScrapeCount too small for number of accounts'
                    }), 400
            else:
                per_account_count = 5  # Default
            
            # Create job record
            job_id = str(uuid.uuid4())
            supabase = get_supabase_client()
            
            # Split accounts into batches of 50
            batch_size = 50
            account_batches = [accounts[i:i + batch_size] for i in range(0, len(accounts), batch_size)]
            total_batches = len(account_batches)
            
            logger.info(f"Creating job {job_id} with {total_batches} batches for base_id={base_id}")
            
            # Insert job record with base_id
            supabase.table('scrape_jobs').insert({
                'job_id': job_id,
                'status': 'queued',
                'accounts': accounts,
                'target_gender': target_gender,
                'max_count_per_account': per_account_count,
                'total_batches': total_batches,
                'current_batch': 0,
                'progress': 0.0,
                'profiles_scraped': 0,
                'base_id': base_id,
                'created_at': datetime.now(timezone.utc).isoformat()
            }).execute()
            
            logger.info(f"Job {job_id} created, queueing tasks")
            
            # Queue batch tasks using Celery chord pattern
            # All batches run in parallel, then aggregation runs after all complete
            batch_tasks = []
            for i, batch in enumerate(account_batches, 1):
                task = scrape_account_batch.s(
                    job_id=job_id,
                    accounts=batch,
                    target_gender=target_gender,
                    max_per_account=per_account_count,
                    batch_number=i
                )
                batch_tasks.append(task)
            
            # Create chord: all batches → aggregation
            workflow = chord(batch_tasks)(
                aggregate_scrape_results.s(job_id=job_id)
            )
            
            # Update job to processing
            supabase.table('scrape_jobs')\
                .update({
                    'status': 'processing',
                    'started_at': datetime.now(timezone.utc).isoformat()
                })\
                .eq('job_id', job_id)\
                .execute()
            
            logger.info(f"Job {job_id} queued successfully with {total_batches} batches for base_id={base_id}")
            
            return jsonify({
                'success': True,
                'job_id': job_id,
                'base_id': base_id,
                'status_url': f'/api/job-status/{job_id}',
                'results_url': f'/api/job-results/{job_id}',
                'total_batches': total_batches,
                'message': 'Job queued successfully. Poll status_url for progress.'
            }), 202  # 202 Accepted
            
        except Exception as e:
            logger.error(f"Error queueing scrape job: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    
    @app.route('/api/job-status/<job_id>', methods=['GET'])
    def get_job_status(job_id: str):
        """
        Get status of a scraping job.
        
        Returns:
        {
            "success": true,
            "job_id": "uuid",
            "status": "processing",
            "progress": 45.5,
            "profiles_scraped": 1200,
            "total_batches": 10,
            "current_batch": 5,
            "error_message": null,
            "created_at": "2025-10-14T...",
            "completed_at": null
        }
        """
        try:
            supabase = get_supabase_client()
            
            # Query job
            job = supabase.table('scrape_jobs')\
                .select('*')\
                .eq('job_id', job_id)\
                .execute()
            
            if not job.data or len(job.data) == 0:
                return jsonify({
                    'success': False,
                    'error': f'Job {job_id} not found'
                }), 404
            
            job_data = job.data[0]
            
            return jsonify({
                'success': True,
                'job_id': job_id,
                'status': job_data['status'],
                'progress': float(job_data['progress']) if job_data['progress'] else 0.0,
                'profiles_scraped': job_data['profiles_scraped'],
                'total_scraped': job_data.get('total_scraped'),
                'total_filtered': job_data.get('total_filtered'),
                'total_batches': job_data.get('total_batches', 0),
                'current_batch': job_data.get('current_batch', 0),
                'error_message': job_data.get('error_message'),
                'created_at': job_data['created_at'],
                'started_at': job_data.get('started_at'),
                'completed_at': job_data.get('completed_at')
            })
            
        except Exception as e:
            logger.error(f"Error fetching job status: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    
    @app.route('/api/job-results/<job_id>', methods=['GET'])
    def get_job_results(job_id: str):
        """
        Get results from a completed scraping job with pagination.
        
        Query parameters:
            page: Page number (default: 1)
            limit: Results per page (default: 1000, max: 5000)
        
        Returns:
        {
            "success": true,
            "job_id": "uuid",
            "page": 1,
            "limit": 1000,
            "total": 5000,
            "profiles": [
                {
                    "id": "123",
                    "username": "john_doe",
                    "full_name": "John Doe",
                    "created_at": "..."
                }
            ]
        }
        """
        try:
            supabase = get_supabase_client()
            
            # Verify job exists and is completed
            job = supabase.table('scrape_jobs')\
                .select('status')\
                .eq('job_id', job_id)\
                .execute()
            
            if not job.data or len(job.data) == 0:
                return jsonify({
                    'success': False,
                    'error': f'Job {job_id} not found'
                }), 404
            
            job_status = job.data[0]['status']
            
            if job_status != 'completed':
                return jsonify({
                    'success': False,
                    'error': f'Job is not completed yet (status: {job_status})'
                }), 400
            
            # Pagination parameters
            page = int(request.args.get('page', 1))
            limit = min(int(request.args.get('limit', 1000)), 5000)  # Max 5000 per page
            offset = (page - 1) * limit
            
            # Get total count
            count_result = supabase.table('scrape_results')\
                .select('id', count='exact')\
                .eq('job_id', job_id)\
                .execute()
            
            total = count_result.count if count_result.count else 0
            
            # Get paginated results
            results = supabase.table('scrape_results')\
                .select('profile_id, username, full_name, created_at')\
                .eq('job_id', job_id)\
                .order('created_at', desc=True)\
                .range(offset, offset + limit - 1)\
                .execute()
            
            profiles = []
            if results.data:
                for row in results.data:
                    profiles.append({
                        'id': row['profile_id'],
                        'username': row['username'],
                        'full_name': row.get('full_name', ''),
                        'created_at': row['created_at']
                    })
            
            return jsonify({
                'success': True,
                'job_id': job_id,
                'page': page,
                'limit': limit,
                'total': total,
                'profiles': profiles
            })
            
        except Exception as e:
            logger.error(f"Error fetching job results: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    
    @app.route('/api/ingest', methods=['POST'])
    def ingest_profiles_async():
        """
        ASYNC: Queue profile ingestion job.
        
        Expected JSON payload:
        {
            "profiles": [
                {
                    "id": "123456",
                    "username": "john_doe",
                    "full_name": "John Doe"
                }
            ]
        }
        
        Returns:
        {
            "success": true,
            "batch_count": 5,
            "total_profiles": 5000,
            "message": "Ingestion queued successfully"
        }
        """
        try:
            data = request.get_json()
            
            if not data or 'profiles' not in data:
                return jsonify({
                    'success': False,
                    'error': 'Missing "profiles" field in request body'
                }), 400
            
            profiles = data['profiles']
            
            if not isinstance(profiles, list):
                return jsonify({
                    'success': False,
                    'error': 'Profiles must be a list'
                }), 400
            
            if len(profiles) == 0:
                return jsonify({
                    'success': True,
                    'batch_count': 0,
                    'total_profiles': 0,
                    'message': 'No profiles to ingest'
                })
            
            # Split profiles into batches of 1000
            batch_size = 1000
            profile_batches = [profiles[i:i + batch_size] for i in range(0, len(profiles), batch_size)]
            batch_id = str(uuid.uuid4())
            
            logger.info(f"Queueing ingestion {batch_id}: {len(profiles)} profiles in {len(profile_batches)} batches")
            
            # Queue batch tasks
            for i, batch in enumerate(profile_batches, 1):
                ingest_profiles_batch.delay(
                    batch_id=batch_id,
                    profiles=batch,
                    batch_number=i
                )
            
            return jsonify({
                'success': True,
                'batch_id': batch_id,
                'batch_count': len(profile_batches),
                'total_profiles': len(profiles),
                'message': f'Ingestion queued successfully ({len(profile_batches)} batches)'
            }), 202  # 202 Accepted
            
        except Exception as e:
            logger.error(f"Error queueing ingest job: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    
    @app.route('/api/run-daily', methods=['POST'])
    def run_daily_async():
        """
        ASYNC: Queue daily pipeline orchestration.
        
        Optional JSON payload:
        {
            "campaign_date": "2025-10-14" (optional, defaults to today),
            "profiles_per_table": 180 (optional)
        }
        
        Returns:
        {
            "success": true,
            "task_id": "celery-task-id",
            "message": "Daily pipeline queued successfully"
        }
        """
        try:
            data = request.get_json() or {}
            
            campaign_date = data.get('campaign_date')
            profiles_per_table = data.get('profiles_per_table', 180)
            
            logger.info(f"Queueing daily pipeline: date={campaign_date}, profiles_per_table={profiles_per_table}")
            
            # Queue orchestrator task
            task = daily_pipeline_orchestrator.delay(
                campaign_date=campaign_date,
                profiles_per_table=profiles_per_table
            )
            
            return jsonify({
                'success': True,
                'task_id': task.id,
                'message': 'Daily pipeline queued successfully. Check logs for progress.'
            }), 202  # 202 Accepted
            
        except Exception as e:
            logger.error(f"Error queueing daily pipeline: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    logger.info("Async endpoints registered successfully")
