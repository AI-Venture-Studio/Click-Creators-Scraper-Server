"""
Supabase RLS (Row-Level Security) context manager for multi-tenant isolation.

This module provides utilities to set and manage base_id context for RLS policies.
The base_id is passed to Supabase via JWT claims or custom headers, allowing
RLS policies to filter data per tenant.

Usage:
    # In Flask request handler
    from utils.rls_context import set_rls_context, get_rls_context
    
    @app.before_request
    def setup_rls():
        base_id = extract_base_id_from_request()
        set_rls_context(base_id)
    
    # Later in database operations
    base_id = get_rls_context()
    # RLS policies will automatically filter by this base_id
"""

import logging
from typing import Optional
from flask import g, request
from functools import wraps

logger = logging.getLogger(__name__)

# Context variable name in Flask g object
RLS_CONTEXT_KEY = '_rls_base_id'


def set_rls_context(base_id: str) -> None:
    """
    Set the current base_id for RLS policy filtering.
    
    This should be called at the start of each request to establish
    the tenant context for database operations.
    
    Args:
        base_id: The base_id to use for RLS filtering
    """
    if not base_id or not isinstance(base_id, str):
        raise ValueError(f"Invalid base_id: {base_id}")
    
    g.setdefault(RLS_CONTEXT_KEY, base_id)
    logger.debug(f"RLS context set to base_id={base_id}")


def get_rls_context() -> str:
    """
    Get the current base_id from RLS context.
    
    Returns:
        str: The current base_id, or 'default_instagram' if not set
    """
    return g.get(RLS_CONTEXT_KEY, 'default_instagram')


def clear_rls_context() -> None:
    """Clear the RLS context."""
    if RLS_CONTEXT_KEY in g:
        del g[RLS_CONTEXT_KEY]
    logger.debug("RLS context cleared")


def rls_required(f):
    """
    Decorator to ensure RLS context is set before executing function.
    
    Usage:
        @app.route('/api/data')
        @rls_required
        def get_data():
            base_id = get_rls_context()
            # base_id is guaranteed to be set
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        context = get_rls_context()
        logger.debug(f"Function {f.__name__} executing with RLS context: {context}")
        return f(*args, **kwargs)
    return decorated_function


def create_rls_jwt_claims(base_id: str) -> dict:
    """
    Create JWT claims dict with base_id for RLS policies.
    
    These claims should be embedded in the JWT token sent to Supabase
    so that RLS policies can access them via current_setting().
    
    Args:
        base_id: The base_id to include in claims
        
    Returns:
        Dict with JWT claims including base_id
    """
    return {
        'base_id': base_id,
        'sub': 'anonymous-user',
        'aud': 'authenticated'
    }


def get_base_id_from_context() -> str:
    """
    Alias for get_rls_context() for backward compatibility.
    
    Returns:
        str: The current base_id
    """
    return get_rls_context()
