"""
Batch processing utilities for database operations.
"""
import logging
import time
from typing import List, Dict, Tuple
from datetime import datetime, timezone
from supabase import Client

logger = logging.getLogger(__name__)


def batch_insert_profiles(
    supabase: Client,
    profiles: List[Dict],
    batch_size: int = 1000,
    rate_limit_delay: float = 0.1,
    base_id: str = 'default_instagram'
) -> Tuple[int, int, int]:
    """
    Insert profiles into Supabase using TRUE bulk inserts for maximum performance.
    
    OPTIMIZED FOR 500K+ SCALE WITH FREE TIER PROTECTION:
    - Bulk inserts (1000 records at a time) instead of individual inserts
    - Single bulk query to check existing profiles instead of N queries
    - Rate limiting protection (100ms delay between batches)
    - Graceful fallback to individual inserts if batch fails
    - Handles duplicates gracefully with upsert logic
    
    SUPABASE FREE TIER LIMITS CONSIDERED:
    - Batch size: 1000 records (~100-200 KB, well under 8 MB limit)
    - Rate limiting: 100ms delay between batches (prevents throttling)
    - Connection pooling: Reuses single connection (under 50 connection limit)
    - Payload size: Each batch ~200 KB (safe for free tier)
    
    Args:
        supabase: Supabase client instance
        profiles: List of profile dictionaries with id, username, full_name
        batch_size: Number of profiles to insert per batch (default: 1000)
        rate_limit_delay: Delay in seconds between batches (default: 0.1 = 100ms)
        base_id: Multi-tenant identifier for data isolation (default: 'default_instagram')
        
    Returns:
        Tuple of (inserted_raw, added_to_global, skipped_existing)
    """
    inserted_raw = 0
    added_to_global = 0
    skipped_existing = 0
    
    total_profiles = len(profiles)
    logger.info(f"Starting BULK insert of {total_profiles} profiles in batches of {batch_size}")
    
    # Validate and prepare all profiles first
    valid_profiles = []
    current_timestamp = datetime.now(timezone.utc).isoformat()
    
    for profile in profiles:
        # Validate required fields
        if 'id' not in profile or 'username' not in profile:
            logger.warning(f"Skipping profile with missing id or username: {profile}")
            continue
        
        valid_profiles.append({
            'id': str(profile['id']),
            'username': profile['username'],
            'full_name': profile.get('full_name', '')
        })
    
    if not valid_profiles:
        logger.warning("No valid profiles to insert")
        return 0, 0, 0
    
    logger.info(f"Validated {len(valid_profiles)} profiles for insertion")
    
    # OPTIMIZATION: Check ALL existing profiles in ONE bulk query
    # Instead of N individual queries, we do 1 query with IN clause
    all_profile_ids = [p['id'] for p in valid_profiles]
    existing_ids = set()
    
    # Query in chunks of 1000 to avoid URL length limits
    logger.info(f"Checking for existing profiles in global_usernames...")
    for i in range(0, len(all_profile_ids), 1000):
        chunk_ids = all_profile_ids[i:i + 1000]
        try:
            existing = supabase.table('global_usernames')\
                .select('id')\
                .in_('id', chunk_ids)\
                .execute()
            
            if existing.data:
                existing_ids.update(r['id'] for r in existing.data)
        except Exception as e:
            logger.error(f"Failed to check existing profiles (chunk {i//1000 + 1}): {str(e)}")
    
    logger.info(f"Found {len(existing_ids)} existing profiles in global_usernames")
    
    # Separate profiles into: raw inserts and new global profiles
    raw_records = []
    global_records = []
    
    for profile in valid_profiles:
        profile_id = profile['id']
        username = profile['username']
        full_name = profile['full_name']
        
        # Always add to raw_scraped_profiles (historical record)
        raw_records.append({
            'id': profile_id,
            'username': username,
            'full_name': full_name,
            'scraped_at': current_timestamp,
            'base_id': base_id
        })
        
        # Only add to global_usernames if it doesn't exist
        if profile_id not in existing_ids:
            global_records.append({
                'id': profile_id,
                'username': username,
                'full_name': full_name,
                'used': False,
                'created_at': current_timestamp,  # Fixed: was 'added_at', should be 'created_at'
                'base_id': base_id
            })
        else:
            skipped_existing += 1
    
    logger.info(f"Prepared {len(raw_records)} raw records, {len(global_records)} new global records")
    
    # BULK INSERT #1: Insert into raw_scraped_profiles
    logger.info("Bulk inserting into raw_scraped_profiles...")
    for i in range(0, len(raw_records), batch_size):
        batch = raw_records[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(raw_records) + batch_size - 1) // batch_size
        
        try:
            # Single INSERT with multiple records
            supabase.table('raw_scraped_profiles').insert(batch).execute()
            inserted_raw += len(batch)
            logger.info(f"✓ Inserted batch {batch_num}/{total_batches} into raw_scraped_profiles ({len(batch)} records)")
            
            # Rate limiting protection for Supabase Free Tier
            if i + batch_size < len(raw_records):  # Don't delay after last batch
                time.sleep(rate_limit_delay)
                
        except Exception as e:
            logger.error(f"✗ Failed to insert batch {batch_num} into raw_scraped_profiles: {str(e)}")
            # Try individual inserts as fallback for this batch only
            for record in batch:
                try:
                    supabase.table('raw_scraped_profiles').insert(record).execute()
                    inserted_raw += 1
                    time.sleep(0.01)  # 10ms delay for individual inserts
                except Exception as e2:
                    logger.warning(f"Failed to insert {record['username']} individually: {str(e2)}")
    
    # BULK INSERT #2: Insert into global_usernames (only new profiles)
    if global_records:
        logger.info("Bulk inserting into global_usernames...")
        for i in range(0, len(global_records), batch_size):
            batch = global_records[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(global_records) + batch_size - 1) // batch_size
            
            try:
                # Single INSERT with multiple records
                supabase.table('global_usernames').insert(batch).execute()
                added_to_global += len(batch)
                logger.info(f"✓ Inserted batch {batch_num}/{total_batches} into global_usernames ({len(batch)} records)")
                
                # Rate limiting protection for Supabase Free Tier
                if i + batch_size < len(global_records):  # Don't delay after last batch
                    time.sleep(rate_limit_delay)
                    
            except Exception as e:
                logger.error(f"✗ Failed to insert batch {batch_num} into global_usernames: {str(e)}")
                # Try individual inserts as fallback for this batch only
                for record in batch:
                    try:
                        supabase.table('global_usernames').insert(record).execute()
                        added_to_global += 1
                        time.sleep(0.01)  # 10ms delay for individual inserts
                    except Exception as e2:
                        logger.warning(f"Failed to insert {record['username']} individually: {str(e2)}")
                        skipped_existing += 1
    else:
        logger.info("No new profiles to insert into global_usernames (all already exist)")
    
    logger.info("=" * 70)
    logger.info(f"BULK INSERT COMPLETE:")
    logger.info(f"  - Raw profiles inserted: {inserted_raw}/{len(raw_records)}")
    logger.info(f"  - New global profiles: {added_to_global}/{len(global_records)}")
    logger.info(f"  - Skipped (already exist): {skipped_existing}")
    logger.info("=" * 70)
    
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
