"""
Background tasks for asynchronous processing using Celery.
"""
import os
import logging
import random
import uuid
import threading
from typing import List, Dict, Any
from datetime import datetime, timezone, date, timedelta
from celery import Task, chord, group
from celery.exceptions import SoftTimeLimitExceeded
from supabase import create_client, Client

from celery_config import celery
from utils.scraper import scrape_followers
from utils.gender import detect_gender, filter_by_gender
from utils.batch_processor import batch_insert_profiles, batch_update_assignments

logger = logging.getLogger(__name__)


# ===================================================================
# SUPABASE CLIENT WITH CONNECTION POOLING (THREAD-SAFE)
# ===================================================================
# Use singleton pattern with thread lock to prevent race conditions
_supabase_client = None
_supabase_lock = threading.Lock()

def get_supabase_client() -> Client:
    """
    Initialize and return Supabase client.
    
    OPTIMIZED: Uses thread-safe singleton pattern to reuse the same client instance
    across all Celery tasks, preventing connection leaks and race conditions.
    """
    global _supabase_client
    
    # Double-checked locking pattern for thread safety
    if _supabase_client is not None:
        return _supabase_client
    
    with _supabase_lock:
        # Check again inside lock (another thread might have initialized it)
        if _supabase_client is not None:
            return _supabase_client
        
        # Initialize new client
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
        
        if not supabase_url or not supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables are required.")
        
        _supabase_client = create_client(supabase_url, supabase_key)
        logger.info("✓ Supabase client initialized with connection pooling (Celery, thread-safe)")
        
        return _supabase_client
    
    return _supabase_client


class BaseTask(Task):
    """Base task with error handling and retry logic."""
    
    autoretry_for = (Exception,)
    retry_kwargs = {'max_retries': 3}
    retry_backoff = True
    retry_backoff_max = 600  # 10 minutes
    retry_jitter = True


@celery.task(base=BaseTask, bind=True, name='tasks.scrape_account_batch')
def scrape_account_batch(
    self,
    job_id: str,
    accounts: List[str],
    target_gender: str = 'male',
    max_per_account: int = 5,
    batch_number: int = 1
) -> Dict[str, Any]:
    """
    Scrape a batch of accounts (max 50) and return filtered profiles.
    
    Args:
        job_id: Unique job identifier
        accounts: List of Instagram usernames (max 50)
        target_gender: Target gender filter ('male' or 'female')
        max_per_account: Max followers to scrape per account
        batch_number: Batch number for logging
        
    Returns:
        Dictionary with scraped and filtered profiles
    """
    try:
        logger.info(f"[Job {job_id}] Batch {batch_number}: Scraping {len(accounts)} accounts")
        
        # Update job progress
        supabase = get_supabase_client()
        
        # Step 1: Scrape followers
        followers = scrape_followers(accounts, max_per_account)
        logger.info(f"[Job {job_id}] Batch {batch_number}: Scraped {len(followers)} followers")
        
        # Step 2: Detect gender
        followers_gender = detect_gender(followers)
        
        # Step 3: Filter by target gender
        filtered_followers = filter_by_gender(followers_gender, target_gender)
        logger.info(f"[Job {job_id}] Batch {batch_number}: Filtered to {len(filtered_followers)} profiles")
        
        # Step 4: Format profiles for return
        complete_profiles = []
        for username in filtered_followers.keys():
            follower_info = followers.get(username, {})
            complete_profiles.append({
                'id': follower_info.get('id', username),
                'username': username,
                'full_name': follower_info.get('full_name', ''),
            })
        
        # Update job progress
        try:
            # Increment profiles_scraped count
            job = supabase.table('scrape_jobs')\
                .select('profiles_scraped')\
                .eq('job_id', job_id)\
                .execute()
            
            current_count = job.data[0]['profiles_scraped'] if job.data else 0
            new_count = current_count + len(complete_profiles)
            
            supabase.table('scrape_jobs')\
                .update({
                    'profiles_scraped': new_count,
                    'updated_at': datetime.now(timezone.utc).isoformat()
                })\
                .eq('job_id', job_id)\
                .execute()
        except Exception as e:
            logger.warning(f"Failed to update job progress: {str(e)}")
        
        return {
            'job_id': job_id,
            'batch_number': batch_number,
            'profiles': complete_profiles,
            'total_scraped': len(followers),
            'total_filtered': len(complete_profiles)
        }
        
    except SoftTimeLimitExceeded:
        logger.error(f"[Job {job_id}] Batch {batch_number}: Task exceeded time limit")
        raise
    except Exception as e:
        logger.error(f"[Job {job_id}] Batch {batch_number}: Error - {str(e)}")
        
        # Update job with error
        try:
            supabase = get_supabase_client()
            supabase.table('scrape_jobs')\
                .update({
                    'status': 'failed',
                    'error_message': str(e),
                    'updated_at': datetime.now(timezone.utc).isoformat()
                })\
                .eq('job_id', job_id)\
                .execute()
        except:
            pass
        
        raise


