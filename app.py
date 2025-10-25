"""
Instagram Follower Scraper API

A Flask API that provides functionality to scrape Instagram followers from specified accounts,
detect their gender, filter them based on gender preferences, and persist to Supabase.

REFACTORED FOR PRODUCTION:
- Asynchronous task processing with Celery
- Background workers for scalability
- Batch operations for memory efficiency
- Logging and error tracking with Sentry
- Rate limiting for API protection
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
import logging
import threading
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.celery import CeleryIntegration
from dotenv import load_dotenv
from apify_client import ApifyClient
import pandas as pd
import gender_guesser.detector as gender
import re
from typing import Optional, List, Dict, Any
from supabase import create_client, Client
from supabase.lib.client_options import ClientOptions
from datetime import datetime, timezone, date, timedelta
import uuid
import random
import time
from pyairtable import Api
import traceback

# Import utility modules
from utils.airtable_creator import AirtableCreator, create_airtable_base
from utils.base_id_utils import get_base_id_from_request, ensure_base_id, ensure_base_id_list, validate_base_id, get_va_table_count
from utils.rls_context import set_rls_context, get_rls_context

# Load environment variables from .env file
load_dotenv()

# ===================================================================
# LOGGING CONFIGURATION
# ===================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ===================================================================
# SENTRY ERROR TRACKING
# ===================================================================
if os.getenv('SENTRY_DSN'):
    sentry_sdk.init(
        dsn=os.getenv('SENTRY_DSN'),
        integrations=[
            FlaskIntegration(),
            CeleryIntegration()
        ],
        traces_sample_rate=0.1,  # 10% performance monitoring
        environment=os.getenv('FLASK_ENV', 'development'),
        release=os.getenv('APP_VERSION', '1.0.0')
    )
    logger.info("Sentry error tracking initialized")
else:
    logger.warning("SENTRY_DSN not set, error tracking disabled")

# Constants
DEFAULT_PROFILES_PER_TABLE = 180  # Fallback if client doesn't send value

# ===================================================================
# FLASK APP INITIALIZATION
# ===================================================================
app = Flask(__name__)

# CORS configuration with restricted origins
allowed_origins = os.getenv('ALLOWED_ORIGINS', '*').split(',')
CORS(app, resources={
    r"/api/*": {
        "origins": allowed_origins,
        "methods": ["GET", "POST"],
        "allow_headers": ["Content-Type", "X-API-Key", "X-Base-Id"]
    }
})

# Rate limiting configuration
# Use in-memory storage to avoid SSL issues with Redis for rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per hour"],
    storage_uri='memory://'  # Use in-memory storage instead of Redis
)

logger.info("Flask app initialized with CORS and rate limiting")


# ===================================================================
# RLS CONTEXT SETUP
# ===================================================================
# Initialize RLS context on every request with the base_id
# This allows Supabase RLS policies to filter data per tenant

@app.before_request
def setup_rls_context():
    """
    Set up RLS context for the current request.
    
    Extracts base_id from request headers/body and sets it in the RLS context,
    which is then used by Supabase RLS policies to filter data per tenant.
    
    Skips RLS setup for:
    - OPTIONS requests (CORS preflight)
    - Health check endpoints (/, /health)
    - Static file requests
    """
    # Skip RLS setup for OPTIONS requests (CORS preflight)
    if request.method == 'OPTIONS':
        return
    
    # Skip RLS setup for health check and root endpoints
    if request.path in ['/', '/health', '/favicon.ico']:
        return
    
    try:
        # Extract base_id from request (uses priority: header > body)
        # required=False allows requests without base_id to proceed
        # Individual endpoints can validate if they need it
        base_id = get_base_id_from_request(required=False)
        
        # Only set RLS context if base_id is provided
        if base_id:
            # Validate base_id format
            if not validate_base_id(base_id):
                logger.warning(f"Invalid base_id format in request: {base_id}")
                # Still set it (validation error will be caught later in endpoint)
            
            # Set RLS context for this request
            set_rls_context(base_id)
            
            logger.debug(f"RLS context initialized for base_id={base_id}")
        else:
            logger.debug(f"No base_id provided for {request.method} {request.path}")
        
    except Exception as e:
        logger.error(f"Error setting up RLS context: {e}")
        # Continue without RLS context - individual endpoints will validate if needed


logger.info("✓ RLS context setup enabled for multi-tenant isolation")


# ===================================================================
# SUPABASE CLIENT WITH CONNECTION POOLING (THREAD-SAFE)
# ===================================================================
# Use singleton pattern with thread lock to prevent race conditions in multi-threaded Flask
_supabase_client = None
_supabase_lock = threading.Lock()

def get_supabase_client() -> Client:
    """
    Initialize and return Supabase client using service role key.
    
    OPTIMIZED FOR 500K+ SCALE:
    - Thread-safe singleton pattern to reuse the same client instance
    - Connection pooling with limits to prevent pool exhaustion
    - Configurable pool size via environment variable
    - Automatic connection cleanup and recycling
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
        
        # Configure connection pooling for scale
        # Free Tier: Max 50 connections total across all clients
        # Render Free: 1 web worker + 1 celery worker = need conservative pool
        # Default: 5 connections per process (safe for free tier)
        # Pro tier: Increase to 20-30
        pool_size = int(os.getenv('SUPABASE_POOL_SIZE', '5'))
        
        # Create client options with proper ClientOptions object
        options = ClientOptions(
            schema='public',
            headers={
                'x-client-info': 'instagram-scraper-api/1.0'
            },
            auto_refresh_token=False,
            persist_session=False
        )
        
        _supabase_client = create_client(
            supabase_url, 
            supabase_key,
            options=options
        )
        
        logger.info(f"✓ Supabase client initialized with connection pool (size: {pool_size}, tier: free)")
        
        return _supabase_client


def get_airtable_client() -> Api:
    """
    Initialize and return Airtable API client.
    
    Returns:
        Airtable API client instance
    """
    airtable_token = os.getenv('AIRTABLE_ACCESS_TOKEN')
    
    if not airtable_token:
        raise ValueError("AIRTABLE_ACCESS_TOKEN environment variable is required.")
    
    return Api(airtable_token)


def scrape_followers(accounts: list, max_count: int = 5) -> dict:
    """
    Handles API requests and Instagram scraping logic.
    
    Args:
        accounts: A list of Instagram account usernames to scrape followers from.
        max_count: Maximum followers to scrape per account (default: 5).
        
    Returns:
        A dictionary mapping each account to their extracted followers data.
        Each follower entry contains username, full_name, follower_count, following_count, posts_count.
    """
    # Initialize the ApifyClient with API token from environment variable
    api_key = os.getenv('APIFY_API_KEY')
    if not api_key:
        raise ValueError("APIFY_API_KEY environment variable is required. Please set it in your .env file or environment.")
    
    client = ApifyClient(api_key)
    
    # Prepare the Actor input
    run_input = {
        "usernames": accounts,
        "max_count": max_count,  # Use the provided max_count parameter
    }
    
    # Run the Actor and wait for it to finish
    actor_key = os.getenv('APIFY_ACTOR_ID')

    if not actor_key:
        raise ValueError("APIFY_ACTOR_ID environment variable is required. Please set it in your .env file or environment.")

    run = client.actor(actor_key).call(run_input=run_input)
    
    # Fetch Actor results and store in a list
    data = []
    for item in client.dataset(run["defaultDatasetId"]).iterate_items():
        data.append(item)
    
    # Create pandas DataFrame from the collected data
    followers_df = pd.DataFrame(data)
    
    # Drop unnecessary columns to clean up the data
    columns_to_drop = ['profile_pic_url', 'latest_story_ts', 'is_verified', 'is_private']
    followers_df = followers_df.drop(columns=columns_to_drop, errors='ignore')
    
    # Convert DataFrame to dictionary format for easier processing
    followers_dict = {}
    for _, row in followers_df.iterrows():
        follower_data = {
            'username': row.get('username', ''),
            'full_name': row.get('full_name') or row.get('fullname', ''),
            'follower_count': row.get('follower_count', 0),
            'following_count': row.get('following_count', 0),
            'posts_count': row.get('posts_count', 0),
            'id': row.get('id', row.get('username', ''))  # Use ID or fallback to username
        }
        # Use username as key for each follower
        followers_dict[row.get('username', '')] = follower_data
    
    return followers_dict


def detect_gender(followers: dict) -> dict:
    """
    Performs gender detection on the scraped followers.
    
    Args:
        followers: Dictionary of followers with their profile information.
        
    Returns:
        Dictionary mapping each follower username to their detected gender 
        ("male", "female", or "unknown").
    """
    # Initialize the gender detector
    detector = gender.Detector(case_sensitive=False)
    
    def extract_names(text: str) -> List[str]:
        """Extract potential names from text, handling various formats."""
        if not text:
            return []
        
        # Remove common prefixes and suffixes
        cleaned = re.sub(r'(^(mrs?|ms|dr|prof|sir|lady|miss)\.?\s+)|(\d+|_+|\.+)', 
                        '', text, flags=re.IGNORECASE)
        
        # Split by common separators and extract alphabetic sequences
        parts = re.split(r'[_\.\-\s\d]+', cleaned)
        names = []
        
        for part in parts:
            # Extract alphabetic sequences of reasonable length (2-20 chars)
            name_matches = re.findall(r'[A-Za-z]{2,20}', part)
            names.extend(name_matches)
        
        # Exclude common non-name words but keep gender-indicating titles
        excluded_words = {
            'the', 'and', 'official', 'real', 'true', 'page', 'account', 'profile',
            'fitness', 'gym', 'workout', 'life', 'love', 'style', 'blog', 'shop'
        }
        
        return [name for name in names if name.lower() not in excluded_words and len(name) >= 2]
    
    def check_gender_keywords(text: str) -> str:
        """Check for gender-indicating keywords in text."""
        if not text:
            return 'unknown'
        
        text_lower = text.lower()
        
        # Male-indicating words
        male_keywords = ['king', 'prince', 'sir', 'mr', 'lord', 'duke']
        # Female-indicating words  
        female_keywords = ['queen', 'princess', 'lady', 'mrs', 'ms', 'miss', 'duchess']
        
        for keyword in male_keywords:
            if keyword in text_lower:
                return 'male'
                
        for keyword in female_keywords:
            if keyword in text_lower:
                return 'female'
                
        return 'unknown'
    
    def classify_gender(gender_result: str) -> str:
        """Classify gender_guesser results into male/female/unknown."""
        if gender_result in ['male', 'mostly_male']:
            return 'male'
        elif gender_result in ['female', 'mostly_female']:
            return 'female'
        else:
            return 'unknown'
    
    def guess_gender_robust(username: str, full_name: Optional[str] = None) -> str:
        """
        Robust gender detection function that tries multiple strategies.
        
        Args:
            username: Instagram username
            full_name: Full name from profile (optional)
        
        Returns:
            'male', 'female', or 'unknown'
        """
        # Strategy 1: Check for gender keywords first (in both username and full_name)
        for text in [full_name, username]:
            keyword_result = check_gender_keywords(text)
            if keyword_result != 'unknown':
                return keyword_result
        
        # Strategy 2: Try full_name with name detection
        if full_name:
            names = extract_names(full_name)
            for name in names:
                result = detector.get_gender(name)
                classified = classify_gender(result)
                if classified != 'unknown':
                    return classified
        
        # Strategy 3: Try username with name detection
        if username:
            names = extract_names(username)
            for name in names:
                result = detector.get_gender(name)
                classified = classify_gender(result)
                if classified != 'unknown':
                    return classified
        
        return 'unknown'
    
    # Apply gender detection to all followers
    followers_gender = {}
    for username, follower_data in followers.items():
        detected_gender = guess_gender_robust(
            username, 
            follower_data.get('full_name', '')
        )
        followers_gender[username] = detected_gender
    
    return followers_gender


