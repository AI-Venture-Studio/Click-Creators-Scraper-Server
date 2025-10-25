"""
Instagram scraping utilities using Apify.
"""
import os
import logging
import time
from typing import Dict, List
import pandas as pd
from apify_client import ApifyClient

logger = logging.getLogger(__name__)


def scrape_followers(accounts: List[str], max_count: int = 5, max_retries: int = 3) -> Dict[str, Dict]:
    """
    Scrape Instagram followers from specified accounts using Apify with retry logic.
    
    OPTIMIZED FOR 500K+ SCALE:
    - Exponential backoff retry for rate limiting
    - Handles Apify API failures gracefully
    - Automatic retry on network errors
    
    Args:
        accounts: A list of Instagram account usernames to scrape followers from.
        max_count: Maximum followers to scrape per account (default: 5).
        max_retries: Maximum number of retry attempts (default: 3).
        
    Returns:
        A dictionary mapping each account to their extracted followers data.
        Each follower entry contains username, full_name, follower_count, following_count, posts_count.
        
    Raises:
        ValueError: If required environment variables are missing.
        Exception: If Apify scraping fails after all retries.
    """
    logger.info(f"Starting scrape for {len(accounts)} accounts, max {max_count} followers each")
    
    # Initialize the ApifyClient with API token from environment variable
    api_key = os.getenv('APIFY_API_KEY')
    if not api_key:
        raise ValueError("APIFY_API_KEY environment variable is required. Please set it in your .env file or environment.")
    
    client = ApifyClient(api_key)
    
    # Prepare the Actor input
    run_input = {
        "usernames": accounts,
        "max_count": max_count,
    }
    
    # Run the Actor and wait for it to finish
    actor_key = os.getenv('APIFY_ACTOR_ID')
    if not actor_key:
        raise ValueError("APIFY_ACTOR_ID environment variable is required. Please set it in your .env file or environment.")

    logger.info(f"Calling Apify actor {actor_key}")
    
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
    
    # Drop unnecessary columns to clean up the data
    columns_to_drop = ['profile_pic_url', 'latest_story_ts', 'is_verified', 'is_private']
    followers_df = followers_df.drop(columns=columns_to_drop, errors='ignore')
    
    # Convert DataFrame to dictionary format for easier processing
    # Process row by row to minimize memory footprint
    followers_dict = {}
    for _, row in followers_df.iterrows():
        follower_data = {
            'username': row.get('username', ''),
            'full_name': row.get('full_name') or row.get('fullname', ''),
            'follower_count': row.get('follower_count', 0),
            'following_count': row.get('following_count', 0),
            'posts_count': row.get('posts_count', 0),
            'id': row.get('id', row.get('username', ''))
        }
        # Use username as key for each follower
        followers_dict[row.get('username', '')] = follower_data
    
    # Clear DataFrame from memory
    del followers_df
    del data
    
    logger.info(f"Processed {len(followers_dict)} unique followers")
    return followers_dict

