-- =====================================================================
-- DATABASE PERFORMANCE INDEXES FOR 500K+ SCALE
-- =====================================================================
-- 
-- INSTRUCTIONS:
-- 1. Go to your Supabase Dashboard (https://supabase.com/dashboard)
-- 2. Select your project
-- 3. Click "SQL Editor" in the left sidebar
-- 4. Click "New Query"
-- 5. Copy and paste this ENTIRE file
-- 6. Click "Run" (or press Cmd+Enter / Ctrl+Enter)
-- 7. Wait for confirmation message: "Success. No rows returned"
--
-- SAFE TO RUN: These commands are idempotent (can be run multiple times)
-- If an index already exists, it will just skip that one.
--
-- ESTIMATED TIME: 30 seconds - 2 minutes (depending on existing data)
-- =====================================================================


-- =====================================================================
-- INDEX 1: global_usernames.used (CRITICAL)
-- =====================================================================
-- PURPOSE: Speed up daily selection query that finds unused profiles
-- QUERY AFFECTED: SELECT * FROM global_usernames WHERE used = false LIMIT 14400
-- IMPACT: 60 seconds → <1 second at 500K records
-- 
-- This is a PARTIAL INDEX - only indexes rows where used = false
-- Much more efficient than indexing the entire column
-- =====================================================================

CREATE INDEX IF NOT EXISTS idx_global_usernames_used_false 
ON global_usernames(used) 
WHERE used = false;

-- Add comment for documentation
COMMENT ON INDEX idx_global_usernames_used_false IS 
'Speeds up daily profile selection by indexing unused profiles only';


-- =====================================================================
-- INDEX 2: global_usernames.id (CRITICAL FOR BULK LOOKUPS)
-- =====================================================================
-- PURPOSE: Speed up duplicate checking during bulk scraping
-- QUERY AFFECTED: SELECT id FROM global_usernames WHERE id IN (...)
-- IMPACT: 500K individual queries → 500 bulk queries
-- =====================================================================

CREATE INDEX IF NOT EXISTS idx_global_usernames_id 
ON global_usernames(id);

COMMENT ON INDEX idx_global_usernames_id IS 
'Speeds up bulk duplicate checking during profile ingestion';


-- =====================================================================
-- INDEX 3: daily_assignments.status (HIGH PRIORITY)
-- =====================================================================
-- PURPOSE: Speed up status-based queries (pending, followed, completed, etc.)
-- QUERIES AFFECTED: 
--   - SELECT * FROM daily_assignments WHERE status = 'followed'
--   - SELECT * FROM daily_assignments WHERE status = 'completed'
-- IMPACT: Full table scan → index lookup (30 sec → <1 sec)
-- =====================================================================

CREATE INDEX IF NOT EXISTS idx_daily_assignments_status 
ON daily_assignments(status);

COMMENT ON INDEX idx_daily_assignments_status IS 
'Speeds up status filtering for cleanup and sync operations';


-- =====================================================================
-- INDEX 4: daily_assignments.assigned_at (HIGH PRIORITY)
-- =====================================================================
-- PURPOSE: Speed up date-based cleanup queries
-- QUERIES AFFECTED:
--   - SELECT * FROM daily_assignments WHERE assigned_at >= '2024-10-08'
--   - SELECT * FROM daily_assignments WHERE assigned_at < '2024-10-01'
-- IMPACT: Critical for 7-day lifecycle cleanup performance
-- =====================================================================

CREATE INDEX IF NOT EXISTS idx_daily_assignments_assigned_at 
ON daily_assignments(assigned_at);

COMMENT ON INDEX idx_daily_assignments_assigned_at IS 
'Speeds up date-range queries for lifecycle cleanup';


-- =====================================================================
-- INDEX 5: daily_assignments.campaign_id (MEDIUM PRIORITY)
-- =====================================================================
-- PURPOSE: Speed up campaign-specific queries
-- QUERIES AFFECTED:
--   - SELECT * FROM daily_assignments WHERE campaign_id = 'uuid'
-- IMPACT: Faster campaign distribution and reporting
-- =====================================================================

CREATE INDEX IF NOT EXISTS idx_daily_assignments_campaign_id 
ON daily_assignments(campaign_id);

COMMENT ON INDEX idx_daily_assignments_campaign_id IS 
'Speeds up campaign-specific queries during distribution';


-- =====================================================================
-- INDEX 6: daily_assignments.va_table_number (MEDIUM PRIORITY)
-- =====================================================================
-- PURPOSE: Speed up VA table filtering
-- QUERIES AFFECTED:
--   - SELECT * FROM daily_assignments WHERE va_table_number = 1
--   - SELECT * FROM daily_assignments WHERE va_table_number > 0
-- IMPACT: Faster per-VA reporting and status checks
-- =====================================================================

CREATE INDEX IF NOT EXISTS idx_daily_assignments_va_table_number 
ON daily_assignments(va_table_number);

COMMENT ON INDEX idx_daily_assignments_va_table_number IS 
'Speeds up VA table filtering and reporting';


-- =====================================================================
-- INDEX 7: scrape_jobs.job_id (MEDIUM PRIORITY)
-- =====================================================================
-- PURPOSE: Speed up job status lookups
-- QUERIES AFFECTED:
--   - SELECT * FROM scrape_jobs WHERE job_id = 'uuid'
-- IMPACT: Faster job status polling
-- =====================================================================

CREATE INDEX IF NOT EXISTS idx_scrape_jobs_job_id 
ON scrape_jobs(job_id);

COMMENT ON INDEX idx_scrape_jobs_job_id IS 
'Speeds up job status lookups in async scraping endpoints';


-- =====================================================================
-- INDEX 8: scrape_results.job_id (MEDIUM PRIORITY)
-- =====================================================================
-- PURPOSE: Speed up scrape result retrieval by job
-- QUERIES AFFECTED:
--   - SELECT * FROM scrape_results WHERE job_id = 'uuid'
-- IMPACT: Faster result pagination and retrieval
-- =====================================================================

CREATE INDEX IF NOT EXISTS idx_scrape_results_job_id 
ON scrape_results(job_id);

COMMENT ON INDEX idx_scrape_results_job_id IS 
'Speeds up scrape result retrieval for completed jobs';


-- =====================================================================
-- COMPOSITE INDEX 9: daily_assignments (status + assigned_at)
-- =====================================================================
-- PURPOSE: Optimize the most common cleanup query
-- QUERY AFFECTED:
--   - SELECT * FROM daily_assignments 
--     WHERE status = 'followed' AND assigned_at <= '2024-10-08'
-- IMPACT: Super-fast cleanup operations
-- =====================================================================

CREATE INDEX IF NOT EXISTS idx_daily_assignments_status_assigned_at 
ON daily_assignments(status, assigned_at);

COMMENT ON INDEX idx_daily_assignments_status_assigned_at IS 
'Composite index for optimized cleanup queries combining status and date';


-- =====================================================================
-- VERIFICATION QUERIES
-- =====================================================================
-- Run these after creating indexes to verify they exist
-- =====================================================================

-- List all indexes on global_usernames
SELECT 
    indexname,
    indexdef
FROM pg_indexes 
WHERE tablename = 'global_usernames'
ORDER BY indexname;

-- List all indexes on daily_assignments
SELECT 
    indexname,
    indexdef
FROM pg_indexes 
WHERE tablename = 'daily_assignments'
ORDER BY indexname;

-- List all indexes on scrape_jobs
SELECT 
    indexname,
    indexdef
FROM pg_indexes 
WHERE tablename = 'scrape_jobs'
ORDER BY indexname;

-- List all indexes on scrape_results
SELECT 
    indexname,
    indexdef
FROM pg_indexes 
WHERE tablename = 'scrape_results'
ORDER BY indexname;


-- =====================================================================
-- EXPECTED RESULTS
-- =====================================================================
-- After running this script, you should see:
-- ✓ "Success. No rows returned" message
-- ✓ In the verification queries below, you should see the new indexes listed
--
-- TROUBLESHOOTING:
-- - If you get "permission denied", make sure you're using the service_role key
-- - If you get "table does not exist", check your table names match exactly
-- - You can safely run this script multiple times - it won't create duplicates
-- =====================================================================
