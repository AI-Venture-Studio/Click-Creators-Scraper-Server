"""
Multi-tenant base_id utility functions.

This module provides helper functions for:
1. Extracting base_id from request headers/body (REQUIRED)
2. Validating base_id format
3. Scoping queries to specific base_id

IMPORTANT: base_id must ALWAYS be provided explicitly via headers or request body.
No default fallback is provided to ensure proper multi-tenant isolation.
"""

import logging
from typing import Optional, Dict, Any
from flask import request

logger = logging.getLogger(__name__)


def get_base_id_from_request(required: bool = True) -> Optional[str]:
    """
    Extract base_id from request headers or body.
    
    Priority order:
    1. X-Base-Id header
    2. base_id field in JSON body
    
    Args:
        required: If True, raises ValueError when base_id is missing
    
    Returns:
        str: The base_id from the request, or None if not found and not required
        
    Raises:
        ValueError: If required=True and base_id is not provided
    """
    try:
        # Check header first (preferred for multi-tenant routing)
        base_id_header = request.headers.get('X-Base-Id')
        if base_id_header and base_id_header.strip():
            logger.debug(f"Using base_id from header: {base_id_header}")
            return base_id_header.strip()
        
        # Check JSON body (for request payloads that include it)
        try:
            data = request.get_json(silent=True) or {}
            base_id_body = data.get('base_id')
            if base_id_body and isinstance(base_id_body, str) and base_id_body.strip():
                logger.debug(f"Using base_id from request body: {base_id_body}")
                return base_id_body.strip()
        except Exception as e:
            logger.debug(f"Could not parse JSON body for base_id: {e}")
        
        # No base_id found
        if required:
            logger.error("base_id is required but was not provided in headers or request body")
            raise ValueError(
                "base_id is required. Please provide it via 'X-Base-Id' header or 'base_id' in request body."
            )
        
        logger.warning("No base_id specified in request")
        return None
        
    except ValueError:
        # Re-raise ValueError for missing required base_id
        raise
    except Exception as e:
        logger.error(f"Error extracting base_id from request: {e}")
        if required:
            raise ValueError(f"Error extracting base_id: {str(e)}")
        return None


def ensure_base_id(data: Optional[Dict[str, Any]], base_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Ensure a data dictionary includes base_id.
    
    If data already has base_id, keeps it.
    Otherwise, adds base_id (from parameter or request context).
    
    Args:
        data: Dictionary to augment with base_id
        base_id: Optional explicit base_id to use
        
    Returns:
        Dict: Data dictionary with base_id included
    """
    if data is None:
        data = {}
    
    # If data already has base_id, keep it
    if 'base_id' in data and data['base_id']:
        return data
    
    # Use provided base_id or extract from request
    if base_id is None:
        base_id = get_base_id_from_request()
    
    data['base_id'] = base_id
    return data


def ensure_base_id_list(data_list: list, base_id: Optional[str] = None) -> list:
    """
    Ensure all records in a list include base_id.
    
    Args:
        data_list: List of dictionaries to augment
        base_id: Optional explicit base_id to use
        
    Returns:
        List: Records with base_id included
    """
    if base_id is None:
        base_id = get_base_id_from_request()
    
    augmented = []
    for record in data_list:
        if record is None:
            continue
        if not isinstance(record, dict):
            record = {'data': record}
        record['base_id'] = base_id
        augmented.append(record)
    
    return augmented


def validate_base_id(base_id: str) -> bool:
    """
    Validate base_id format.
    
    Airtable base IDs typically follow pattern: app[alphanumeric]
    
    Args:
        base_id: Base ID to validate
        
    Returns:
        bool: True if valid, False otherwise
    """
    if not base_id or not isinstance(base_id, str):
        return False
    
    base_id = base_id.strip()
    
    # Airtable base IDs start with 'app' followed by alphanumeric
    if base_id.startswith('app') and len(base_id) > 3 and base_id[3:].replace('_', '').isalnum():
        return True
    
    return False


def get_va_table_count(base_id: str, supabase_client, airtable_token: Optional[str] = None) -> int:
    """
    Dynamically get the number of VA tables for a given base_id.
    
    This function checks:
    1. Supabase scraping_jobs table for num_vas configuration
    2. If not found, queries Airtable base schema to count Daily_Outreach_Table_XX tables
    3. Falls back to environment variable NUM_VA_TABLES if both fail
    
    Args:
        base_id: The Airtable base ID
        supabase_client: Initialized Supabase client
        airtable_token: Optional Airtable API token (for schema inspection)
        
    Returns:
        int: Number of VA tables configured for this base
    """
    import os
    from pyairtable import Api
    
    logger.info(f"[get_va_table_count] Fetching VA table count for base_id: {base_id}")
    
    try:
        # Strategy 1: Check scraping_jobs table in Supabase
        result = supabase_client.table('scraping_jobs')\
            .select('num_vas, airtable_base_id')\
            .eq('airtable_base_id', base_id)\
            .limit(1)\
            .execute()
        
        if result.data and len(result.data) > 0:
            num_vas = result.data[0].get('num_vas')
            if num_vas and isinstance(num_vas, int) and num_vas > 0:
                logger.info(f"[get_va_table_count] Found num_vas={num_vas} in scraping_jobs table")
                return num_vas
    
    except Exception as e:
        logger.warning(f"[get_va_table_count] Could not query scraping_jobs: {e}")
    
    # Strategy 2: Query Airtable base schema directly
    if airtable_token:
        try:
            airtable = Api(airtable_token)
            base = airtable.base(base_id)
            schema = base.schema()
            
            # Count tables matching pattern Daily_Outreach_Table_XX
            va_table_count = 0
            for table in schema.tables:
                if table.name.startswith('Daily_Outreach_Table_'):
                    va_table_count += 1
            
            if va_table_count > 0:
                logger.info(f"[get_va_table_count] Found {va_table_count} VA tables in Airtable schema")
                return va_table_count
                
        except Exception as e:
            logger.warning(f"[get_va_table_count] Could not query Airtable schema: {e}")
    
    # Strategy 3: Fallback to environment variable
    fallback = int(os.getenv('NUM_VA_TABLES', 80))
    logger.warning(f"[get_va_table_count] Using fallback NUM_VA_TABLES={fallback}")
    return fallback


class BaseIdContext:
    """
    Context manager for scoping base_id through request lifecycle.
    
    Usage:
        with BaseIdContext('app12345') as ctx:
            ctx.base_id  # Use in queries
    """
    
    def __init__(self, base_id: Optional[str] = None):
        """Initialize with explicit base_id or extract from request."""
        self.base_id = base_id or get_base_id_from_request()
        logger.info(f"BaseIdContext initialized with base_id: {self.base_id}")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
    
    def scope_query(self, query_builder, column_name: str = 'base_id'):
        """
        Add base_id filter to a Supabase query builder.
        
        Args:
            query_builder: Supabase query object (from .table().select())
            column_name: Name of the base_id column (default: 'base_id')
            
        Returns:
            Modified query builder with base_id filter
        """
        logger.debug(f"Scoping query to base_id={self.base_id}")
        return query_builder.eq(column_name, self.base_id)
