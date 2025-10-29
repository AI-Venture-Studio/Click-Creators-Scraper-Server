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
        # TikTok actor expects startUrls with full profile URLs
        # Convert usernames to TikTok profile URLs
        tiktok_urls = []
        for username in accounts:
            # Add @ prefix if not present and convert to URL
            clean_username = username.strip()
            if not clean_username.startswith('@'):
                clean_username = f'@{clean_username}'
            # Create full TikTok URL
            profile_url = f'https://www.tiktok.com/{clean_username}'
            tiktok_urls.append({"url": profile_url})
        
        run_input = {
            "startUrls": tiktok_urls,
            "resultsPerPage": max_count,
        }
        logger.info(f"TikTok URLs to scrape: {[u['url'] for u in tiktok_urls]}")
    elif platform.lower() == 'threads':
        # Threads actor - adjust as needed based on actual actor
        run_input = {
            "usernames": accounts,
            "max_count": max_count,
        }
    elif platform.lower() == 'x':
        # X/Twitter actor - adjust as needed based on actual actor
        run_input = {
            "usernames": accounts,
            "max_count": max_count,
        }
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
        columns_to_drop = ['avatar', 'coverImage', 'region', 'language', 'hasEmail', 'hasPhone', 'verified']
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
            # TikTok uses: nickname, followers, following, videos
            follower_data = {
                'username': row.get('username', ''),
                'full_name': row.get('nickname', ''),  # TikTok uses 'nickname'
                'follower_count': row.get('followers', 0),  # TikTok uses 'followers'
                'following_count': row.get('following', 0),  # TikTok uses 'following'
                'posts_count': row.get('videos', 0),  # TikTok uses 'videos'
                'id': str(row.get('id', row.get('username', '')))  # Ensure ID is string
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
            # X/Twitter field mapping (adjust as needed based on actual actor response)
            follower_data = {
                'username': row.get('username', ''),
                'full_name': row.get('name', ''),  # X uses 'name'
                'follower_count': row.get('followers_count', 0),
                'following_count': row.get('following_count', 0),
                'posts_count': row.get('tweets_count', 0),
                'id': row.get('id', row.get('username', ''))
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

