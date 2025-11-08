"""
Instagram scraping utilities using Apify.
Multi-platform support: Instagram, TikTok, Threads, X
"""
import os
import logging
import time
from typing import Dict, List, Literal
import pandas as pd
from apify_client import ApifyClient

logger = logging.getLogger(__name__)

# Type alias for platform
Platform = Literal['instagram', 'threads', 'tiktok', 'x']


def get_actor_id_for_platform(platform: str = 'instagram') -> str:
    """
    Get the appropriate Apify actor ID for the specified platform.
    
    Args:
        platform: Social media platform (instagram, threads, tiktok, x)
        
    Returns:
        Apify actor ID for the platform
        
    Raises:
        ValueError: If platform is unsupported or actor ID not configured
    """
    # Normalize platform to lowercase
    platform = platform.lower()
    
    # Map platform to environment variable
    platform_env_map = {
        'instagram': 'INSTAGRAM_APIFY_ACTOR_ID',
        'threads': 'THREADS_APIFY_ACTOR_ID',
        'tiktok': 'TIKTOK_APIFY_ACTOR_ID',
        'x': 'X_APIFY_ACTOR_ID'
    }
    
    # Fallback to legacy APIFY_ACTOR_ID for Instagram if specific one not set
    if platform == 'instagram':
        actor_id = os.getenv('INSTAGRAM_APIFY_ACTOR_ID') or os.getenv('APIFY_ACTOR_ID')
    elif platform in platform_env_map:
        actor_id = os.getenv(platform_env_map[platform])
    else:
        # Unknown platform - default to Instagram actor
        logger.warning(f"Unknown platform '{platform}', defaulting to Instagram actor")
        actor_id = os.getenv('INSTAGRAM_APIFY_ACTOR_ID') or os.getenv('APIFY_ACTOR_ID')
    
    if not actor_id:
        raise ValueError(
            f"Apify actor ID not configured for platform '{platform}'. "
            f"Please set {platform_env_map.get(platform, 'APIFY_ACTOR_ID')} environment variable."
        )
    
    logger.info(f"Using Apify actor {actor_id} for platform '{platform}'")
    return actor_id