def filter_by_gender(followers_gender: dict, target_gender: str) -> dict:
    """
    Filters followers based on the specified gender.
    
    Args:
        followers_gender: Dictionary mapping follower usernames to their detected gender.
        target_gender: Target gender to filter for ("male" or "female").
        
    Returns:
        Dictionary of filtered followers according to gender rules:
        - If target_gender="male", returns "male" + "unknown"
        - If target_gender="female", returns "female" + "unknown"
    """
    filtered_followers = {}
    
    if target_gender.lower() == "male":
        # Include male and unknown gender followers
        for username, gender in followers_gender.items():
            if gender in ["male", "unknown"]:
                filtered_followers[username] = gender
                
    elif target_gender.lower() == "female":
        # Include female and unknown gender followers
        for username, gender in followers_gender.items():
            if gender in ["female", "unknown"]:
                filtered_followers[username] = gender
    else:
        # Invalid target_gender, return empty dict
        print(f"Warning: Invalid target_gender '{target_gender}'. Must be 'male' or 'female'.")
        return {}
    
    return filtered_followers


def process_accounts(accounts: list, target_gender: str = "male", max_count_per_account: int = 5) -> dict:
    """
    Orchestrates the entire workflow.
    
    Args:
        accounts: List of Instagram usernames to scrape followers from.
        target_gender: Target gender to filter for ("male" or "female").
        max_count_per_account: Maximum followers to scrape per account.
        
    Returns:
        Dictionary with filtered followers data and summary statistics.
    """
    print(f"Starting Instagram follower analysis for accounts: {accounts}")
    print(f"Target gender: {target_gender}")
    print(f"Max count per account: {max_count_per_account}")
    
    # Step 1: Scrape followers from specified accounts
    print("\n1. Scraping followers...")
    followers = scrape_followers(accounts, max_count_per_account)
    print(f"   Scraped {len(followers)} total followers")
    
    # Step 2: Detect gender for all followers
    print("\n2. Detecting gender...")
    followers_gender = detect_gender(followers)
    
    # Display gender distribution
    gender_counts = {}
    for gender in followers_gender.values():
        gender_counts[gender] = gender_counts.get(gender, 0) + 1
    
    print("   Gender distribution:")
    for gender, count in gender_counts.items():
        print(f"     {gender}: {count}")
    
    # Step 3: Filter followers by target gender
    print(f"\n3. Filtering by target gender '{target_gender}'...")
    filtered_followers = filter_by_gender(followers_gender, target_gender)
    print(f"   Filtered results: {len(filtered_followers)} followers")
    
    # Create complete follower data with gender information
    complete_follower_data = []
    for username in filtered_followers.keys():
        follower_info = followers.get(username, {})
        complete_follower_data.append({
            'id': follower_info.get('id', username),  # Use ID or fallback to username
            'fullName': follower_info.get('full_name', ''),
            'username': username,
        })
    
    return {
        'accounts': complete_follower_data,
        'totalFiltered': len(complete_follower_data),
        'totalScraped': len(followers),
        'genderDistribution': gender_counts
    }


# ============================================================================
# HEALTH CHECK ENDPOINTS (no base_id required)
# ============================================================================

@app.route('/', methods=['GET'])
def root():
    """
    Root endpoint for basic health checks and uptime monitoring.
    Does not require base_id authentication.
    """
    return jsonify({
        'status': 'ok',
        'service': 'Instagram Scraper API',
        'version': '1.0.0'
    }), 200


# ============================================================================
# API ENDPOINTS (base_id required via before_request handler)
# ============================================================================

