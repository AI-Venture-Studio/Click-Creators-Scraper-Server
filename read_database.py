#!/usr/bin/env python3
"""
Quick script to read and display Supabase database tables
"""
import os
import sys
from dotenv import load_dotenv
from supabase import create_client

# Load environment variables
load_dotenv()

# Initialize Supabase client
supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

if not supabase_url or not supabase_key:
    print("❌ Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY not found in .env")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

print("=" * 80)
print("📊 SUPABASE DATABASE OVERVIEW")
print("=" * 80)
print(f"\nProject URL: {supabase_url}\n")

# List of your tables
tables = [
    'global_usernames',
    'raw_scraped_profiles',
    'campaigns',
    'daily_assignments',
    'source_profiles',
    'scrape_jobs',      # New async table
    'scrape_results'    # New async table
]

for table_name in tables:
    print(f"\n{'=' * 80}")
    print(f"📋 TABLE: {table_name}")
    print('=' * 80)
    
    try:
        # Get row count
        count_response = supabase.table(table_name).select('*', count='exact').limit(0).execute()
        total_count = count_response.count if hasattr(count_response, 'count') else 0
        
        # Get sample data (first 5 rows)
        sample_response = supabase.table(table_name).select('*').limit(5).execute()
        
        print(f"\n📊 Total Records: {total_count}")
        
        if sample_response.data:
            print(f"\n🔍 Sample Data (first 5 rows):")
            print("-" * 80)
            
            # Show column names
            columns = list(sample_response.data[0].keys())
            print(f"\nColumns: {', '.join(columns)}")
            
            # Show data
            for i, row in enumerate(sample_response.data, 1):
                print(f"\nRow {i}:")
                for key, value in row.items():
                    # Truncate long values
                    str_value = str(value)
                    if len(str_value) > 100:
                        str_value = str_value[:100] + "..."
                    print(f"  {key}: {str_value}")
        else:
            print("\n⚠️  No data in this table")
            
    except Exception as e:
        print(f"\n❌ Error reading table: {str(e)}")

print("\n" + "=" * 80)
print("✅ Database scan complete!")
print("=" * 80)

# Check if new async tables exist
print("\n" + "=" * 80)
print("🔍 CHECKING NEW ASYNC TABLES")
print("=" * 80)

async_tables = ['scrape_jobs', 'scrape_results']
for table_name in async_tables:
    try:
        response = supabase.table(table_name).select('*', count='exact').limit(0).execute()
        if hasattr(response, 'count'):
            print(f"✅ {table_name}: EXISTS (Migration applied)")
        else:
            print(f"⚠️  {table_name}: Response received but count unavailable")
    except Exception as e:
        if 'does not exist' in str(e).lower() or 'relation' in str(e).lower():
            print(f"❌ {table_name}: DOES NOT EXIST")
            print(f"   ⚠️  ACTION REQUIRED: Apply migration file: migrations/001_add_job_tracking.sql")
        else:
            print(f"❓ {table_name}: ERROR - {str(e)}")

print("\n" + "=" * 80)
