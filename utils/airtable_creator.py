"""
Simplified Airtable Base Creation Utility
==========================================
Creates Daily Outreach Tables in an Airtable base with a standardized schema.

Usage:
    from utils.airtable_creator import create_airtable_tables
    
    result = create_airtable_tables(
        api_key='your_api_key',
        base_id='appXYZ123ABC',
        num_tables=80
    )
"""

import re
import time
import logging
from typing import Dict, List, Optional
from pyairtable import Api

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def extract_base_id_from_url(url: str) -> Optional[str]:
    """
    Extract Airtable base ID from an Airtable URL.
    
    Args:
        url: Airtable URL (e.g., https://airtable.com/app1ovtHsWbF2Ae7x/tblXXX/viwXXX)
        
    Returns:
        Base ID (e.g., 'app1ovtHsWbF2Ae7x') or None if invalid
    """
    # If it's already just a base_id (starts with 'app'), return it
    if url.startswith('app') and '/' not in url:
        return url
    
    # Extract base_id from URL
    pattern = r'https?://(?:www\.)?airtable\.com/(app[a-zA-Z0-9]+)'
    match = re.search(pattern, url)
    
    if match:
        return match.group(1)
    
    return None


def validate_base_id(base_id: str) -> bool:
    """
    Validate that a base_id follows Airtable's format.
    
    Args:
        base_id: The base ID to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not base_id:
        return False
    
    # Airtable base IDs start with 'app' followed by alphanumeric characters
    pattern = r'^app[a-zA-Z0-9]{8,20}$'
    return bool(re.match(pattern, base_id))


def create_airtable_tables(
    api_key: str,
    base_id: str,
    num_tables: int
) -> Dict:
    """
    Creates multiple Daily Outreach Tables in an Airtable base.
    
    Args:
        api_key (str): The Airtable API key (Personal Access Token)
        base_id (str): The ID of the Airtable base
        num_tables (int): The number of tables to create (represents number of VAs)
    
    Returns:
        dict: A dictionary containing:
            - success (bool): Whether the operation was successful
            - base_id (str): The base ID used
            - tables_created (int): Number of tables successfully created
            - tables_failed (int): Number of tables that failed
            - failed_tables (list): List of failed table names with errors
            - table_ids (dict): Mapping of table names to their IDs
    """
    logger.info(f"Starting table creation: {num_tables} tables in base {base_id}")
    
    # Initialize API client
    try:
        api = Api(api_key)
        base = api.base(base_id)
    except Exception as e:
        logger.error(f"Failed to initialize Airtable API: {str(e)}")
        return {
            'success': False,
            'error': f'Failed to initialize Airtable API: {str(e)}',
            'base_id': base_id,
            'tables_created': 0,
            'tables_failed': num_tables,
            'failed_tables': [],
            'table_ids': {}
        }
    
    created_tables = []
    failed_tables = []
    table_ids = {}
    skipped_tables = []  # Track tables that already exist
    
    # Create tables
    for i in range(1, num_tables + 1):
        # Table name format: Daily_Outreach_Table_01, Daily_Outreach_Table_02, etc.
        table_name = f"Daily_Outreach_Table_{i:02d}"
        
        try:
            logger.info(f"Creating table {i}/{num_tables}: {table_name}")
            
            # Create table with the required schema
            # Schema supports multi-platform data (Instagram, TikTok, Threads, X/Twitter)
            table = base.create_table(
                name=table_name,
                fields=[
                    {
                        "name": "id",
                        "type": "singleLineText",
                        "description": "Unique identifier for the profile"
                    },
                    {
                        "name": "username",
                        "type": "singleLineText",
                        "description": "Social media username (platform-specific)"
                    },
                    {
                        "name": "full_name",
                        "type": "singleLineText",
                        "description": "Full name of the profile"
                    },
                    {
                        "name": "platform",
                        "type": "singleSelect",
                        "description": "Social media platform",
                        "options": {
                            "choices": [
                                {"name": "instagram"},
                                {"name": "tiktok"},
                                {"name": "threads"},
                                {"name": "x"}
                            ]
                        }
                    },
                    {
                        "name": "position",
                        "type": "number",
                        "description": "Position in the assignment queue",
                        "options": {
                            "precision": 0  # Integer
                        }
                    },
                    {
                        "name": "campaign_date",
                        "type": "date",
                        "description": "Date of the campaign",
                        "options": {
                            "dateFormat": {
                                "name": "iso"
                            }
                        }
                    },
                    {
                        "name": "progress_status",
                        "type": "singleSelect",
                        "description": "Current status of the outreach",
                        "options": {
                            "choices": [
                                {"name": "pending"},
                                {"name": "followed"},
                                {"name": "unfollowed"},
                                {"name": "completed"}
                            ]
                        }
                    }
                ]
            )
            
            created_tables.append(table)
            table_ids[table_name] = table.id
            logger.info(f"✓ Successfully created table: {table_name} (ID: {table.id})")
            
            # Rate limiting: Airtable allows ~5 requests per second
            time.sleep(0.25)
            
        except Exception as e:
            error_msg = str(e)
            
            # Check if error is due to duplicate table name
            if 'DUPLICATE_TABLE_NAME' in error_msg or 'already exists' in error_msg.lower():
                logger.info(f"⊙ Table {table_name} already exists, skipping...")
                skipped_tables.append(table_name)
                # Don't count as failure - table already exists is OK
            else:
                logger.error(f"✗ Error creating table {table_name}: {error_msg}")
                failed_tables.append({
                    'table_name': table_name,
                    'error': error_msg
                })
    
    tables_created = len(created_tables)
    tables_failed = len(failed_tables)
    tables_skipped = len(skipped_tables)
    
    # Success if we created tables OR if tables already exist (skipped)
    # Fail only if we have actual errors
    success = (tables_created > 0 or tables_skipped > 0) and tables_failed == 0
    
    result = {
        'success': success,
        'base_id': base_id,
        'tables_created': tables_created,
        'tables_skipped': tables_skipped,
        'tables_failed': tables_failed,
        'failed_tables': failed_tables,
        'table_ids': table_ids,
        'total_tables': num_tables,
        'message': f'Created {tables_created} new tables' + (f', {tables_skipped} already existed' if tables_skipped > 0 else '')
    }
    
    logger.info(f"Table creation complete: {tables_created} created, {tables_skipped} skipped, {tables_failed} failed")
    
    return result


def create_airtable_base(
    base_id: str,
    num_vas: int,
    airtable_token: str,
    base_name: Optional[str] = None
) -> Dict:
    """
    Convenience function to create Airtable tables (maintains compatibility with existing code).
    
    Args:
        base_id: Airtable base ID
        num_vas: Number of VA tables to create
        airtable_token: Airtable Personal Access Token
        base_name: Optional display name for logging
        
    Returns:
        Dictionary with creation results
    """
    display_name = base_name or base_id
    logger.info(f"Creating Airtable base: {display_name}")
    
    result = create_airtable_tables(
        api_key=airtable_token,
        base_id=base_id,
        num_tables=num_vas
    )
    
    # Wrap result in expected format for backward compatibility
    return {
        'success': result['success'],
        'base_id': result['base_id'],
        'base_name': display_name,
        'setup_results': {
            'tables_created': result['tables_created'],
            'tables_skipped': result.get('tables_skipped', 0),
            'tables_failed': result['tables_failed'],
            'failed_tables': result['failed_tables'],
            'total_tables': result['total_tables']
        },
        'table_ids': result.get('table_ids', {}),
        'message': result.get('message', '')
    }


# Maintain backward compatibility
class AirtableCreator:
    """Legacy class for backward compatibility."""
    
    def __init__(self, airtable_token: str):
        self.token = airtable_token
        self.api = Api(airtable_token)
        logger.info("✓ Airtable API client initialized")
    
    def create_base_with_va_tables(
        self,
        base_id: str,
        num_vas: int,
        base_name: Optional[str] = None
    ) -> Dict:
        """Create VA tables in an existing base."""
        return create_airtable_base(
            base_id=base_id,
            num_vas=num_vas,
            airtable_token=self.token,
            base_name=base_name
        )
