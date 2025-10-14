"""
Instagram scraping utilities using Apify.
"""
import os
import logging
from typing import Dict, List
import pandas as pd
from apify_client import ApifyClient

logger = logging.getLogger(__name__)


def scrape_followers(accounts: List[str], max_count: int = 5) -> Dict[str, Dict]:
    """
    Scrape Instagram followers from specified accounts using Apify.
    
    Args:
        accounts: A list of Instagram account usernames to scrape followers from.
        max_count: Maximum followers to scrape per account (default: 5).
        
    Returns:
        A dictionary mapping each account to their extracted followers data.
        Each follower entry contains username, full_name, follower_count, following_count, posts_count.
        
    Raises:
        ValueError: If required environment variables are missing.
        Exception: If Apify scraping fails.
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
    
    try:
        run = client.actor(actor_key).call(run_input=run_input)
        
        # Fetch Actor results and store in a list
        data = []
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            data.append(item)
        
        logger.info(f"Scraped {len(data)} total follower profiles")
        
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
                'id': row.get('id', row.get('username', ''))
            }
            # Use username as key for each follower
            followers_dict[row.get('username', '')] = follower_data
        
        logger.info(f"Processed {len(followers_dict)} unique followers")
        return followers_dict
        
    except Exception as e:
        logger.error(f"Apify scraping failed: {str(e)}")
        raise Exception(f"Failed to scrape followers: {str(e)}")