@app.route('/api/scrape-followers', methods=['POST'])
def scrape_followers_api():
    """
    API endpoint to scrape Instagram followers.
    
    Expected JSON payload:
    {
        "accounts": ["username1", "username2"],
        "targetGender": "male" (optional, defaults to "male"),
        "totalScrapeCount": 150 (optional, total accounts to scrape across all usernames)
    }
    
    Returns:
    {
        "success": true,
        "data": {
            "accounts": [
                {
                    "id": "account_id",
                    "fullName": "Full Name",
                    "username": "username"
                }
            ],
            "totalFiltered": 10,
            "totalScraped": 15,
            "genderDistribution": {
                "male": 8,
                "female": 4,
                "unknown": 3
            }
        }
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
        target_gender = data.get('targetGender', 'male')  # Default to male
        total_scrape_count = data.get('totalScrapeCount', None)  # User-defined total count
        
        if not isinstance(accounts, list) or len(accounts) == 0:
            return jsonify({
                'success': False,
                'error': 'Accounts must be a non-empty list'
            }), 400
        
        # Compute per-account scrape count
        if total_scrape_count is not None:
            if total_scrape_count <= 0:
                return jsonify({
                    'success': False,
                    'error': 'totalScrapeCount must be greater than 0'
                }), 400
            
            # Compute how many accounts to scrape per username
            per_account_count = int(total_scrape_count / len(accounts))
            
            if per_account_count == 0:
                return jsonify({
                    'success': False,
                    'error': f'totalScrapeCount ({total_scrape_count}) is too small for {len(accounts)} accounts. Need at least {len(accounts)} total.'
                }), 400
            
            print(f"Total scrape count: {total_scrape_count}")
            print(f"Number of accounts: {len(accounts)}")
            print(f"Per-account count: {per_account_count}")
        else:
            # Fallback to default if not provided
            per_account_count = 5
            print(f"No totalScrapeCount provided, using default per-account count: {per_account_count}")
        
        # Process the accounts with computed per-account count
        result = process_accounts(accounts, target_gender, per_account_count)
        
        return jsonify({
            'success': True,
            'data': result
        })
        
        return jsonify({
            'success': True,
            'data': result
        })
        
    except Exception as e:
        print(f"Error processing request: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/ingest', methods=['POST'])
def ingest_profiles():
    """
    API endpoint to ingest scraped profiles into Supabase.
    
    This endpoint is idempotent: calling it multiple times with the same profiles
    will not create duplicates in global_usernames.
    
    Expected JSON payload:
    {
        "profiles": [
            {
                "id": "123456",
                "username": "john_doe",
                "full_name": "John Doe"
            }
        ],
        "base_id": "appXYZ123ABC" (optional, defaults to 'default_instagram')
    }
    
    OR pass base_id via header:
    X-Base-Id: appXYZ123ABC
    
    Returns:
    {
        "success": true,
        "base_id": "appXYZ123ABC",
        "inserted_raw": 10,
        "added_to_global": 8,
        "skipped_existing": 2
    }
    """
    try:
        # Get JSON data from request
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
                'base_id': get_base_id_from_request(),
                'inserted_raw': 0,
                'added_to_global': 0,
                'skipped_existing': 0
            })
        
        # Extract base_id with fallback to default
        base_id = get_base_id_from_request()
        
        if not validate_base_id(base_id):
            return jsonify({
                'success': False,
                'error': f'Invalid base_id format: {base_id}'
            }), 400
        
        # Initialize Supabase client
        supabase = get_supabase_client()
        
        # Counters for response
        inserted_raw = 0
        added_to_global = 0
        skipped_existing = 0
        
        logger.info(f"Ingesting {len(profiles)} profiles for base_id={base_id}")
        
        # Process each profile
        for profile in profiles:
            # Validate required fields
            if 'id' not in profile or 'username' not in profile:
                print(f"Warning: Skipping profile with missing id or username: {profile}")
                continue
            
            profile_id = str(profile['id'])
            username = profile['username']
            full_name = profile.get('full_name', '')
            
            # Step 1: Insert into raw_scraped_profiles with base_id
            try:
                supabase.table('raw_scraped_profiles').insert({
                    'id': profile_id,
                    'username': username,
                    'full_name': full_name,
                    'base_id': base_id,
                    'scraped_at': datetime.now(timezone.utc).isoformat()
                }).execute()
                inserted_raw += 1
                print(f"✓ Inserted {username} into raw_scraped_profiles (base_id={base_id})")
            except Exception as e:
                print(f"Warning: Failed to insert {username} into raw_scraped_profiles: {str(e)}")
            
            # Step 2: Check if profile exists in global_usernames (scoped to base_id)
            try:
                existing = supabase.table('global_usernames')\
                    .select('id')\
                    .eq('id', profile_id)\
                    .eq('base_id', base_id)\
                    .execute()
                
                if existing.data and len(existing.data) > 0:
                    # Profile already exists in global_usernames for this base_id
                    skipped_existing += 1
                    print(f"○ Skipped {username} (already in global_usernames for base_id={base_id})")
                else:
                    # Profile doesn't exist for this base_id, insert it
                    supabase.table('global_usernames').insert({
                        'id': profile_id,
                        'username': username,
                        'full_name': full_name,
                        'used': False,
                        'base_id': base_id,
                        'created_at': datetime.now(timezone.utc).isoformat()
                    }).execute()
                    added_to_global += 1
                    print(f"✓ Added {username} to global_usernames (base_id={base_id})")
                    
            except Exception as e:
                print(f"Warning: Failed to process {username} for global_usernames: {str(e)}")
                skipped_existing += 1
        
        logger.info(f"Ingest complete for base_id={base_id}: {inserted_raw} raw, {added_to_global} new global, {skipped_existing} skipped")
        
        return jsonify({
            'success': True,
            'base_id': base_id,
            'inserted_raw': inserted_raw,
            'added_to_global': added_to_global,
            'skipped_existing': skipped_existing
        })
        
    except Exception as e:
        print(f"Error processing ingest request: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/daily-selection', methods=['POST'])
def daily_selection():
    """
    API endpoint to select fresh profiles for a new campaign.
    
    Creates a new campaign and selects up to (NUM_VA_TABLES * profiles_per_table) unused profiles
    from global_usernames, marking them as used.
    
    Expected JSON payload:
    {
        "campaign_date": "2025-10-02" (optional, defaults to today),
        "profiles_per_table": 180 (optional, should be sent from client's NEXT_PUBLIC_PROFILES_PER_TABLE),
        "base_id": "appXYZ123ABC" (optional, defaults to 'default_instagram')
    }
    
    OR pass base_id via header:
    X-Base-Id: appXYZ123ABC
    
    Returns:
    {
        "success": true,
        "campaign_id": "uuid",
        "base_id": "appXYZ123ABC",
        "total_selected": 14400
    }
    """
    try:
        # Get JSON data from request
        data = request.get_json() or {}
        
        # Extract base_id with fallback to default
        base_id = get_base_id_from_request()
        
        if not validate_base_id(base_id):
            return jsonify({
                'success': False,
                'error': f'Invalid base_id format: {base_id}'
            }), 400
        
        # Get profiles_per_table from client (should be NEXT_PUBLIC_PROFILES_PER_TABLE)
        profiles_per_table = data.get('profiles_per_table')
        
        if profiles_per_table is not None:
            profiles_per_table = int(profiles_per_table)
            # Validate
            if profiles_per_table <= 0:
                return jsonify({
                    'success': False,
                    'error': 'profiles_per_table must be a positive integer'
                }), 400
            print(f"✓ Using profiles_per_table from client: {profiles_per_table}")
        else:
            profiles_per_table = DEFAULT_PROFILES_PER_TABLE
            print(f"⚠️ WARNING: Client did not send profiles_per_table, using fallback: {profiles_per_table}")
        
        # Initialize Supabase client
        supabase = get_supabase_client()
        
        # Get number of VA tables dynamically from database/Airtable
        airtable_token = os.getenv('AIRTABLE_ACCESS_TOKEN')
        num_va_tables = get_va_table_count(base_id, supabase, airtable_token)
        
        # Calculate target count: num_va_tables * profiles_per_table
        target_count = num_va_tables * profiles_per_table
        
        # Get campaign date (default to today)
        campaign_date_str = data.get('campaign_date')
        if campaign_date_str:
            campaign_date_obj = datetime.strptime(campaign_date_str, '%Y-%m-%d').date()
        else:
            campaign_date_obj = date.today()
        
        print(f"Starting daily selection for {campaign_date_obj} with base_id={base_id}...")
        print(f"Target: {target_count} profiles ({num_va_tables} VA tables × {profiles_per_table} profiles/table)")
        
        # Step 1: Create a new campaign with base_id
        campaign_id = str(uuid.uuid4())
        
        campaign_response = supabase.table('campaigns').insert({
            'campaign_id': campaign_id,
            'campaign_date': campaign_date_obj.isoformat(),
            'total_assigned': 0,
            'base_id': base_id,
            'airtable_base_id': base_id,  # Store the Airtable base ID (same as base_id)
            'status': False,  # Default to False (failed), will update to True (success) after Airtable sync
            'created_at': datetime.now(timezone.utc).isoformat()
        }).execute()
        
        print(f"✓ Created campaign: {campaign_id} (base_id={base_id})")
        
        # Step 2: Select up to target_count unused profiles from global_usernames
        # Scoped to the specific base_id
        available_profiles = supabase.table('global_usernames')\
            .select('id, username, full_name')\
            .eq('used', False)\
            .eq('base_id', base_id)\
            .limit(target_count)\
            .execute()
        
        if not available_profiles.data:
            return jsonify({
                'success': False,
                'error': f'No unused profiles available in global_usernames for base_id={base_id}'
            }), 400
        
        selected_profiles = available_profiles.data
        total_selected = len(selected_profiles)
        
        print(f"✓ Selected {total_selected} unused profiles from base_id={base_id}")
        
        # Step 3: Mark selected profiles as used
        profile_ids = [profile['id'] for profile in selected_profiles]
        
        # Update all selected profiles to used=true (scoped to base_id)
        for profile_id in profile_ids:
            supabase.table('global_usernames')\
                .update({
                    'used': True,
                    'used_at': datetime.now(timezone.utc).isoformat()
                })\
                .eq('id', profile_id)\
                .eq('base_id', base_id)\
                .execute()
        
        print(f"✓ Marked {total_selected} profiles as used for base_id={base_id}")
        
        # Step 4: Insert into daily_assignments with placeholders and base_id
        assignments = []
        for profile in selected_profiles:
            assignments.append({
                'assignment_id': str(uuid.uuid4()),
                'campaign_id': campaign_id,
                'va_table_number': 0,  # Placeholder - will be assigned during distribution
                'position': 0,  # Placeholder - will be assigned during distribution
                'id': profile['id'],
                'username': profile['username'],
                'full_name': profile['full_name'],
                'base_id': base_id,
                'status': 'pending',
                'assigned_at': datetime.now(timezone.utc).isoformat()
            })
        
        # Batch insert assignments (Supabase handles this efficiently)
        supabase.table('daily_assignments').insert(assignments).execute()
        
        print(f"✓ Inserted {total_selected} assignments for base_id={base_id}")
        
        # Step 5: Update campaign total_assigned
        supabase.table('campaigns')\
            .update({'total_assigned': total_selected})\
            .eq('campaign_id', campaign_id)\
            .execute()
        
        print(f"✓ Updated campaign total_assigned to {total_selected}")
        
        logger.info(f"Daily selection complete for base_id={base_id}: campaign_id={campaign_id}, total_selected={total_selected}")
        
        return jsonify({
            'success': True,
            'campaign_id': campaign_id,
            'base_id': base_id,
            'total_selected': total_selected,
            'campaign_date': campaign_date_obj.isoformat()
        })
        
    except Exception as e:
        print(f"Error processing daily selection request: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/distribute/<campaign_id>', methods=['POST'])
def distribute_campaign(campaign_id: str):
    """
    API endpoint to distribute campaign profiles to VA tables.
    
    Fetches all unassigned profiles for a campaign, shuffles them randomly,
    and assigns them to VA tables with positions.
    
    URL Parameters:
        campaign_id: UUID of the campaign to distribute
    
    Optional JSON payload:
    {
        "profiles_per_table": 180,  (optional, should be sent from client's NEXT_PUBLIC_PROFILES_PER_TABLE)
        "base_id": "appXYZ123ABC"   (optional, defaults to 'default_instagram')
    }
    
    OR pass base_id via header:
    X-Base-Id: appXYZ123ABC
    
    Returns:
    {
        "success": true,
        "campaign_id": "uuid",
        "base_id": "appXYZ123ABC",
        "va_tables": 80,
        "assigned_per_table": 180,
        "total_distributed": 14400
    }
    """
    try:
        # Extract base_id with fallback to default
        base_id = get_base_id_from_request()
        
        if not validate_base_id(base_id):
            return jsonify({
                'success': False,
                'error': f'Invalid base_id format: {base_id}'
            }), 400
        
        # Initialize Supabase client
        supabase = get_supabase_client()
        
        # Get number of VA tables dynamically from database/Airtable
        airtable_token = os.getenv('AIRTABLE_ACCESS_TOKEN')
        num_va_tables = get_va_table_count(base_id, supabase, airtable_token)
        
        # Get profiles_per_table from request body (should be from client's NEXT_PUBLIC_PROFILES_PER_TABLE)
        data = request.get_json() or {}
        profiles_per_table = data.get('profiles_per_table')
        
        if profiles_per_table is not None:
            profiles_per_table = int(profiles_per_table)
            # Validate
            if profiles_per_table <= 0:
                return jsonify({
                    'success': False,
                    'error': 'profiles_per_table must be a positive integer'
                }), 400
            print(f"✓ Using profiles_per_table from client: {profiles_per_table}")
        else:
            profiles_per_table = DEFAULT_PROFILES_PER_TABLE
            print(f"⚠️ WARNING: Client did not send profiles_per_table, using fallback: {profiles_per_table}")

        print(f"Starting distribution for campaign {campaign_id} with base_id={base_id}...")
        print(f"Configuration: {num_va_tables} VA tables (dynamic), {profiles_per_table} profiles per table")
        
        # Step 1: Verify campaign exists (scoped to base_id)
        campaign = supabase.table('campaigns')\
            .select('campaign_id, campaign_date, total_assigned, base_id')\
            .eq('campaign_id', campaign_id)\
            .eq('base_id', base_id)\
            .execute()
        
        if not campaign.data or len(campaign.data) == 0:
            return jsonify({
                'success': False,
                'error': f'Campaign {campaign_id} not found for base_id={base_id}'
            }), 404
        
        campaign_info = campaign.data[0]
        print(f"✓ Found campaign: {campaign_info['campaign_date']} with {campaign_info['total_assigned']} assignments")
        
        # Step 2: Fetch all unassigned profiles (va_table_number=0) scoped to base_id
        unassigned = supabase.table('daily_assignments')\
            .select('assignment_id, id, username, full_name')\
            .eq('campaign_id', campaign_id)\
            .eq('base_id', base_id)\
            .eq('va_table_number', 0)\
            .execute()
        
        if not unassigned.data or len(unassigned.data) == 0:
            return jsonify({
                'success': False,
                'error': 'No unassigned profiles found for this campaign. Already distributed?'
            }), 400
        
        profiles = unassigned.data
        total_profiles = len(profiles)
        
        print(f"✓ Found {total_profiles} unassigned profiles")
        
        # Step 3: Shuffle profiles randomly
        random.shuffle(profiles)
        print(f"✓ Shuffled profiles randomly")
        
        # Step 4: Assign to VA tables
        distributed_count = 0
        current_table = 1
        current_position = 1
        
        for profile in profiles:
            # Update the assignment with VA table and position
            supabase.table('daily_assignments')\
                .update({
                    'va_table_number': current_table,
                    'position': current_position
                })\
                .eq('assignment_id', profile['assignment_id'])\
                .execute()
            
            distributed_count += 1
            
            # Move to next position
            current_position += 1
            
            # If we've filled this table, move to next table
            if current_position > profiles_per_table:
                current_position = 1
                current_table += 1
                
                # Stop if we've filled all VA tables
                if current_table > num_va_tables:
                    print(f"⚠ Reached maximum VA tables ({num_va_tables}), stopping distribution")
                    break
        
        # Calculate actual distribution stats
        # If current_position is 1, we just incremented to a new table but haven't used it yet
        # So the actual tables used is current_table - 1
        tables_used = current_table - 1 if current_position == 1 else current_table
        
        print(f"✓ Distributed {distributed_count} profiles across {tables_used} VA tables")
        
        logger.info(f"Distribution complete for base_id={base_id}, campaign_id={campaign_id}: {distributed_count} profiles distributed across {tables_used} tables")
        
        return jsonify({
            'success': True,
            'campaign_id': campaign_id,
            'base_id': base_id,
            'va_tables': tables_used,
            'assigned_per_table': profiles_per_table,
            'total_distributed': distributed_count,
            'total_available': total_profiles
        })
        
    except Exception as e:
        print(f"Error processing distribution request: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/airtable-sync/<campaign_id>', methods=['POST'])
def airtable_sync(campaign_id: str):
    """
    API endpoint to sync campaign assignments to Airtable tables.
    
    Fetches distributed profiles from daily_assignments and pushes them
    to Airtable tables (one table per VA, 180 profiles each).
    
    URL Parameters:
        campaign_id: UUID of the campaign to sync
    
    Optional JSON payload:
    {
        "base_id": "appXYZ123ABC" (optional, defaults to 'default_instagram')
    }
    
    OR pass base_id via header:
    X-Base-Id: appXYZ123ABC
    
    Returns:
    {
        "success": true,
        "campaign_id": "uuid",
        "base_id": "appXYZ123ABC",
        "tables_synced": 80,
        "records_synced": 14400
    }
    """
    try:
        # Extract base_id with fallback to default
        base_id = get_base_id_from_request()
        
        if not validate_base_id(base_id):
            return jsonify({
                'success': False,
                'error': f'Invalid base_id format: {base_id}'
            }), 400
        
        # Initialize clients
        supabase = get_supabase_client()
        airtable_token = os.getenv('AIRTABLE_ACCESS_TOKEN')
        airtable = get_airtable_client()
        
        # Get number of VA tables dynamically from database/Airtable
        num_va_tables = get_va_table_count(base_id, supabase, airtable_token)
        
        # Get Airtable base ID from request body or campaign metadata
        # Use silent=True to prevent error when no JSON body is sent
        data = request.get_json(silent=True) or {}
        airtable_base_id = data.get('airtable_base_id')
        
        # If not provided in request, try to fetch from campaign metadata in Supabase
        if not airtable_base_id:
            try:
                campaign = supabase.table('campaigns')\
                    .select('airtable_base_id')\
                    .eq('campaign_id', campaign_id)\
                    .eq('base_id', base_id)\
                    .single()\
                    .execute()
                
                if campaign.data and campaign.data.get('airtable_base_id'):
                    airtable_base_id = campaign.data['airtable_base_id']
                    logger.info(f"Retrieved Airtable base ID from campaign metadata: {airtable_base_id}")
                else:
                    logger.warning(f"No Airtable base ID found in campaign {campaign_id}")
            except Exception as e:
                logger.error(f"Error fetching Airtable base ID from campaign: {str(e)}")
        
        # Validate that we have an Airtable base ID
        if not airtable_base_id:
            return jsonify({
            'success': False,
            'error': 'Missing Airtable base ID. Please provide "airtable_base_id" in request body or ensure campaign has base ID configured.'
            }), 400
        
        
        if not airtable_base_id:
            return jsonify({
                'success': False,
                'error': 'AIRTABLE_BASE_ID environment variable not set'
            }), 500
        
        print(f"Starting Airtable sync for campaign {campaign_id} with base_id={base_id}...")
        print(f"Configuration: {num_va_tables} VA tables (dynamic), base ID: {airtable_base_id}")
        
        # Step 1: Verify campaign exists and fetch campaign_date (scoped to base_id)
        campaign = supabase.table('campaigns')\
            .select('campaign_id, campaign_date, total_assigned, base_id')\
            .eq('campaign_id', campaign_id)\
            .eq('base_id', base_id)\
            .execute()
        
        if not campaign.data or len(campaign.data) == 0:
            return jsonify({
                'success': False,
                'error': f'Campaign {campaign_id} not found for base_id={base_id}'
            }), 404
        
        campaign_info = campaign.data[0]
        campaign_date = campaign_info['campaign_date']
        print(f"✓ Found campaign: {campaign_date} with {campaign_info['total_assigned']} assignments")
        
        # Step 2: Fetch all assigned profiles (va_table_number > 0) scoped to base_id
        assigned = supabase.table('daily_assignments')\
            .select('va_table_number, position, id, username, full_name, status')\
            .eq('campaign_id', campaign_id)\
            .eq('base_id', base_id)\
            .gt('va_table_number', 0)\
            .order('va_table_number')\
            .order('position')\
            .execute()
        
        if not assigned.data or len(assigned.data) == 0:
            return jsonify({
                'success': False,
                'error': 'No assigned profiles found for this campaign. Run distribution first.'
            }), 400
        
        profiles = assigned.data
        total_profiles = len(profiles)
        
        print(f"✓ Found {total_profiles} assigned profiles")
        
        # Step 3: Group profiles by VA table
        profiles_by_table = {}
        for profile in profiles:
            table_num = profile['va_table_number']
            if table_num not in profiles_by_table:
                profiles_by_table[table_num] = []
            profiles_by_table[table_num].append(profile)
        
        print(f"✓ Grouped profiles into {len(profiles_by_table)} VA tables")
        
        # Step 4: Sync to Airtable with retry logic
        tables_synced = 0
        records_synced = 0
        max_retries = 3
        initial_backoff = 1  # seconds
        batch_size = 10  # Airtable batch limit
        
        def sync_with_retry(table, records, retries=0):
            """Helper function to sync records with exponential backoff."""
            try:
                # Split records into batches of 10
                for i in range(0, len(records), batch_size):
                    batch = records[i:i + batch_size]
                    table.batch_create(batch)
                    time.sleep(0.2)  # Rate limit protection (5 requests per second)
                return True
            except Exception as e:
                if retries < max_retries:
                    backoff_time = initial_backoff * (2 ** retries)
                    print(f"⚠ Retry {retries + 1}/{max_retries} after {backoff_time}s: {str(e)}")
                    time.sleep(backoff_time)
                    return sync_with_retry(table, records, retries + 1)
                else:
                    raise e
        
        # Sync each VA table
        for table_num in sorted(profiles_by_table.keys()):
            table_name = f"Daily_Outreach_Table_{table_num:02d}"
            table_profiles = profiles_by_table[table_num]
            
            print(f"Syncing {len(table_profiles)} profiles to {table_name}...")
            
            try:
                # Get Airtable table reference
                table = airtable.table(airtable_base_id, table_name)
                
                # Prepare records for Airtable
                airtable_records = []
                for profile in table_profiles:
                    airtable_records.append({
                        'id': profile['id'],
                        'username': profile['username'],
                        'full_name': profile['full_name'],
                        'position': profile['position'],
                        'campaign_date': campaign_date,
                        'progress_status': profile['status']  # singleSelect requires string, defaults to 'pending'
                    })
                
                # Sync with retry logic
                sync_with_retry(table, airtable_records)
                
                tables_synced += 1
                records_synced += len(table_profiles)
                print(f"✓ Synced {len(table_profiles)} records to {table_name}")
                
            except Exception as e:
                print(f"✗ Failed to sync {table_name}: {str(e)}")
                # Continue with other tables even if one fails
                continue
        
        print(f"✓ Completed sync: {tables_synced} tables, {records_synced} records")
        
        # Update campaign status based on sync results
        # Success (True): All 80 VA tables received their profiles
        # Failed (False): Less than 80 tables were synced
        campaign_status = True if tables_synced == num_va_tables and records_synced > 0 else False
        
        supabase.table('campaigns')\
            .update({'status': campaign_status})\
            .eq('campaign_id', campaign_id)\
            .eq('base_id', base_id)\
            .execute()
        
        status_text = 'success' if campaign_status else 'failed'
        print(f"✓ Updated campaign status to: {status_text} ({campaign_status})")
        print(f"  - Expected tables: {num_va_tables}, Synced: {tables_synced}")
        print(f"  - Total records synced: {records_synced}")
        
        logger.info(f"Airtable sync complete for base_id={base_id}, campaign_id={campaign_id}: {tables_synced} tables, {records_synced} records")
        
        return jsonify({
            'success': True,
            'campaign_id': campaign_id,
            'base_id': base_id,
            'tables_synced': tables_synced,
            'records_synced': records_synced,
            'campaign_status': campaign_status
        })
        
    except Exception as e:
        print(f"Error processing Airtable sync request: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # Mark campaign as failed (False) on exception
        try:
            supabase = get_supabase_client()
            supabase.table('campaigns')\
                .update({'status': False})\
                .eq('campaign_id', campaign_id)\
                .execute()
            print(f"✓ Updated campaign status to: failed (False) due to error")
        except Exception as status_error:
            print(f"⚠ Could not update campaign status: {str(status_error)}")
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


"""
OLD CLEANUP ENDPOINT - REPLACED BY NEW 4-STATUS WORKFLOW
This endpoint has been replaced by three new endpoints:
1. POST /api/sync-airtable-statuses - Sync VA manual updates from Airtable → Supabase
2. POST /api/mark-unfollow-due - Mark 7-day old 'followed' records as 'unfollow'
3. POST /api/delete-completed-after-delay - Delete 'completed' records after 24 hours

Kept for reference during transition. Remove after testing new workflow.

@app.route('/api/cleanup', methods=['POST'])
def cleanup():
    API endpoint to handle 7-day lifecycle cleanup.
    
    This endpoint:
    1. Marks assignments exactly 7 days old as "to_unfollow" in Supabase
    2. Updates those records in Airtable to "to_unfollow" status
    3. Deletes records older than 7 days from Airtable
    4. Deletes records older than 7 days from Supabase temporary tables
    
    Returns:
    {
        "success": true,
        "unfollow_marked": 100,
        "airtable_deleted": 50,
        "supabase_deleted": 150
    }
    try:
        # Get configuration
        num_va_tables = int(os.getenv('NUM_VA_TABLES', '80'))
        airtable_base_id = os.getenv('AIRTABLE_BASE_ID')
        
        if not airtable_base_id:
            return jsonify({
                'success': False,
                'error': 'AIRTABLE_BASE_ID environment variable not set'
            }), 500
        
        print("Starting 7-day lifecycle cleanup...")
        
        # Initialize clients
        supabase = get_supabase_client()
        airtable = get_airtable_client()
        
        # Calculate dates
        today = datetime.now(timezone.utc)
        exactly_7_days_ago = (today - timedelta(days=7)).date()
        older_than_7_days = (today - timedelta(days=8)).date()
        
        print(f"Today: {today.date()}")
        print(f"Exactly 7 days ago: {exactly_7_days_ago}")
        print(f"Older than 7 days: {older_than_7_days}")
        
        # === STEP 1: Mark 7-day old assignments as "to_unfollow" in Supabase ===
        print("\n1. Marking 7-day old assignments as 'to_unfollow' in Supabase...")
        
        # Find assignments from exactly 7 days ago
        seven_day_old = supabase.table('daily_assignments')\
            .select('assignment_id, va_table_number, position, id, username, campaign_id')\
            .gte('assigned_at', f'{exactly_7_days_ago}T00:00:00')\
            .lt('assigned_at', f'{exactly_7_days_ago}T23:59:59')\
            .eq('status', 'pending')\
            .execute()
        
        unfollow_marked = 0
        
        if seven_day_old.data:
            print(f"   Found {len(seven_day_old.data)} assignments from exactly 7 days ago")
            
            # Update status to "to_unfollow"
            for assignment in seven_day_old.data:
                supabase.table('daily_assignments')\
                    .update({'status': 'to_unfollow'})\
                    .eq('assignment_id', assignment['assignment_id'])\
                    .execute()
                unfollow_marked += 1
            
            print(f"   ✓ Marked {unfollow_marked} assignments as 'to_unfollow' in Supabase")
            
            # === STEP 2: Update those records in Airtable ===
            print("\n2. Updating Airtable records to 'to_unfollow' status...")
            
            # Group by VA table
            by_table = {}
            for assignment in seven_day_old.data:
                table_num = assignment['va_table_number']
                if table_num > 0:  # Only process assigned records
                    if table_num not in by_table:
                        by_table[table_num] = []
                    by_table[table_num].append(assignment)
            
            airtable_updated = 0
            for table_num, assignments in by_table.items():
                table_name = f"Daily_Outreach_Table_{table_num:02d}"
                
                try:
                    table = airtable.table(airtable_base_id, table_name)
                    
                    # Fetch all records from this table
                    all_records = table.all()
                    
                    # Update matching records
                    for assignment in assignments:
                        # Find the record by id field
                        for record in all_records:
                            if record['fields'].get('id') == assignment['id']:
                                # Update status to "to_unfollow"
                                table.update(record['id'], {'status': 'to_unfollow'})
                                airtable_updated += 1
                                break
                    
                    time.sleep(0.2)  # Rate limiting
                    
                except Exception as e:
                    print(f"   ⚠ Failed to update {table_name}: {str(e)}")
                    continue
            
            print(f"   ✓ Updated {airtable_updated} Airtable records to 'to_unfollow'")
        else:
            print("   No assignments found from exactly 7 days ago")
        
        # === STEP 3: Delete records older than 7 days from Airtable ===
        print(f"\n3. Deleting Airtable records older than {older_than_7_days}...")
        
        airtable_deleted = 0
        
        for table_num in range(1, num_va_tables + 1):
            table_name = f"Daily_Outreach_Table_{table_num:02d}"
            
            try:
                table = airtable.table(airtable_base_id, table_name)
                
                # Fetch all records
                all_records = table.all()
                
                # Filter records older than 7 days
                records_to_delete = []
                for record in all_records:
                    campaign_date_str = record['fields'].get('campaign_date')
                    if campaign_date_str:
                        # Parse date (ISO format: YYYY-MM-DD)
                        campaign_date = datetime.strptime(campaign_date_str, '%Y-%m-%d').date()
                        
                        if campaign_date < older_than_7_days:
                            records_to_delete.append(record['id'])
                
                # Delete in batches of 10
                for i in range(0, len(records_to_delete), 10):
                    batch = records_to_delete[i:i + 10]
                    table.batch_delete(batch)
                    airtable_deleted += len(batch)
                    time.sleep(0.2)  # Rate limiting
                
                if records_to_delete:
                    print(f"   ✓ Deleted {len(records_to_delete)} records from {table_name}")
                
            except Exception as e:
                print(f"   ⚠ Failed to clean {table_name}: {str(e)}")
                continue
        
        print(f"   ✓ Deleted {airtable_deleted} total records from Airtable")
        
        # === STEP 4: Delete records older than 7 days from Supabase ===
        print(f"\n4. Deleting Supabase records older than {older_than_7_days}...")
        
        supabase_deleted = 0
        
        # Delete from raw_scraped_profiles
        try:
            result = supabase.table('raw_scraped_profiles')\
                .delete()\
                .lt('scraped_at', f'{older_than_7_days}T00:00:00')\
                .execute()
            deleted_count = len(result.data) if result.data else 0
            supabase_deleted += deleted_count
            print(f"   ✓ Deleted {deleted_count} records from raw_scraped_profiles")
        except Exception as e:
            print(f"   ⚠ Failed to delete from raw_scraped_profiles: {str(e)}")
        
        # Delete from campaigns
        try:
            result = supabase.table('campaigns')\
                .delete()\
                .lt('campaign_date', str(older_than_7_days))\
                .execute()
            deleted_count = len(result.data) if result.data else 0
            supabase_deleted += deleted_count
            print(f"   ✓ Deleted {deleted_count} records from campaigns")
        except Exception as e:
            print(f"   ⚠ Failed to delete from campaigns: {str(e)}")
        
        # Delete from daily_assignments
        try:
            result = supabase.table('daily_assignments')\
                .delete()\
                .lt('assigned_at', f'{older_than_7_days}T00:00:00')\
                .execute()
            deleted_count = len(result.data) if result.data else 0
            supabase_deleted += deleted_count
            print(f"   ✓ Deleted {deleted_count} records from daily_assignments")
        except Exception as e:
            print(f"   ⚠ Failed to delete from daily_assignments: {str(e)}")
        
        print(f"   ✓ Deleted {supabase_deleted} total records from Supabase")
        
        # === Summary ===
        print("\n" + "=" * 60)
        print("Cleanup Summary")
        print("=" * 60)
        print(f"Unfollow marked (Supabase): {unfollow_marked}")
        print(f"Airtable deleted: {airtable_deleted}")
        print(f"Supabase deleted: {supabase_deleted}")
        print("=" * 60)
        
        return jsonify({
            'success': True,
            'unfollow_marked': unfollow_marked,
            'airtable_deleted': airtable_deleted,
            'supabase_deleted': supabase_deleted
        })
        
    except Exception as e:
        print(f"Error processing cleanup request: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
"""


@app.route('/api/sync-airtable-statuses', methods=['POST'])
def sync_airtable_statuses():
    """
    Sync manual VA status updates from Airtable to Supabase.
    
    This endpoint:
    1. Fetches all records from all 80 VA tables in Airtable
    2. Matches records by Instagram 'id' field
    3. Updates Supabase where status differs
    4. Idempotent operation - safe to run multiple times
    
    Returns:
    {
        "success": true,
        "synced_count": 150,
        "errors": []
    }
    """
    try:
        # Extract base_id with fallback to default
        base_id = get_base_id_from_request()
        
        if not validate_base_id(base_id):
            return jsonify({
                'success': False,
                'error': f'Invalid base_id format: {base_id}'
            }), 400
        
        # Initialize clients
        supabase = get_supabase_client()
        airtable_token = os.getenv('AIRTABLE_ACCESS_TOKEN')
        airtable = get_airtable_client()
        
        # Get number of VA tables dynamically
        num_va_tables = get_va_table_count(base_id, supabase, airtable_token)
        
        # Get Airtable base ID - use base_id parameter as the Airtable base ID
        airtable_base_id = base_id
        
        print("Starting Airtable → Supabase status sync...")
        print(f"Base ID: {airtable_base_id}, VA tables: {num_va_tables}")
        
        synced_count = 0
        errors = []
        
        # Process each VA table
        for table_num in range(1, num_va_tables + 1):
            table_name = f"Daily_Outreach_Table_{table_num:02d}"
            
            try:
                table = airtable.table(airtable_base_id, table_name)
                
                # Fetch all records from Airtable
                all_records = table.all()
                
                # Process in batches
                for i in range(0, len(all_records), 10):
                    batch = all_records[i:i + 10]
                    
                    for record in batch:
                        fields = record['fields']
                        instagram_id = fields.get('id')
                        airtable_status = fields.get('progress_status')  # singleSelect returns string
                        
                        if not instagram_id or not airtable_status:
                            continue
                        
                        # Find matching record in Supabase
                        supabase_record = supabase.table('daily_assignments')\
                            .select('assignment_id, status')\
                            .eq('id', instagram_id)\
                            .eq('va_table_number', table_num)\
                            .execute()
                        
                        if supabase_record.data and len(supabase_record.data) > 0:
                            current_status = supabase_record.data[0]['status']
                            
                            # Update if status differs
                            if current_status != airtable_status:
                                supabase.table('daily_assignments')\
                                    .update({'status': airtable_status})\
                                    .eq('assignment_id', supabase_record.data[0]['assignment_id'])\
                                    .execute()
                                synced_count += 1
                                print(f"   ✓ Synced {instagram_id}: {current_status} → {airtable_status}")
                    
                    time.sleep(0.2)  # Rate limiting
                
                print(f"   ✓ Processed {table_name}")
                
            except Exception as e:
                error_msg = f"Failed to sync {table_name}: {str(e)}"
                print(f"   ⚠ {error_msg}")
                errors.append(error_msg)
                continue
        
        print(f"\n✓ Sync complete! Synced {synced_count} records")
        
        return jsonify({
            'success': True,
            'synced_count': synced_count,
            'errors': errors
        })
        
    except Exception as e:
        print(f"Error syncing Airtable statuses: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mark-unfollow-due', methods=['POST'])
def mark_unfollow_due():
    """
    Mark followed records 7+ days old as 'unfollow'.
    
    This endpoint:
    1. Queries daily_assignments WHERE status='followed' AND assigned_at <= NOW() - INTERVAL '7 days'
    2. Updates status to 'unfollow' in Supabase
    3. Updates matching records in Airtable
    4. Batch processes with retry logic
    
    Returns:
    {
        "success": true,
        "marked_count": 50,
        "errors": []
    }
    """
    try:
        # Extract base_id with fallback to default
        base_id = get_base_id_from_request()
        
        if not validate_base_id(base_id):
            return jsonify({
                'success': False,
                'error': f'Invalid base_id format: {base_id}'
            }), 400
        
        # Initialize clients
        supabase = get_supabase_client()
        airtable_token = os.getenv('AIRTABLE_ACCESS_TOKEN')
        airtable = get_airtable_client()
        
        # Get Airtable base ID - use base_id parameter
        airtable_base_id = base_id
        
        print("Starting 7-day unfollow marking...")
        print(f"Base ID: {airtable_base_id}")
        
        # Calculate 7 days ago
        seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        
        print(f"Marking records with assigned_at <= {seven_days_ago}")
        
        # Find records that are 7+ days old and still 'followed'
        followed_records = supabase.table('daily_assignments')\
            .select('assignment_id, va_table_number, id, username')\
            .eq('status', 'followed')\
            .lte('assigned_at', seven_days_ago)\
            .execute()
        
        marked_count = 0
        errors = []
        
        if not followed_records.data:
            print("No records to mark for unfollow")
            return jsonify({
                'success': True,
                'marked_count': 0,
                'errors': []
            })
        
        print(f"Found {len(followed_records.data)} records to mark as 'unfollow'")
        
        # Update Supabase first
        for record in followed_records.data:
            try:
                supabase.table('daily_assignments')\
                    .update({'status': 'unfollow'})\
                    .eq('assignment_id', record['assignment_id'])\
                    .execute()
                marked_count += 1
            except Exception as e:
                error_msg = f"Failed to update Supabase record {record['assignment_id']}: {str(e)}"
                print(f"   ⚠ {error_msg}")
                errors.append(error_msg)
        
        print(f"   ✓ Updated {marked_count} records in Supabase")
        
        # Group by VA table for Airtable updates
        by_table = {}
        for record in followed_records.data:
            table_num = record['va_table_number']
            if table_num > 0:  # Only process assigned records
                if table_num not in by_table:
                    by_table[table_num] = []
                by_table[table_num].append(record)
        
        # Update Airtable
        airtable_updated = 0
        for table_num, assignments in by_table.items():
            table_name = f"Daily_Outreach_Table_{table_num:02d}"
            
            try:
                table = airtable.table(airtable_base_id, table_name)
                
                # Fetch all records from this table
                all_records = table.all()
                
                # Update matching records
                for assignment in assignments:
                    # Find the record by id field
                    for airtable_record in all_records:
                        if airtable_record['fields'].get('id') == assignment['id']:
                            # Update progress_status to "unfollow" (string format for singleSelect)
                            table.update(airtable_record['id'], {'progress_status': 'unfollow'})
                            airtable_updated += 1
                            break
                
                time.sleep(0.2)  # Rate limiting
                print(f"   ✓ Updated {table_name}")
                
            except Exception as e:
                error_msg = f"Failed to update {table_name}: {str(e)}"
                print(f"   ⚠ {error_msg}")
                errors.append(error_msg)
                continue
        
        print(f"   ✓ Updated {airtable_updated} records in Airtable")
        
        return jsonify({
            'success': True,
            'marked_count': marked_count,
            'airtable_updated': airtable_updated,
            'errors': errors
        })
        
    except Exception as e:
        print(f"Error marking unfollow due: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/delete-completed-after-delay', methods=['POST'])
def delete_completed_after_delay():
    """
    Delete completed records after 24 hours.
    
    This endpoint:
    1. Queries WHERE status='completed' AND updated_at <= NOW() - INTERVAL '24 hours'
    2. Deletes from Airtable first (batch delete)
    3. Deletes from Supabase daily_assignments
    4. Never touches global_usernames or source_profiles
    
    Returns:
    {
        "success": true,
        "deleted_count": 30,
        "errors": []
    }
    """
    try:
        # Extract base_id with fallback to default
        base_id = get_base_id_from_request()
        
        if not validate_base_id(base_id):
            return jsonify({
                'success': False,
                'error': f'Invalid base_id format: {base_id}'
            }), 400
        
        # Initialize clients
        supabase = get_supabase_client()
        airtable_token = os.getenv('AIRTABLE_ACCESS_TOKEN')
        airtable = get_airtable_client()
        
        # Get Airtable base ID - use base_id parameter
        airtable_base_id = base_id
        
        print("Starting 24-hour completed record deletion...")
        print(f"Base ID: {airtable_base_id}")
        
        # Calculate 24 hours ago
        twenty_four_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        
        print(f"Deleting records with status='completed' AND updated_at <= {twenty_four_hours_ago}")
        
        # Find completed records older than 24 hours
        completed_records = supabase.table('daily_assignments')\
            .select('assignment_id, va_table_number, id, username')\
            .eq('status', 'completed')\
            .lte('updated_at', twenty_four_hours_ago)\
            .execute()
        
        if not completed_records.data:
            print("No completed records to delete")
            return jsonify({
                'success': True,
                'deleted_count': 0,
                'errors': []
            })
        
        print(f"Found {len(completed_records.data)} completed records to delete")
        
        errors = []
        
        # Group by VA table for Airtable deletion
        by_table = {}
        for record in completed_records.data:
            table_num = record['va_table_number']
            if table_num > 0:  # Only process assigned records
                if table_num not in by_table:
                    by_table[table_num] = []
                by_table[table_num].append(record)
        
        # Delete from Airtable first
        airtable_deleted = 0
        for table_num, assignments in by_table.items():
            table_name = f"Daily_Outreach_Table_{table_num:02d}"
            
            try:
                table = airtable.table(airtable_base_id, table_name)
                
                # Fetch all records from this table
                all_records = table.all()
                
                # Find matching records to delete
                records_to_delete = []
                for assignment in assignments:
                    for airtable_record in all_records:
                        if airtable_record['fields'].get('id') == assignment['id']:
                            records_to_delete.append(airtable_record['id'])
                            break
                
                # Delete in batches of 10
                for i in range(0, len(records_to_delete), 10):
                    batch = records_to_delete[i:i + 10]
                    table.batch_delete(batch)
                    airtable_deleted += len(batch)
                    time.sleep(0.2)  # Rate limiting
                
                if records_to_delete:
                    print(f"   ✓ Deleted {len(records_to_delete)} records from {table_name}")
                
            except Exception as e:
                error_msg = f"Failed to delete from {table_name}: {str(e)}"
                print(f"   ⚠ {error_msg}")
                errors.append(error_msg)
                continue
        
        print(f"   ✓ Deleted {airtable_deleted} records from Airtable")
        
        # Delete from Supabase daily_assignments
        supabase_deleted = 0
        for record in completed_records.data:
            try:
                supabase.table('daily_assignments')\
                    .delete()\
                    .eq('assignment_id', record['assignment_id'])\
                    .execute()
                supabase_deleted += 1
            except Exception as e:
                error_msg = f"Failed to delete Supabase record {record['assignment_id']}: {str(e)}"
                print(f"   ⚠ {error_msg}")
                errors.append(error_msg)
        
        print(f"   ✓ Deleted {supabase_deleted} records from Supabase")
        
        return jsonify({
            'success': True,
            'deleted_count': supabase_deleted,
            'airtable_deleted': airtable_deleted,
            'errors': errors
        })
        
    except Exception as e:
        print(f"Error deleting completed records: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/run-daily', methods=['POST'])
def run_daily():
    """
    Orchestration endpoint - runs the entire daily pipeline with one API call.
    
    Pipeline execution (sequential):
    1. Daily Selection - Create campaign and select 14,400 profiles
    2. Distribution - Shuffle and assign profiles to VA tables
    3. Airtable Sync - Push assignments to Airtable
    4. Cleanup - Handle 7-day lifecycle maintenance
    
    Note: Assumes /api/ingest has already been called by the scraper
    
    Returns:
    {
        "success": true,
        "campaign_id": "uuid",
        "selected": 14400,
        "distributed": true,
        "airtable_synced": true,
        "cleanup_done": true,
        "execution_time": 125.5
    }
    """
    try:
        import time as time_module
        start_time = time_module.time()
        
        print("=" * 70)
        print("DAILY PIPELINE ORCHESTRATION")
        print("=" * 70)
        print()
        
        # Extract base_id
        base_id = get_base_id_from_request()
        
        if not validate_base_id(base_id):
            return jsonify({
                'success': False,
                'error': f'Invalid base_id format: {base_id}'
            }), 400
        
        # Initialize Supabase client
        supabase = get_supabase_client()
        airtable_token = os.getenv('AIRTABLE_ACCESS_TOKEN')
        
        # Get number of VA tables dynamically
        num_va_tables = get_va_table_count(base_id, supabase, airtable_token)
        
        # Get configuration - profiles_per_table should come from request body
        # This endpoint is typically for testing/manual runs, so we use DEFAULT if not provided
        data = request.get_json() or {}
        profiles_per_table = data.get('profiles_per_table', DEFAULT_PROFILES_PER_TABLE)
        
        if profiles_per_table != DEFAULT_PROFILES_PER_TABLE:
            print(f"✓ Using profiles_per_table from request: {profiles_per_table}")
        else:
            print(f"⚠️ WARNING: Using default profiles_per_table: {profiles_per_table}")
        
        # Calculate target count: num_va_tables * profiles_per_table
        target_count = num_va_tables * profiles_per_table
        campaign_date_obj = date.today()
        
        print(f"Configuration: {num_va_tables} VA tables (dynamic) × {profiles_per_table} profiles = {target_count} total")
        
        # ===== STEP 1: DAILY SELECTION =====
        print("STEP 1: Daily Selection")
        print("-" * 70)
        
        try:
            # Create campaign
            campaign_id = str(uuid.uuid4())
            
            supabase.table('campaigns').insert({
                'campaign_id': campaign_id,
                'campaign_date': campaign_date_obj.isoformat(),
                'total_assigned': 0,
                'base_id': base_id,
                'airtable_base_id': base_id,  # Store the Airtable base ID
                'status': False,
                'created_at': datetime.now(timezone.utc).isoformat()
            }).execute()
            
            print(f"✓ Created campaign: {campaign_id}")
            
            # Select unused profiles
            available_profiles = supabase.table('global_usernames')\
                .select('id, username, full_name')\
                .eq('used', False)\
                .eq('base_id', base_id)\
                .limit(target_count)\
                .execute()
            
            if not available_profiles.data:
                return jsonify({
                    'success': False,
                    'error': 'No unused profiles available in global_usernames',
                    'step_failed': 'daily_selection'
                }), 400
            
            selected_profiles = available_profiles.data
            total_selected = len(selected_profiles)
            
            print(f"✓ Selected {total_selected} unused profiles")
            
            # Mark as used
            profile_ids = [profile['id'] for profile in selected_profiles]
            for profile_id in profile_ids:
                supabase.table('global_usernames')\
                    .update({
                        'used': True,
                        'used_at': datetime.now(timezone.utc).isoformat()
                    })\
                    .eq('id', profile_id)\
                    .eq('base_id', base_id)\
                    .execute()
            
            print(f"✓ Marked {total_selected} profiles as used")
            
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
                    'base_id': base_id,
                    'status': 'pending',
                    'assigned_at': datetime.now(timezone.utc).isoformat()
                })
            
            supabase.table('daily_assignments').insert(assignments).execute()
            
            # Update campaign
            supabase.table('campaigns')\
                .update({'total_assigned': total_selected})\
                .eq('campaign_id', campaign_id)\
                .execute()
            
            print(f"✓ Created {total_selected} placeholder assignments")
            print()
            
        except Exception as e:
            print(f"✗ Daily Selection failed: {str(e)}")
            return jsonify({
                'success': False,
                'error': f'Daily Selection failed: {str(e)}',
                'step_failed': 'daily_selection'
            }), 500
        
        # ===== STEP 2: DISTRIBUTION =====
        print("STEP 2: Distribution")
        print("-" * 70)
        
        try:
            # num_va_tables already calculated dynamically at the top
            # profiles_per_table already defined at the top from request body
            
            # Fetch unassigned profiles
            unassigned = supabase.table('daily_assignments')\
                .select('assignment_id, id, username, full_name')\
                .eq('campaign_id', campaign_id)\
                .eq('base_id', base_id)\
                .eq('va_table_number', 0)\
                .execute()
            
            profiles = unassigned.data
            total_profiles = len(profiles)
            
            print(f"✓ Found {total_profiles} unassigned profiles")
            
            # Shuffle randomly
            random.shuffle(profiles)
            print(f"✓ Shuffled profiles randomly")
            
            # Assign to VA tables
            distributed_count = 0
            current_table = 1
            current_position = 1
            
            for profile in profiles:
                supabase.table('daily_assignments')\
                    .update({
                        'va_table_number': current_table,
                        'position': current_position
                    })\
                    .eq('assignment_id', profile['assignment_id'])\
                    .execute()
                
                distributed_count += 1
                current_position += 1
                
                if current_position > profiles_per_table:
                    current_position = 1
                    current_table += 1
                    
                    if current_table > num_va_tables:
                        break
            
            tables_used = current_table if current_position == 1 else current_table
            
            print(f"✓ Distributed {distributed_count} profiles to {tables_used} VA tables")
            print()
            
        except Exception as e:
            print(f"✗ Distribution failed: {str(e)}")
            return jsonify({
                'success': False,
                'error': f'Distribution failed: {str(e)}',
                'step_failed': 'distribution',
                'campaign_id': campaign_id
            }), 500
        
        # ===== STEP 3: AIRTABLE SYNC =====
        print("STEP 3: Airtable Sync")
        print("-" * 70)
        
        try:
            airtable_base_id = os.getenv('AIRTABLE_BASE_ID')
            
            if not airtable_base_id:
                print("⚠ Skipping Airtable sync - AIRTABLE_BASE_ID not set")
                airtable_synced = False
            else:
                airtable = get_airtable_client()
                campaign_date = campaign_date_obj.isoformat()
                
                # Fetch assigned profiles
                assigned = supabase.table('daily_assignments')\
                    .select('va_table_number, position, id, username, full_name, status')\
                    .eq('campaign_id', campaign_id)\
                    .gt('va_table_number', 0)\
                    .order('va_table_number')\
                    .order('position')\
                    .execute()
                
                profiles = assigned.data
                
                # Group by VA table
                profiles_by_table = {}
                for profile in profiles:
                    table_num = profile['va_table_number']
                    if table_num not in profiles_by_table:
                        profiles_by_table[table_num] = []
                    profiles_by_table[table_num].append(profile)
                
                print(f"✓ Grouped {len(profiles)} profiles into {len(profiles_by_table)} tables")
                
                # Sync to Airtable
                tables_synced = 0
                records_synced = 0
                batch_size = 10
                
                for table_num in sorted(profiles_by_table.keys()):
                    table_name = f"Daily_Outreach_Table_{table_num:02d}"
                    table_profiles = profiles_by_table[table_num]
                    
                    try:
                        table = airtable.table(airtable_base_id, table_name)
                        
                        # Prepare records
                        airtable_records = []
                        for profile in table_profiles:
                            airtable_records.append({
                                'id': profile['id'],
                                'username': profile['username'],
                                'full_name': profile['full_name'],
                                'position': profile['position'],
                                'campaign_date': campaign_date,
                                'progress_status': profile['status']  # singleSelect requires string, defaults to 'pending'
                            })
                        
                        # Batch create
                        for i in range(0, len(airtable_records), batch_size):
                            batch = airtable_records[i:i + batch_size]
                            table.batch_create(batch)
                            time.sleep(0.2)
                        
                        tables_synced += 1
                        records_synced += len(table_profiles)
                        
                    except Exception as e:
                        print(f"  ⚠ Failed to sync {table_name}: {str(e)}")
                        continue
                
                print(f"✓ Synced {records_synced} records to {tables_synced} Airtable tables")
                
                # Update campaign status based on sync results
                campaign_status = True if tables_synced == num_va_tables and records_synced > 0 else False
                supabase.table('campaigns')\
                    .update({'status': campaign_status})\
                    .eq('campaign_id', campaign_id)\
                    .execute()
                status_text = 'success' if campaign_status else 'failed'
                print(f"✓ Updated campaign status to: {status_text} ({campaign_status})")
                
                airtable_synced = True
            
            print()
            
        except Exception as e:
            print(f"✗ Airtable Sync failed: {str(e)}")
            print("  Continuing with cleanup...")
            
            # Mark campaign as failed (False) on exception
            try:
                supabase.table('campaigns')\
                    .update({'status': False})\
                    .eq('campaign_id', campaign_id)\
                    .execute()
                print(f"✓ Updated campaign status to: failed (False) due to error")
            except Exception as status_error:
                print(f"⚠ Could not update campaign status: {str(status_error)}")
            
            airtable_synced = False
        
        # ===== STEP 4: CLEANUP =====
        print("STEP 4: Cleanup (7-day lifecycle)")
        print("-" * 70)
        
        try:
            today = datetime.now(timezone.utc)
            exactly_7_days_ago = (today - timedelta(days=7)).date()
            older_than_7_days = (today - timedelta(days=8)).date()
            
            # Mark for unfollow
            seven_day_old = supabase.table('daily_assignments')\
                .select('assignment_id')\
                .gte('assigned_at', f'{exactly_7_days_ago}T00:00:00')\
                .lt('assigned_at', f'{exactly_7_days_ago}T23:59:59')\
                .eq('status', 'pending')\
                .execute()
            
            unfollow_marked = 0
            if seven_day_old.data:
                for assignment in seven_day_old.data:
                    supabase.table('daily_assignments')\
                        .update({'status': 'to_unfollow'})\
                        .eq('assignment_id', assignment['assignment_id'])\
                        .execute()
                    unfollow_marked += 1
            
            print(f"✓ Marked {unfollow_marked} assignments for unfollow")
            
            # Delete old records
            supabase_deleted = 0
            
            # Delete from raw_scraped_profiles
            result = supabase.table('raw_scraped_profiles')\
                .delete()\
                .lt('scraped_at', f'{older_than_7_days}T00:00:00')\
                .execute()
            supabase_deleted += len(result.data) if result.data else 0
            
            # Delete from campaigns
            result = supabase.table('campaigns')\
                .delete()\
                .lt('campaign_date', str(older_than_7_days))\
                .execute()
            supabase_deleted += len(result.data) if result.data else 0
            
            # Delete from daily_assignments
            result = supabase.table('daily_assignments')\
                .delete()\
                .lt('assigned_at', f'{older_than_7_days}T00:00:00')\
                .execute()
            supabase_deleted += len(result.data) if result.data else 0
            
            print(f"✓ Deleted {supabase_deleted} old records from Supabase")
            print()
            
            cleanup_done = True
            
        except Exception as e:
            print(f"✗ Cleanup failed: {str(e)}")
            print("  Pipeline completed with cleanup error")
            cleanup_done = False
        
        # ===== SUMMARY =====
        execution_time = time_module.time() - start_time
        
        print("=" * 70)
        print("PIPELINE COMPLETED")
        print("=" * 70)
        print(f"Campaign ID: {campaign_id}")
        print(f"Selected: {total_selected} profiles")
        print(f"Distributed: {distributed_count} profiles")
        print(f"Airtable Synced: {'Yes' if airtable_synced else 'No'}")
        print(f"Cleanup Done: {'Yes' if cleanup_done else 'No'}")
        print(f"Execution Time: {execution_time:.2f} seconds")
        print("=" * 70)
        
        return jsonify({
            'success': True,
            'campaign_id': campaign_id,
            'selected': total_selected,
            'distributed': True,
            'airtable_synced': airtable_synced,
            'cleanup_done': cleanup_done,
            'execution_time': round(execution_time, 2)
        })
        
    except Exception as e:
        print(f"Pipeline error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e),
            'step_failed': 'unknown'
        }), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'service': 'Instagram Scraper API (Production)',
        'version': os.getenv('APP_VERSION', '1.0.0'),
        'async_enabled': True
    })



# ===================================================================
# AIRTABLE BASE CREATION
# ===================================================================

@app.route('/api/airtable/create-base', methods=['POST'])
@limiter.limit("5 per hour")  # Strict limit for base creation
def create_airtable_base_endpoint():
    """
    Create a new Airtable base with VA tables for a scraping job.
    
    IMPORTANT: You must create the base manually in Airtable first
    and provide its base_id or link. This endpoint will populate it with tables.
    
    Request Body:
    {
        // EITHER provide base_id OR airtable_link
        "base_id": "appXYZ123ABC",                                    // Option 1: Direct base ID
        "airtable_link": "https://airtable.com/app1ovtH.../tbl.../",  // Option 2: Airtable URL
        
        "num_vas": 80,               // Optional: Number of VA tables (default: 80)
        "base_name": "Client Name"   // Optional: Display name for logging
    }
    
    Returns:
    {
        "success": true,
        "base_id": "appXYZ123ABC",
        "base_name": "Client Name",
        "tables_created": 80,
        "tables_failed": 0,
        "verification": {...}
    }
    """
    try:
        from utils.airtable_creator import extract_base_id_from_url, validate_base_id
        
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'Request body is required'
            }), 400
        
        # Accept either base_id or airtable_link
        base_id_or_url = data.get('base_id') or data.get('airtable_link')
        
        if not base_id_or_url:
            return jsonify({
                'success': False,
                'error': 'Either "base_id" or "airtable_link" is required'
            }), 400
        
        # Extract base_id from URL if needed
        base_id = extract_base_id_from_url(base_id_or_url)
        
        if not base_id:
            return jsonify({
                'success': False,
                'error': f'Could not extract base ID from: {base_id_or_url}'
            }), 400
        
        # Validate base_id format
        if not validate_base_id(base_id):
            return jsonify({
                'success': False,
                'error': f'Invalid base_id format: {base_id}. Should start with "app" followed by alphanumeric characters'
            }), 400
        
        # Optional parameters
        num_vas = data.get('num_vas', 80)
        base_name = data.get('base_name')
        
        # Validate num_vas
        if not isinstance(num_vas, int) or num_vas < 1 or num_vas > 200:
            return jsonify({
                'success': False,
                'error': 'num_vas must be an integer between 1 and 200'
            }), 400
        
        # Get Airtable token
        airtable_token = os.getenv('AIRTABLE_ACCESS_TOKEN')
        if not airtable_token:
            return jsonify({
                'success': False,
                'error': 'AIRTABLE_ACCESS_TOKEN not configured on server'
            }), 500
        
        logger.info(f"Creating Airtable base: {base_id} with {num_vas} VA tables")
        
        # Check if this base_id already exists in scraping_jobs
        try:
            supabase = get_supabase_client()
            existing_jobs = supabase.table('scraping_jobs')\
                .select('job_id, influencer_name, platform, airtable_base_id')\
                .eq('airtable_base_id', base_id)\
                .execute()
            
            if existing_jobs.data and len(existing_jobs.data) > 0:
                job = existing_jobs.data[0]
                return jsonify({
                    'success': False,
                    'error': 'duplicate_base_id',
                    'message': f'This Airtable base is already associated with an existing campaign: {job.get("influencer_name", "Unknown")} ({job.get("platform", "Unknown")})',
                    'existing_job': {
                        'job_id': job.get('job_id'),
                        'influencer_name': job.get('influencer_name'),
                        'platform': job.get('platform')
                    }
                }), 409  # 409 Conflict
        except Exception as check_error:
            logger.warning(f"Error checking for duplicate base_id: {str(check_error)}")
            # Continue with creation if check fails
        
        # Create the base tables
        result = create_airtable_base(
            base_id=base_id,
            num_vas=num_vas,
            airtable_token=airtable_token,
            base_name=base_name
        )
        
        # If tables were successfully created, save to Supabase
        if result['success'] and result['setup_results']['tables_created'] > 0:
            try:
                supabase = get_supabase_client()
                
                # Create a simple record noting the Airtable base creation
                # Store base_id in a way that's compatible with existing schema
                logger.info(f"✓ Airtable base {base_id} created with {result['setup_results']['tables_created']} tables")
                logger.info(f"Base details: {base_name or base_id}, {num_vas} VAs")
                
                # Optionally store in environment or config for later use
                # The base_id should be used when syncing campaigns
                
            except Exception as supabase_error:
                logger.warning(f"Error during post-creation processing: {str(supabase_error)}")
                # Don't fail the entire operation
        
        # Prepare response
        response = {
            'success': result['success'],
            'base_id': result['base_id'],
            'base_name': result['base_name'],
            'tables_created': result['setup_results']['tables_created'],
            'tables_skipped': result['setup_results'].get('tables_skipped', 0),
            'tables_failed': result['setup_results']['tables_failed'],
            'total_tables': result['setup_results']['total_tables'],
            'message': result.get('message', f'Successfully created {result["setup_results"]["tables_created"]} tables in Airtable base {base_id}')
        }
        
        # Add table IDs if available
        if 'table_ids' in result:
            response['table_ids'] = result['table_ids']
        
        # Add failed tables if any
        if result['setup_results']['failed_tables']:
            response['failed_tables'] = result['setup_results']['failed_tables']
        
        # Add verification results if present
        if 'verification' in result:
            response['verification'] = result['verification']
        
        status_code = 200 if result['success'] else 500
        return jsonify(response), status_code
        
    except Exception as e:
        logger.error(f"Error creating Airtable base: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/airtable/verify-base', methods=['POST'])
@limiter.limit("20 per hour")
def verify_airtable_base_endpoint():
    """
    Verify that an Airtable base has the correct structure.
    
    Request Body:
    {
        // EITHER provide base_id OR airtable_link
        "base_id": "appXYZ123ABC",                                    // Option 1: Direct base ID
        "airtable_link": "https://airtable.com/app1ovtH.../tbl.../",  // Option 2: Airtable URL
        
        "num_vas": 80                // Optional: Expected number of VA tables (default: 80)
    }
    
    Returns:
    {
        "valid": true,
        "base_id": "appXYZ123ABC",
        "tables_found": 80,
        "tables_expected": 80,
        "missing_tables": [],
        "extra_tables": []
    }
    """
    try:
        from utils.airtable_creator import extract_base_id_from_url, validate_base_id
        
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'Request body is required'
            }), 400
        
        # Accept either base_id or airtable_link
        base_id_or_url = data.get('base_id') or data.get('airtable_link')
        
        if not base_id_or_url:
            return jsonify({
                'success': False,
                'error': 'Either "base_id" or "airtable_link" is required'
            }), 400
        
        # Extract base_id from URL if needed
        base_id = extract_base_id_from_url(base_id_or_url)
        
        if not base_id:
            return jsonify({
                'success': False,
                'error': f'Could not extract base ID from: {base_id_or_url}'
            }), 400
        
        # Validate base_id format
        if not validate_base_id(base_id):
            return jsonify({
                'success': False,
                'error': f'Invalid base_id format: {base_id}'
            }), 400
        
        # Optional parameters
        num_vas = data.get('num_vas', 80)
        
        # Get Airtable token
        airtable_token = os.getenv('AIRTABLE_ACCESS_TOKEN')
        if not airtable_token:
            return jsonify({
                'success': False,
                'error': 'AIRTABLE_ACCESS_TOKEN not configured on server'
            }), 500
        
        logger.info(f"Verifying Airtable base: {base_id}")
        
        # Verify the base
        creator = AirtableCreator(airtable_token)
        result = creator.verify_base_structure(base_id, num_vas)
        
        # Add base_id to response for reference
        result['base_id'] = base_id
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error verifying Airtable base: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/healthz', methods=['GET'])
@limiter.exempt  # Exempt health checks from rate limiting
def healthz():
    """Simple health check endpoint for Electron process management."""
    return 'ok', 200


# ===================================================================
# REGISTER ASYNC ENDPOINTS
# ===================================================================
try:
    from api_async import register_async_endpoints
    register_async_endpoints(app, get_supabase_client, limiter)  # ADDED: Pass limiter for rate limiting
    logger.info("✅ Async endpoints registered successfully")
except ImportError as e:
    logger.warning(f"⚠️ Could not import async endpoints: {e}")
    logger.warning("Running in legacy synchronous mode")


# ===================================================================
# APPLICATION ENTRY POINT
# ===================================================================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    debug = os.getenv('FLASK_ENV') != 'production'
    
    logger.info("=" * 60)
    logger.info("Instagram Scraper API Starting...")
    logger.info(f"Port: {port}")
    logger.info(f"Environment: {os.getenv('FLASK_ENV', 'development')}")
    logger.info(f"Debug mode: {debug}")
    logger.info(f"Async tasks: {'Enabled' if 'api_async' in dir() else 'Disabled'}")
    logger.info("=" * 60)
    
    app.run(host='0.0.0.0', port=port, debug=debug)