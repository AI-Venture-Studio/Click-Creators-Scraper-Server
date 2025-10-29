"""
Multi-Tenant Scraping Jobs Backend Helper

This module provides Python helper functions for working with the new
multi-tenant scraping jobs system in the backend.
"""

from typing import List, Dict, Optional, Literal
from datetime import datetime
import os
from supabase import create_client, Client

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Type aliases
Platform = Literal['instagram', 'threads', 'tiktok', 'x']
JobStatus = Literal['active', 'paused', 'archived']

# Legacy placeholder job ID
LEGACY_PLACEHOLDER_JOB_ID = '00000000-0000-0000-0000-000000000001'


class ScrapingJobsManager:
    """Manager for multi-tenant scraping jobs operations"""
    
    @staticmethod
    def create_job(
        influencer_name: str,
        platform: Platform,
        airtable_base_id: str,
        num_vas: Optional[int] = None,
        base_id: Optional[str] = None,
        status: JobStatus = 'active'
    ) -> Optional[Dict]:
        """
        Create a new scraping job
        
        Args:
            influencer_name: Name of the influencer
            platform: Social media platform (instagram, threads, tiktok, x)
            airtable_base_id: Airtable base ID for this job
            num_vas: Number of Virtual Assistants (optional)
            base_id: Multi-tenant base identifier (optional)
            status: Job status (default: active)
            
        Returns:
            Created job data or None if failed
        """
        try:
            job_data = {
                'influencer_name': influencer_name,
                'platform': platform.lower(),  # Normalize to lowercase
                'airtable_base_id': airtable_base_id,
                'num_vas': num_vas,
                'status': status
            }
            
            # Add base_id if provided
            if base_id:
                job_data['base_id'] = base_id
            
            response = supabase.table('scraping_jobs').insert(job_data).execute()
            
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error creating scraping job: {e}")
            return None
    
    @staticmethod
    def get_job(job_id: str) -> Optional[Dict]:
        """Get a scraping job by ID"""
        try:
            response = supabase.table('scraping_jobs')\
                .select('*')\
                .eq('job_id', job_id)\
                .single()\
                .execute()
            
            return response.data
        except Exception as e:
            print(f"Error fetching job: {e}")
            return None
    
    @staticmethod
    def get_all_jobs(status: Optional[JobStatus] = None) -> List[Dict]:
        """
        Get all scraping jobs, optionally filtered by status
        
        Args:
            status: Filter by job status (optional)
            
        Returns:
            List of job dictionaries
        """
        try:
            query = supabase.table('scraping_jobs').select('*')
            
            if status:
                query = query.eq('status', status)
            
            response = query.order('created_at', desc=True).execute()
            return response.data or []
        except Exception as e:
            print(f"Error fetching jobs: {e}")
            return []
    
    @staticmethod
    def get_jobs_by_platform(
        platform: Platform,
        active_only: bool = False
    ) -> List[Dict]:
        """Get jobs for a specific platform"""
        try:
            query = supabase.table('scraping_jobs')\
                .select('*')\
                .eq('platform', platform)
            
            if active_only:
                query = query.eq('status', 'active')
            
            response = query.order('created_at', desc=True).execute()
            return response.data or []
        except Exception as e:
            print(f"Error fetching jobs by platform: {e}")
            return []
    
    @staticmethod
    def update_job_status(job_id: str, status: JobStatus) -> bool:
        """Update job status"""
        try:
            supabase.table('scraping_jobs')\
                .update({'status': status})\
                .eq('job_id', job_id)\
                .execute()
            return True
        except Exception as e:
            print(f"Error updating job status: {e}")
            return False
    
    @staticmethod
    def get_airtable_base_id(job_id: str) -> Optional[str]:
        """
        Get Airtable base ID for a specific job
        
        This is crucial for sending scraped data to the correct Airtable base
        
        Args:
            job_id: The scraping job ID
            
        Returns:
            Airtable base ID or None if not found
        """
        try:
            response = supabase.table('scraping_jobs')\
                .select('airtable_base_id')\
                .eq('job_id', job_id)\
                .single()\
                .execute()
            
            return response.data['airtable_base_id'] if response.data else None
        except Exception as e:
            print(f"Error fetching Airtable base ID: {e}")
            return None
    
    @staticmethod
    def get_job_statistics(job_id: str) -> Dict:
        """
        Get statistics for a scraping job
        
        Returns:
            Dictionary with counts of usernames, assignments, etc.
        """
        try:
            # Count usernames
            usernames_response = supabase.table('global_usernames')\
                .select('*', count='exact')\
                .eq('job_id', job_id)\
                .execute()
            
            # Count available usernames
            available_response = supabase.table('global_usernames')\
                .select('*', count='exact')\
                .eq('job_id', job_id)\
                .eq('used', False)\
                .execute()
            
            # Count assignments
            assignments_response = supabase.table('daily_assignments')\
                .select('*', count='exact')\
                .eq('job_id', job_id)\
                .execute()
            
            # Count scrape results
            results_response = supabase.table('scrape_results')\
                .select('*', count='exact')\
                .eq('scraping_job_id', job_id)\
                .execute()
            
            return {
                'total_usernames': usernames_response.count or 0,
                'available_usernames': available_response.count or 0,
                'used_usernames': (usernames_response.count or 0) - (available_response.count or 0),
                'total_assignments': assignments_response.count or 0,
                'total_scrape_results': results_response.count or 0
            }
        except Exception as e:
            print(f"Error fetching job statistics: {e}")
            return {
                'total_usernames': 0,
                'available_usernames': 0,
                'used_usernames': 0,
                'total_assignments': 0,
                'total_scrape_results': 0
            }


