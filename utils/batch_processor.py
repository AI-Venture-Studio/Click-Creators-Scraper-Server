"""
Batch processing utilities for database operations.
"""
import logging
from typing import List, Dict, Tuple
from datetime import datetime, timezone
from supabase import Client

logger = logging.getLogger(__name__)


def batch_insert_profiles(
    supabase: Client,
    profiles: List[Dict],
    batch_size: int = 500
) -> Tuple[int, int]:
    """
    Insert profiles into Supabase in batches to avoid memory overflow.
    
    Args:
        supabase: Supabase client instance
        profiles: List of profile dictionaries with id, username, full_name
        batch_size: Number of profiles to insert per batch (default: 500)
        
    Returns:
        Tuple of (inserted_count, skipped_count)
    """
    inserted_raw = 0
    added_to_global = 0
    skipped_existing = 0
    
    total_profiles = len(profiles)
    logger.info(f"Starting batch insert of {total_profiles} profiles in batches of {batch_size}")
    
    # Process in batches
    for i in range(0, total_profiles, batch_size):
        batch = profiles[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (total_profiles + batch_size - 1) // batch_size
        
        logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} profiles)")
        
        # Insert each profile in the batch
        for profile in batch:
            try:
                # Validate required fields
                if 'id' not in profile or 'username' not in profile:
                    logger.warning(f"Skipping profile with missing id or username: {profile}")
                    continue
                
                profile_id = str(profile['id'])
                username = profile['username']
                full_name = profile.get('full_name', '')
                
                # Step 1: Insert into raw_scraped_profiles
                try:
                    supabase.table('raw_scraped_profiles').insert({
                        'id': profile_id,
                        'username': username,
                        'full_name': full_name,
                        'scraped_at': datetime.now(timezone.utc).isoformat()
                    }).execute()
                    inserted_raw += 1
                except Exception as e:
                    logger.warning(f"Failed to insert {username} into raw_scraped_profiles: {str(e)}")
                
                # Step 2: Check if profile exists in global_usernames
                try:
                    existing = supabase.table('global_usernames')\
                        .select('id')\
                        .eq('id', profile_id)\
                        .execute()
                    
                    if existing.data and len(existing.data) > 0:
                        skipped_existing += 1
                    else:
                        # Insert into global_usernames
                        supabase.table('global_usernames').insert({
                            'id': profile_id,
                            'username': username,
                            'full_name': full_name,
                            'used': False,
                            'added_at': datetime.now(timezone.utc).isoformat()
                        }).execute()
                        added_to_global += 1
                        
                except Exception as e:
                    logger.warning(f"Failed to process {username} for global_usernames: {str(e)}")
                    skipped_existing += 1
                    
            except Exception as e:
                logger.error(f"Failed to process profile in batch: {str(e)}")
                continue
        
        logger.info(f"Batch {batch_num} complete: {inserted_raw} raw, {added_to_global} global, {skipped_existing} skipped")
    
    logger.info(f"Batch insert complete: Total raw={inserted_raw}, global={added_to_global}, skipped={skipped_existing}")
    
    return inserted_raw, added_to_global, skipped_existing


def batch_update_assignments(
    supabase: Client,
    updates: List[Dict],
    batch_size: int = 500
) -> int:
    """
    Update daily_assignments in batches.
    
    Args:
        supabase: Supabase client instance
        updates: List of update dictionaries with assignment_id and fields to update
        batch_size: Number of updates per batch (default: 500)
        
    Returns:
        Number of successfully updated records
    """
    updated_count = 0
    total_updates = len(updates)
    
    logger.info(f"Starting batch update of {total_updates} assignments in batches of {batch_size}")
    
    # Process in batches
    for i in range(0, total_updates, batch_size):
        batch = updates[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (total_updates + batch_size - 1) // batch_size
        
        logger.info(f"Processing update batch {batch_num}/{total_batches} ({len(batch)} updates)")
        
        for update in batch:
            try:
                assignment_id = update.pop('assignment_id')
                
                supabase.table('daily_assignments')\
                    .update(update)\
                    .eq('assignment_id', assignment_id)\
                    .execute()
                
                updated_count += 1
                
            except Exception as e:
                logger.error(f"Failed to update assignment {update.get('assignment_id')}: {str(e)}")
                continue
        
        logger.info(f"Update batch {batch_num} complete: {updated_count} updated so far")
    
    logger.info(f"Batch update complete: {updated_count} total updates")
    
    return updated_count


def batch_delete_records(
    supabase: Client,
    table_name: str,
    record_ids: List[str],
    id_column: str = 'id',
    batch_size: int = 500
) -> int:
    """
    Delete records from a table in batches.
    
    Args:
        supabase: Supabase client instance
        table_name: Name of the table to delete from
        record_ids: List of record IDs to delete
        id_column: Name of the ID column (default: 'id')
        batch_size: Number of deletes per batch (default: 500)
        
    Returns:
        Number of successfully deleted records
    """
    deleted_count = 0
    total_deletes = len(record_ids)
    
    logger.info(f"Starting batch delete of {total_deletes} records from {table_name} in batches of {batch_size}")
    
    # Process in batches
    for i in range(0, total_deletes, batch_size):
        batch = record_ids[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (total_deletes + batch_size - 1) // batch_size
        
        logger.info(f"Processing delete batch {batch_num}/{total_batches} ({len(batch)} deletes)")
        
        for record_id in batch:
            try:
                supabase.table(table_name)\
                    .delete()\
                    .eq(id_column, record_id)\
                    .execute()
                
                deleted_count += 1
                
            except Exception as e:
                logger.error(f"Failed to delete {record_id} from {table_name}: {str(e)}")
                continue
        
        logger.info(f"Delete batch {batch_num} complete: {deleted_count} deleted so far")
    
    logger.info(f"Batch delete complete: {deleted_count} total deletes from {table_name}")
    
    return deleted_count
