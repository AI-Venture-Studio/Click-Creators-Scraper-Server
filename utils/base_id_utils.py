"""
Multi-tenant base_id utility functions.

This module provides helper functions for:
1. Extracting base_id from request headers/body
2. Providing default base_id for backward compatibility
3. Validating base_id format
4. Scoping queries to specific base_id
"""

import logging
from typing import Optional, Dict, Any
from flask import request

logger = logging.getLogger(__name__)


def get_base_id_from_request() -> str:
    """
    Extract base_id from request with fallback to default.
    
    Priority order:
    1. X-Base-Id header
    2. base_id field in JSON body
    3. Default: 'default_instagram' (for backward compatibility)
    
    Returns:
        str: The base_id to use for this request
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
        
        # Fallback to default for backward compatibility
        logger.debug("No base_id specified, using default: 'default_instagram'")
        return 'default_instagram'
        
    except Exception as e:
        logger.warning(f"Error extracting base_id from request: {e}")
        return 'default_instagram'


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
    Our default is: 'default_instagram'
    
    Args:
        base_id: Base ID to validate
        
    Returns:
        bool: True if valid, False otherwise
    """
    if not base_id or not isinstance(base_id, str):
        return False
    
    base_id = base_id.strip()
    
    # Allow our default placeholder
    if base_id == 'default_instagram':
        return True
    
    # Airtable base IDs start with 'app' followed by alphanumeric
    if base_id.startswith('app') and len(base_id) > 3 and base_id[3:].replace('_', '').isalnum():
        return True
    
    return False


def get_default_base_id() -> str:
    """
    Get the default base_id for backward compatibility.
    
    Returns:
        str: 'default_instagram'
    """
    return 'default_instagram'


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
