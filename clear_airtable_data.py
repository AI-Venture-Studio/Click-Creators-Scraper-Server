#!/usr/bin/env python3
"""
Clear Airtable Data Script
==========================
Safely deletes all records from Airtable tables while preserving schema (field structure).

Usage:
    python clear_airtable_data.py

Environment Variables Required:
    - AIRTABLE_ACCESS_TOKEN: Your Airtable API token
    - AIRTABLE_BASE_ID: Your Airtable base ID
    - NUM_VA_TABLES: Number of VA tables (default: 80)
"""

import os
import sys
from dotenv import load_dotenv
from pyairtable import Api
import time

# Load environment variables
load_dotenv()

# ANSI color codes for terminal output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def get_all_table_names(num_tables: int) -> list:
    """Generate list of all table names based on NUM_VA_TABLES."""
    return [f"Daily_Outreach_Table_{i:02d}" for i in range(1, num_tables + 1)]

def fetch_all_records(table):
    """Fetch all records from a table with pagination handling."""
    try:
        all_records = table.all()
        return all_records
    except Exception as e:
        print(f"{Colors.RED}✗ Error fetching records: {str(e)}{Colors.END}")
        return []

def delete_records_in_batches(table, record_ids: list, batch_size: int = 10):
    """Delete records in batches of 10 (Airtable API limit)."""
    total_deleted = 0
    
    for i in range(0, len(record_ids), batch_size):
        batch = record_ids[i:i + batch_size]
        try:
            table.batch_delete(batch)
            total_deleted += len(batch)
            # Rate limiting: 5 requests per second
            time.sleep(0.2)
        except Exception as e:
            print(f"{Colors.RED}✗ Error deleting batch: {str(e)}{Colors.END}")
            raise e
    
    return total_deleted

def clear_table(api: Api, base_id: str, table_name: str) -> dict:
    """Clear all records from a single table."""
    result = {
        'table_name': table_name,
        'success': False,
        'records_deleted': 0,
        'error': None
    }
    
    try:
        # Get table reference
        table = api.table(base_id, table_name)
        
        # Fetch all records
        all_records = fetch_all_records(table)
        
        if not all_records:
            result['success'] = True
            result['records_deleted'] = 0
            return result
        
        # Extract record IDs
        record_ids = [record['id'] for record in all_records]
        
        # Delete in batches
        deleted_count = delete_records_in_batches(table, record_ids)
        
        result['success'] = True
        result['records_deleted'] = deleted_count
        
    except Exception as e:
        result['error'] = str(e)
    
    return result

def main():
    """Main execution function."""
    print(f"\n{Colors.BOLD}🗑️  Airtable Data Cleaner{Colors.END}")
    print("=" * 50)
    
    # Load configuration from environment
    airtable_token = os.getenv('AIRTABLE_ACCESS_TOKEN')
    base_id = os.getenv('AIRTABLE_BASE_ID')
    num_tables = int(os.getenv('NUM_VA_TABLES', '80'))
    
    # Validate environment variables
    if not airtable_token:
        print(f"{Colors.RED}✗ Error: AIRTABLE_ACCESS_TOKEN not found in .env file{Colors.END}")
        sys.exit(1)
    
    if not base_id:
        print(f"{Colors.RED}✗ Error: AIRTABLE_BASE_ID not found in .env file{Colors.END}")
        sys.exit(1)
    
    # Generate table names
    table_names = get_all_table_names(num_tables)
    
    print(f"\n{Colors.BLUE}📋 Configuration:{Colors.END}")
    print(f"   Base ID: {base_id}")
    print(f"   Number of tables: {num_tables}")
    print(f"   Tables: {table_names[0]} to {table_names[-1]}")
    
    # Safety confirmation
    print(f"\n{Colors.YELLOW}{Colors.BOLD}⚠️  WARNING:{Colors.END}")
    print(f"{Colors.YELLOW}   This will permanently delete ALL records from {num_tables} tables.{Colors.END}")
    print(f"{Colors.YELLOW}   The table structure (fields) will be preserved.{Colors.END}")
    
    confirmation = input(f"\n{Colors.BOLD}Proceed? (y/n): {Colors.END}").strip().lower()
    
    if confirmation != 'y':
        print(f"\n{Colors.YELLOW}Operation cancelled.{Colors.END}\n")
        sys.exit(0)
    
    # Initialize Airtable API client
    try:
        api = Api(airtable_token)
        print(f"\n{Colors.GREEN}✓ Connected to Airtable{Colors.END}\n")
    except Exception as e:
        print(f"\n{Colors.RED}✗ Failed to connect to Airtable: {str(e)}{Colors.END}\n")
        sys.exit(1)
    
    # Clear each table
    print(f"{Colors.BOLD}Starting cleanup...{Colors.END}\n")
    
    total_records_deleted = 0
    successful_tables = 0
    failed_tables = []
    
    for idx, table_name in enumerate(table_names, 1):
        print(f"[{idx}/{num_tables}] Clearing {Colors.BOLD}{table_name}{Colors.END}...", end=" ")
        
        result = clear_table(api, base_id, table_name)
        
        if result['success']:
            print(f"{Colors.GREEN}✓ done ({result['records_deleted']} records deleted){Colors.END}")
            total_records_deleted += result['records_deleted']
            successful_tables += 1
        else:
            print(f"{Colors.RED}✗ failed{Colors.END}")
            print(f"   {Colors.RED}Error: {result['error']}{Colors.END}")
            failed_tables.append(table_name)
    
    # Summary
    print(f"\n{Colors.BOLD}{'=' * 50}{Colors.END}")
    print(f"{Colors.BOLD}📊 Summary:{Colors.END}")
    print(f"   {Colors.GREEN}✓ Successfully cleared: {successful_tables}/{num_tables} tables{Colors.END}")
    print(f"   {Colors.BLUE}📝 Total records deleted: {total_records_deleted}{Colors.END}")
    
    if failed_tables:
        print(f"   {Colors.RED}✗ Failed tables: {len(failed_tables)}{Colors.END}")
        for table in failed_tables:
            print(f"      - {table}")
    else:
        print(f"\n{Colors.GREEN}{Colors.BOLD}✅ All tables cleared successfully!{Colors.END}\n")
    
    print()

if __name__ == "__main__":
    main()