class UsernameManager:
    """Manager for username operations linked to jobs"""
    
    @staticmethod
    def add_usernames_to_job(
        job_id: str,
        profiles: List[Dict]
    ) -> bool:
        """
        Add scraped usernames to a specific job
        
        Args:
            job_id: The scraping job ID
            profiles: List of profile dictionaries with keys: id, username, full_name
            
        Returns:
            True if successful, False otherwise
        """
        try:
            usernames = [{
                'id': p['id'],
                'username': p['username'],
                'full_name': p.get('full_name'),
                'job_id': job_id,
                'used': False
            } for p in profiles]
            
            supabase.table('global_usernames').insert(usernames).execute()
            return True
        except Exception as e:
            print(f"Error adding usernames to job: {e}")
            return False
    
    @staticmethod
    def get_available_usernames(
        job_id: str,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        Get available (unused) usernames for a job
        
        Args:
            job_id: The scraping job ID
            limit: Maximum number of usernames to return (optional)
            
        Returns:
            List of available username dictionaries
        """
        try:
            query = supabase.table('global_usernames')\
                .select('*')\
                .eq('job_id', job_id)\
                .eq('used', False)\
                .order('created_at', desc=True)
            
            if limit:
                query = query.limit(limit)
            
            response = query.execute()
            return response.data or []
        except Exception as e:
            print(f"Error fetching available usernames: {e}")
            return []
    
    @staticmethod
    def mark_usernames_as_used(
        job_id: str,
        username_ids: List[str]
    ) -> bool:
        """Mark usernames as used"""
        try:
            supabase.table('global_usernames')\
                .update({
                    'used': True,
                    'used_at': datetime.utcnow().isoformat()
                })\
                .eq('job_id', job_id)\
                .in_('id', username_ids)\
                .execute()
            return True
        except Exception as e:
            print(f"Error marking usernames as used: {e}")
            return False


class AssignmentManager:
    """Manager for assignment operations linked to jobs"""
    
    @staticmethod
    def create_assignments(
        job_id: str,
        campaign_id: str,
        assignments: List[Dict]
    ) -> bool:
        """
        Create assignments for a specific job
        
        Args:
            job_id: The scraping job ID
            campaign_id: The campaign ID
            assignments: List of assignment dictionaries
            
        Returns:
            True if successful, False otherwise
        """
        try:
            assignment_data = [{
                'campaign_id': campaign_id,
                'id': a['id'],
                'username': a['username'],
                'full_name': a.get('full_name'),
                'va_table_number': a['va_table_number'],
                'position': a['position'],
                'job_id': job_id,
                'status': 'pending'
            } for a in assignments]
            
            supabase.table('daily_assignments').insert(assignment_data).execute()
            return True
        except Exception as e:
            print(f"Error creating assignments: {e}")
            return False
    
    @staticmethod
    def get_job_assignments(
        job_id: str,
        status: Optional[str] = None
    ) -> List[Dict]:
        """Get assignments for a specific job, optionally filtered by status"""
        try:
            query = supabase.table('daily_assignments')\
                .select('*')\
                .eq('job_id', job_id)
            
            if status:
                query = query.eq('status', status)
            
            response = query.order('assigned_at', desc=True).execute()
            return response.data or []
        except Exception as e:
            print(f"Error fetching job assignments: {e}")
            return []


class AirtableIntegration:
    """Helper for Airtable integration with multi-tenant jobs"""
    
    @staticmethod
    def send_profiles_to_job_airtable(
        job_id: str,
        profiles: List[Dict],
        airtable_client
    ) -> bool:
        """
        Send profiles to the Airtable base associated with a job
        
        Args:
            job_id: The scraping job ID
            profiles: List of profile dictionaries to send
            airtable_client: Your Airtable client instance
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Get the Airtable base ID for this job
            base_id = ScrapingJobsManager.get_airtable_base_id(job_id)
            
            if not base_id:
                print(f"No Airtable base found for job {job_id}")
                return False
            
            # Initialize Airtable for this specific base
            # (Implementation depends on your Airtable client)
            # Example: airtable = airtable_client.base(base_id)
            
            # Send profiles to Airtable
            for profile in profiles:
                # Your Airtable insertion logic here
                # airtable.table('Profiles').create({
                #     'Username': profile['username'],
                #     'Full Name': profile.get('full_name', ''),
                #     'Job ID': job_id,
                #     # ... other fields
                # })
                pass
            
            return True
        except Exception as e:
            print(f"Error sending profiles to Airtable: {e}")
            return False


# Utility functions

def is_legacy_job(job_id: str) -> bool:
    """Check if a job ID is the legacy placeholder"""
    return job_id == LEGACY_PLACEHOLDER_JOB_ID


def get_legacy_job() -> Optional[Dict]:
    """Get the legacy placeholder job"""
    return ScrapingJobsManager.get_job(LEGACY_PLACEHOLDER_JOB_ID)


# Example usage
if __name__ == '__main__':
    # Create a new job
    job = ScrapingJobsManager.create_job(
        influencer_name='John Doe',
        platform='instagram',
        airtable_base_id='appXYZ123ABC',
        num_vas=80
    )
    
    if job:
        print(f"Created job: {job['job_id']}")
        
        # Add usernames to the job
        profiles = [
            {'id': '123', 'username': 'user1', 'full_name': 'User One'},
            {'id': '456', 'username': 'user2', 'full_name': 'User Two'}
        ]
        UsernameManager.add_usernames_to_job(job['job_id'], profiles)
        
        # Get statistics
        stats = ScrapingJobsManager.get_job_statistics(job['job_id'])
        print(f"Job stats: {stats}")