@celery.task(base=BaseTask, bind=True, name='tasks.aggregate_scrape_results')
def aggregate_scrape_results(self, batch_results: List[Dict], job_id: str) -> Dict[str, Any]:
    """
    Aggregate results from all batch tasks and store in database.
    
    Args:
        batch_results: List of results from scrape_account_batch tasks
        job_id: Unique job identifier
        
    Returns:
        Summary of aggregation
    """
    try:
        logger.info(f"[Job {job_id}] Aggregating results from {len(batch_results)} batches")
        
        supabase = get_supabase_client()
        
        # Combine all profiles from batches
        all_profiles = []
        total_scraped = 0
        total_filtered = 0
        
        for result in batch_results:
            if result and 'profiles' in result:
                all_profiles.extend(result['profiles'])
                total_scraped += result.get('total_scraped', 0)
                total_filtered += result.get('total_filtered', 0)
        
        logger.info(f"[Job {job_id}] Total profiles: {len(all_profiles)}, Scraped: {total_scraped}, Filtered: {total_filtered}")
        
        # Batch insert into scrape_results (chunks of 1000)
        batch_size = 1000
        inserted_count = 0
        
        for i in range(0, len(all_profiles), batch_size):
            batch = all_profiles[i:i + batch_size]
            
            # Prepare records for insertion
            records = []
            for profile in batch:
                records.append({
                    'job_id': job_id,
                    'profile_id': profile['id'],
                    'username': profile['username'],
                    'full_name': profile.get('full_name', ''),
                    'created_at': datetime.now(timezone.utc).isoformat()
                })
            
            # Insert batch
            try:
                supabase.table('scrape_results').insert(records).execute()
                inserted_count += len(records)
                logger.info(f"[Job {job_id}] Inserted batch: {inserted_count}/{len(all_profiles)}")
            except Exception as e:
                logger.error(f"[Job {job_id}] Failed to insert batch: {str(e)}")
        
        # Update job status to completed
        supabase.table('scrape_jobs')\
            .update({
                'status': 'completed',
                'total_scraped': total_scraped,
                'total_filtered': total_filtered,
                'profiles_scraped': len(all_profiles),
                'progress': 100.0,
                'completed_at': datetime.now(timezone.utc).isoformat(),
                'updated_at': datetime.now(timezone.utc).isoformat()
            })\
            .eq('job_id', job_id)\
            .execute()
        
        logger.info(f"[Job {job_id}] Aggregation complete: {inserted_count} profiles stored")
        
        return {
            'job_id': job_id,
            'total_profiles': len(all_profiles),
            'total_scraped': total_scraped,
            'total_filtered': total_filtered,
            'inserted': inserted_count
        }
        
    except Exception as e:
        logger.error(f"[Job {job_id}] Aggregation error: {str(e)}")
        
        # Update job with error
        try:
            supabase = get_supabase_client()
            supabase.table('scrape_jobs')\
                .update({
                    'status': 'failed',
                    'error_message': f"Aggregation failed: {str(e)}",
                    'updated_at': datetime.now(timezone.utc).isoformat()
                })\
                .eq('job_id', job_id)\
                .execute()
        except:
            pass
        
        raise


@celery.task(base=BaseTask, bind=True, name='tasks.ingest_profiles_batch')
def ingest_profiles_batch(
    self,
    batch_id: str,
    profiles: List[Dict],
    batch_number: int = 1
) -> Dict[str, Any]:
    """
    Ingest a batch of profiles into Supabase (max 1000).
    
    Args:
        batch_id: Unique batch identifier
        profiles: List of profile dictionaries
        batch_number: Batch number for logging
        
    Returns:
        Summary of ingestion
    """
    try:
        logger.info(f"[Batch {batch_id}] #{batch_number}: Ingesting {len(profiles)} profiles")
        
        supabase = get_supabase_client()
        
        # Use batch processor for insertion
        inserted_raw, added_to_global, skipped = batch_insert_profiles(
            supabase,
            profiles,
            batch_size=500
        )
        
        logger.info(f"[Batch {batch_id}] #{batch_number}: Complete - raw={inserted_raw}, global={added_to_global}, skipped={skipped}")
        
        return {
            'batch_id': batch_id,
            'batch_number': batch_number,
            'inserted_raw': inserted_raw,
            'added_to_global': added_to_global,
            'skipped': skipped
        }
        
    except Exception as e:
        logger.error(f"[Batch {batch_id}] #{batch_number}: Error - {str(e)}")
        raise


