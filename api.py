"""
Instagram Follower Scraper API

A Flask API that provides functionality to scrape Instagram followers from specified accounts,
detect their gender, filter them based on gender preferences, and persist to Supabase.
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
from dotenv import load_dotenv
from apify_client import ApifyClient
import pandas as pd
import gender_guesser.detector as gender
import re
from typing import Optional, List, Dict, Any
from supabase import create_client, Client
from datetime import datetime

# Load environment variables from .env file
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for frontend communication


# Initialize Supabase client
def get_supabase_client() -> Client:
    """
    Initialize and return Supabase client using service role key.
    
    Returns:
        Supabase client instance
    """
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    
    if not supabase_url or not supabase_key:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables are required.")
    
    return create_client(supabase_url, supabase_key)


def scrape_followers(accounts: list) -> dict:
    """
    Handles API requests and Instagram scraping logic.
    
    Args:
        accounts: A list of Instagram account usernames to scrape followers from.
        
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
        "max_count": 5,  # Maximum followers to scrape per account
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


def process_accounts(accounts: list, target_gender: str = "male") -> dict:
    """
    Orchestrates the entire workflow.
    
    Args:
        accounts: List of Instagram usernames to scrape followers from.
        target_gender: Target gender to filter for ("male" or "female").
        
    Returns:
        Dictionary with filtered followers data and summary statistics.
    """
    print(f"Starting Instagram follower analysis for accounts: {accounts}")
    print(f"Target gender: {target_gender}")
    
    # Step 1: Scrape followers from specified accounts
    print("\n1. Scraping followers...")
    followers = scrape_followers(accounts)
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


@app.route('/api/scrape-followers', methods=['POST'])
def scrape_followers_api():
    """
    API endpoint to scrape Instagram followers.
    
    Expected JSON payload:
    {
        "accounts": ["username1", "username2"],
        "targetGender": "male" (optional, defaults to "male")
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
        
        if not isinstance(accounts, list) or len(accounts) == 0:
            return jsonify({
                'success': False,
                'error': 'Accounts must be a non-empty list'
            }), 400
        
        # Process the accounts
        result = process_accounts(accounts, target_gender)
        
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
        ]
    }
    
    Returns:
    {
        "success": true,
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
                'inserted_raw': 0,
                'added_to_global': 0,
                'skipped_existing': 0
            })
        
        # Initialize Supabase client
        supabase = get_supabase_client()
        
        # Counters for response
        inserted_raw = 0
        added_to_global = 0
        skipped_existing = 0
        
        # Process each profile
        for profile in profiles:
            # Validate required fields
            if 'id' not in profile or 'username' not in profile:
                print(f"Warning: Skipping profile with missing id or username: {profile}")
                continue
            
            profile_id = str(profile['id'])
            username = profile['username']
            full_name = profile.get('full_name', '')
            
            # Step 1: Insert into raw_scraped_profiles
            try:
                supabase.table('raw_scraped_profiles').insert({
                    'id': profile_id,
                    'username': username,
                    'full_name': full_name,
                    'scraped_at': datetime.utcnow().isoformat()
                }).execute()
                inserted_raw += 1
                print(f"✓ Inserted {username} into raw_scraped_profiles")
            except Exception as e:
                print(f"Warning: Failed to insert {username} into raw_scraped_profiles: {str(e)}")
            
            # Step 2: Check if profile exists in global_usernames
            try:
                existing = supabase.table('global_usernames')\
                    .select('id')\
                    .eq('id', profile_id)\
                    .execute()
                
                if existing.data and len(existing.data) > 0:
                    # Profile already exists in global_usernames
                    skipped_existing += 1
                    print(f"○ Skipped {username} (already in global_usernames)")
                else:
                    # Profile doesn't exist, insert it
                    supabase.table('global_usernames').insert({
                        'id': profile_id,
                        'username': username,
                        'full_name': full_name,
                        'used': False,
                        'created_at': datetime.utcnow().isoformat()
                    }).execute()
                    added_to_global += 1
                    print(f"✓ Added {username} to global_usernames")
                    
            except Exception as e:
                print(f"Warning: Failed to process {username} for global_usernames: {str(e)}")
                skipped_existing += 1
        
        return jsonify({
            'success': True,
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


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'service': 'Instagram Scraper API'
    })


if __name__ == '__main__':
    print("Starting Instagram Scraper API on port 5001...")
    app.run(debug=True, host='0.0.0.0', port=5001)