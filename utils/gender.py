"""
Gender detection utilities for Instagram profiles.
"""
import re
import logging
from typing import Dict, List, Optional
import gender_guesser.detector as gender

logger = logging.getLogger(__name__)


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
    # Initialize the gender detector
    detector = gender.Detector(case_sensitive=False)
    
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


def detect_gender(followers: Dict[str, Dict]) -> Dict[str, str]:
    """
    Performs gender detection on the scraped followers.
    
    Args:
        followers: Dictionary of followers with their profile information.
        
    Returns:
        Dictionary mapping each follower username to their detected gender 
        ("male", "female", or "unknown").
    """
    logger.info(f"Detecting gender for {len(followers)} followers")
    
    # Apply gender detection to all followers
    followers_gender = {}
    for username, follower_data in followers.items():
        detected_gender = guess_gender_robust(
            username, 
            follower_data.get('full_name', '')
        )
        followers_gender[username] = detected_gender
    
    # Log gender distribution
    gender_counts = {}
    for gender_val in followers_gender.values():
        gender_counts[gender_val] = gender_counts.get(gender_val, 0) + 1
    
    logger.info(f"Gender distribution: {gender_counts}")
    
    return followers_gender


def filter_by_gender(followers_gender: Dict[str, str], target_gender: str) -> Dict[str, str]:
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
        for username, gender_val in followers_gender.items():
            if gender_val in ["male", "unknown"]:
                filtered_followers[username] = gender_val
                
    elif target_gender.lower() == "female":
        # Include female and unknown gender followers
        for username, gender_val in followers_gender.items():
            if gender_val in ["female", "unknown"]:
                filtered_followers[username] = gender_val
    else:
        # Invalid target_gender, return empty dict
        logger.warning(f"Invalid target_gender '{target_gender}'. Must be 'male' or 'female'.")
        return {}
    
    logger.info(f"Filtered to {len(filtered_followers)} followers for target gender '{target_gender}'")
    
    return filtered_followers