@celery.task(base=BaseTask, bind=True, name='tasks.daily_pipeline_orchestrator')
def daily_pipeline_orchestrator(
    self,
    campaign_date: str = None,
    profiles_per_table: int = 180
) -> Dict[str, Any]:
    """
    Orchestrate the entire daily pipeline: selection, distribution, sync, cleanup.
    
    Args:
        campaign_date: Campaign date (YYYY-MM-DD) or None for today
        profiles_per_table: Number of profiles per VA table
        
    Returns:
        Summary of pipeline execution
    """
    try:
        logger.info("Starting daily pipeline orchestration")
        
        supabase = get_supabase_client()
        
        # Parse campaign date
        if campaign_date:
            campaign_date_obj = datetime.strptime(campaign_date, '%Y-%m-%d').date()
        else:
            campaign_date_obj = date.today()
        
        num_va_tables = int(os.getenv('NUM_VA_TABLES', 80))
        target_count = num_va_tables * profiles_per_table
        
        logger.info(f"Pipeline config: date={campaign_date_obj}, target={target_count}")
        
        # === STEP 1: DAILY SELECTION ===
        logger.info("Step 1: Daily Selection")
        
        campaign_id = str(uuid.uuid4())
        
        supabase.table('campaigns').insert({
            'campaign_id': campaign_id,
            'campaign_date': campaign_date_obj.isoformat(),
            'total_assigned': 0,
            'status': False,
            'created_at': datetime.now(timezone.utc).isoformat()
        }).execute()
        
        # Select unused profiles
        available_profiles = supabase.table('global_usernames')\
            .select('id, username, full_name')\
            .eq('used', False)\
            .limit(target_count)\
            .execute()
        
        if not available_profiles.data:
            raise Exception("No unused profiles available")
        
        selected_profiles = available_profiles.data
        total_selected = len(selected_profiles)
        
        # Mark as used
        for profile in selected_profiles:
            supabase.table('global_usernames')\
                .update({
                    'used': True,
                    'used_at': datetime.now(timezone.utc).isoformat()
                })\
                .eq('id', profile['id'])\
                .execute()
        
        # Create placeholder assignments
        assignments = []
        for profile in selected_profiles:
            assignments.append({
                'assignment_id': str(uuid.uuid4()),
                'campaign_id': campaign_id,
                'va_table_number': 0,
                'position': 0,
                'id': profile['id'],
                'username': profile['username'],
                'full_name': profile['full_name'],
                'status': 'pending',
                'assigned_at': datetime.now(timezone.utc).isoformat()
            })
        
        supabase.table('daily_assignments').insert(assignments).execute()
        
        supabase.table('campaigns')\
            .update({'total_assigned': total_selected})\
            .eq('campaign_id', campaign_id)\
            .execute()
        
        logger.info(f"Step 1 complete: {total_selected} profiles selected")
        
        # === STEP 2: DISTRIBUTION ===
        logger.info("Step 2: Distribution")
        
        # Shuffle assignments
        random.shuffle(assignments)
        
        # Assign to VA tables
        distributed_count = 0
        current_table = 1
        current_position = 1
        
        for assignment in assignments:
            supabase.table('daily_assignments')\
                .update({
                    'va_table_number': current_table,
                    'position': current_position
                })\
                .eq('assignment_id', assignment['assignment_id'])\
                .execute()
            
            distributed_count += 1
            current_position += 1
            
            if current_position > profiles_per_table:
                current_position = 1
                current_table += 1
                
                if current_table > num_va_tables:
                    break
        
        logger.info(f"Step 2 complete: {distributed_count} profiles distributed")
        
        # === STEP 3: AIRTABLE SYNC ===
        # Note: Airtable sync moved to separate endpoint for reliability
        # This can be called via /api/airtable-sync/<campaign_id>
        
        logger.info("Pipeline complete (Airtable sync should be called separately)")
        
        return {
            'success': True,
            'campaign_id': campaign_id,
            'selected': total_selected,
            'distributed': distributed_count,
            'campaign_date': campaign_date_obj.isoformat()
        }
        
    except Exception as e:
        logger.error(f"Pipeline orchestration error: {str(e)}")
        raise