def scrape_followers(
    accounts: List[str], 
    max_count: int = 5, 
    max_retries: int = 3,
    platform: str = 'instagram'
) -> Dict[str, Dict]:
    """
    Scrape followers from specified social media accounts using Apify with retry logic.
    
    OPTIMIZED FOR 500K+ SCALE:
    - Exponential backoff retry for rate limiting
    - Handles Apify API failures gracefully
    - Automatic retry on network errors
    - Multi-platform support (Instagram, TikTok, Threads, X)
    
    Args:
        accounts: A list of account usernames to scrape followers from.
        max_count: Maximum followers to scrape per account (default: 5).
        max_retries: Maximum number of retry attempts (default: 3).
        platform: Social media platform to scrape from (default: 'instagram').
        
    Returns:
        A dictionary mapping each account to their extracted followers data.
        Each follower entry contains username, full_name, follower_count, following_count, posts_count.
        
    Raises:
        ValueError: If required environment variables are missing.
        Exception: If Apify scraping fails after all retries.
    """
    logger.info(f"Starting {platform} scrape for {len(accounts)} accounts, max {max_count} followers each")
    
    # Initialize the ApifyClient with API token from environment variable
    api_key = os.getenv('APIFY_API_KEY')
    if not api_key:
        raise ValueError("APIFY_API_KEY environment variable is required. Please set it in your .env file or environment.")
    
    client = ApifyClient(api_key)
    
    # Get platform-specific actor ID
    actor_key = get_actor_id_for_platform(platform)
    
    # Prepare the Actor input based on platform
    # Different Apify actors expect different input formats
    if platform.lower() == 'tiktok':
        # TikTok actor expects: {"numFollowers": 100, "usernames": ["username1", "username2"]}
        # Clean usernames: remove @ prefix and any URL parts
        clean_usernames = []
        for username in accounts:
            clean_username = username.strip()
            # Remove @ prefix if present
            if clean_username.startswith('@'):
                clean_username = clean_username[1:]
            # Remove URL prefix if it's a full TikTok URL
            if 'tiktok.com/' in clean_username:
                # Extract username from URL like https://www.tiktok.com/@username
                clean_username = clean_username.split('tiktok.com/')[-1]
                if clean_username.startswith('@'):
                    clean_username = clean_username[1:]
            clean_usernames.append(clean_username)
        
        run_input = {
            "usernames": clean_usernames,
            "numFollowers": max_count,
        }
        logger.info(f"TikTok usernames to scrape: {clean_usernames}")
    elif platform.lower() == 'threads':
        # Threads actor - adjust as needed based on actual actor
        run_input = {
            "usernames": accounts,
            "max_count": max_count,
        }
    elif platform.lower() == 'x':
        # X/Twitter actor - uses specific format with getFollowers/getFollowing
        run_input = {
            "user_names": accounts,  # X actor expects "user_names" not "usernames"
            "getFollowers": True,    # Enable follower scraping
            "getFollowing": True,    # Enable following scraping
            "maxFollowers": max_count,   # Max followers per account
            "maxFollowings": max_count,  # Max following per account
        }
        logger.info(f"X/Twitter scraper input: {run_input}")
    else:
        # Instagram (default)
        run_input = {
            "usernames": accounts,
            "max_count": max_count,
        }

    logger.info(f"Calling Apify actor {actor_key} for platform '{platform}'")
    
    # Retry loop with exponential backoff
    last_error = None
    for attempt in range(max_retries):
        try:
            # Calculate backoff delay (0s, 2s, 8s, 32s...)
            if attempt > 0:
                backoff_delay = 2 ** attempt
                logger.info(f"Retry attempt {attempt + 1}/{max_retries} after {backoff_delay}s delay")
                time.sleep(backoff_delay)
            
            # Call Apify actor
            run = client.actor(actor_key).call(run_input=run_input)
            
            # Fetch Actor results and store in a list
            data = []
            for item in client.dataset(run["defaultDatasetId"]).iterate_items():
                data.append(item)
            
            logger.info(f"Scraped {len(data)} total follower profiles")
            
            # Success! Break retry loop
            break
            
        except Exception as e:
            last_error = e
            error_msg = str(e).lower()
            
            # Check if it's a rate limit error
            if 'rate limit' in error_msg or '429' in error_msg:
                logger.warning(f"Apify rate limit hit (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    continue  # Retry with backoff
            
            # Check if it's a network error
            elif 'connection' in error_msg or 'timeout' in error_msg:
                logger.warning(f"Network error (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    continue  # Retry with backoff
            
            # Unknown error
            else:
                logger.error(f"Apify scraping error (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    continue  # Still retry
            
            # If this was the last attempt, raise the error
            if attempt == max_retries - 1:
                raise Exception(f"Failed to scrape followers after {max_retries} attempts: {last_error}")
    
    # Process the data - OPTIMIZED to reduce memory usage
    # Create pandas DataFrame from the collected data
    followers_df = pd.DataFrame(data)
    
    # Drop unnecessary columns to clean up the data (platform-specific)
    if platform.lower() == 'tiktok':
        columns_to_drop = ['avatar', 'coverImage', 'language', 'hasEmail', 'hasPhone', 'verified']
    else:
        columns_to_drop = ['profile_pic_url', 'latest_story_ts', 'is_verified', 'is_private']
    followers_df = followers_df.drop(columns=columns_to_drop, errors='ignore')
    
    # Convert DataFrame to dictionary format for easier processing
    # Process row by row to minimize memory footprint
    # Normalize field names across different platforms
    followers_dict = {}
    for _, row in followers_df.iterrows():
        # Platform-specific field mapping
        if platform.lower() == 'tiktok':
            # TikTok API can return different field names depending on the actor version
            # Support multiple formats: uniqueId/unique_id/username for username field
            # id field is the primary unique identifier (numeric string)
            unique_id = row.get('uniqueId') or row.get('unique_id') or row.get('username', '')
            follower_data = {
                'id': str(row.get('id', '')),  # Primary unique identifier (numeric string)
                'username': unique_id,  # TikTok username (uniqueId/unique_id/username)
                'full_name': row.get('nickname', ''),  # TikTok display name (used for gender check)
                'follower_count': row.get('followerCount') or row.get('follower_count') or row.get('followers', 0),
                'following_count': row.get('followingCount') or row.get('following_count') or row.get('following', 0),
                'posts_count': row.get('videoCount') or row.get('aweme_count') or row.get('videos', 0),
                'signature': row.get('signature', ''),  # TikTok bio/signature
                'region': row.get('region', ''),  # TikTok region/country code (e.g., 'US', 'PK')
                'sec_uid': row.get('secUid', ''),  # TikTok secure user ID
                'url': row.get('url', ''),  # Profile URL
            }
        elif platform.lower() == 'threads':
            # Threads likely uses similar fields to Instagram (adjust as needed)
            follower_data = {
                'username': row.get('username', ''),
                'full_name': row.get('full_name') or row.get('fullname', ''),
                'follower_count': row.get('follower_count', 0),
                'following_count': row.get('following_count', 0),
                'posts_count': row.get('posts_count', 0),
                'id': row.get('id', row.get('username', ''))
            }
        elif platform.lower() == 'x':
            # X/Twitter field mapping - SIMPLIFIED to essential fields only
            # Only capture: id_str, screen_name, name
            follower_data = {
                'id': str(row.get('id_str', row.get('id', ''))),  # X uses 'id_str' (preferred) or 'id'
                'username': row.get('screen_name', ''),  # X uses 'screen_name' for username
                'full_name': row.get('name', ''),  # X uses 'name' for full name
                # Set default values for compatibility with existing system
                'follower_count': 0,
                'following_count': 0,
                'posts_count': 0,
            }
        else:
            # Instagram (default)
            follower_data = {
                'username': row.get('username', ''),
                'full_name': row.get('full_name') or row.get('fullname', ''),
                'follower_count': row.get('follower_count', 0),
                'following_count': row.get('following_count', 0),
                'posts_count': row.get('posts_count', 0),
                'id': row.get('id', row.get('username', ''))
            }
        
        # Use username as key for each follower
        username = follower_data['username']
        if username:  # Only add if username exists
            followers_dict[username] = follower_data
    
    # Clear DataFrame from memory
    del followers_df
    del data
    
    logger.info(f"Processed {len(followers_dict)} unique followers from {platform}")
    return followers_dict

