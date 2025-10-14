# 🏗️ System Architecture Diagram

## Complete Request Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           CLIENT APPLICATION                            │
│                      (Next.js / Frontend / API User)                    │
└────────────┬────────────────────────────────────────────────────────────┘
             │
             │ POST /api/scrape-followers
             │ {accounts: [...], targetGender: "male", totalScrapeCount: 500000}
             │
             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                              FLASK API                                  │
│                        (Gunicorn Web Dyno)                              │
│                                                                         │
│  1. Validate request                                                    │
│  2. Create job record in Supabase (scrape_jobs)                       │
│  3. Split accounts into batches of 50                                  │
│  4. Queue Celery tasks in Redis                                        │
│  5. Return 202 Accepted with job_id                                    │
│                                                                         │
│  Response: {                                                            │
│    "job_id": "uuid-here",                                              │
│    "status_url": "/api/job-status/uuid",                              │
│    "total_batches": 10000                                              │
│  }                                                                      │
└────────────┬────────────────────────────────────────────────────────────┘
             │
             │ < 200ms response time ⚡
             │
             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                            REDIS QUEUE                                  │
│                    (Heroku Redis or Local)                              │
│                                                                         │
│  Queue: celery                                                          │
│  ├── Task 1: scrape_account_batch (accounts[0:50])                    │
│  ├── Task 2: scrape_account_batch (accounts[50:100])                  │
│  ├── Task 3: scrape_account_batch (accounts[100:150])                 │
│  └── ... (10,000 tasks for 500K accounts)                             │
│                                                                         │
│  After all batches: aggregate_scrape_results                           │
└────────────┬────────────────────────────────────────────────────────────┘
             │
             │ Tasks distributed to workers
             │
             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         CELERY WORKERS                                  │
│                    (4-8 Worker Dynos/Processes)                         │
│                                                                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │  Worker 1   │  │  Worker 2   │  │  Worker 3   │  │  Worker 4   │  │
│  │             │  │             │  │             │  │             │  │
│  │  Batch 1    │  │  Batch 2    │  │  Batch 3    │  │  Batch 4    │  │
│  │  (50 acc)   │  │  (50 acc)   │  │  (50 acc)   │  │  (50 acc)   │  │
│  └─────┬───────┘  └─────┬───────┘  └─────┬───────┘  └─────┬───────┘  │
│        │                │                │                │          │
│        │ Each worker processes:                            │          │
│        │ 1. Scrape followers (Apify)                       │          │
│        │ 2. Detect gender                                  │          │
│        │ 3. Filter by target gender                        │          │
│        │ 4. Return profiles                                │          │
│        │                                                    │          │
└────────┴────────────────┴────────────────┴────────────────┴──────────┘
             │                │                │                │
             └────────────────┴────────────────┴────────────────┘
                                      │
                                      │ Parallel processing 🚀
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        APIFY ACTOR                                      │
│                  (Instagram Follower Scraper)                           │
│                                                                         │
│  Input: {                                                               │
│    usernames: ["nike", "adidas", ...],                                 │
│    max_count: 100                                                       │
│  }                                                                      │
│                                                                         │
│  Output: [                                                              │
│    {id: "123", username: "john_doe", full_name: "John Doe", ...},      │
│    ...                                                                  │
│  ]                                                                      │
└────────────┬────────────────────────────────────────────────────────────┘
             │
             │ Scraped profiles returned
             │
             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    BATCH AGGREGATION                                    │
│              (Runs after all batches complete)                          │
│                                                                         │
│  aggregate_scrape_results task:                                         │
│  1. Combine all batch results                                          │
│  2. Insert into Supabase in chunks of 1000                             │
│  3. Update job status to "completed"                                   │
│  4. Record total_scraped and total_filtered                            │
└────────────┬────────────────────────────────────────────────────────────┘
             │
             │ Batch insert (1000 profiles/batch)
             │
             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         SUPABASE DATABASE                               │
│                        (PostgreSQL + APIs)                              │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ scrape_jobs                                                       │  │
│  │ ├── job_id (UUID, PK)                                            │  │
│  │ ├── status ("queued" → "processing" → "completed")               │  │
│  │ ├── progress (0% → 100%)                                         │  │
│  │ ├── profiles_scraped (incremental count)                         │  │
│  │ ├── total_batches, current_batch                                 │  │
│  │ └── error_message (if failed)                                    │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ scrape_results                                                    │  │
│  │ ├── id (SERIAL, PK)                                              │  │
│  │ ├── job_id (UUID, FK)                                            │  │
│  │ ├── profile_id, username, full_name                              │  │
│  │ └── created_at                                                   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────┬────────────────────────────────────────────────────────────┘
             │
             │ Job complete, results stored
             │
             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         CLIENT POLLING                                  │
│                                                                         │
│  Loop every 5 seconds:                                                  │
│                                                                         │
│  GET /api/job-status/{job_id}                                          │
│  ↓                                                                      │
│  {                                                                      │
│    "status": "processing",                                             │
│    "progress": 45.5,                                                   │
│    "profiles_scraped": 227500                                          │
│  }                                                                      │
│                                                                         │
│  If status === "completed":                                            │
│                                                                         │
│  GET /api/job-results/{job_id}?page=1&limit=1000                       │
│  ↓                                                                      │
│  {                                                                      │
│    "profiles": [{...}, {...}, ...],                                    │
│    "total": 500000,                                                    │
│    "page": 1,                                                          │
│    "limit": 1000                                                       │
│  }                                                                      │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow (500K Accounts Example)

### Phase 1: Job Creation (< 1 second)
```
Client → Flask API
├── Validate 10,000 accounts
├── Calculate: 10,000 accounts × 50 followers each = 500,000 target
├── Batch size: 50 accounts/worker
├── Total batches: 10,000 ÷ 50 = 200 batches
├── Create job record in scrape_jobs
└── Queue 200 Celery tasks in Redis

Response: 202 Accepted + job_id
Time: ~200ms ⚡
```

### Phase 2: Parallel Processing (3-8 hours)
```
Worker 1              Worker 2              Worker 3              Worker 4
├─ Batch 1 (50 acc)   ├─ Batch 2 (50 acc)   ├─ Batch 3 (50 acc)   ├─ Batch 4 (50 acc)
│  ↓ Apify scrape     │  ↓ Apify scrape     │  ↓ Apify scrape     │  ↓ Apify scrape
│  ↓ Gender detect    │  ↓ Gender detect    │  ↓ Gender detect    │  ↓ Gender detect
│  ↓ Filter           │  ↓ Filter           │  ↓ Filter           │  ↓ Filter
│  ↓ Return ~2500     │  ↓ Return ~2500     │  ↓ Return ~2500     │  ↓ Return ~2500
│                     │                     │                     │
├─ Batch 5 (50 acc)   ├─ Batch 6 (50 acc)   ├─ Batch 7 (50 acc)   ├─ Batch 8 (50 acc)
│  ↓ ...              │  ↓ ...              │  ↓ ...              │  ↓ ...
...                   ...                   ...                   ...
└─ Batch 197          └─ Batch 198          └─ Batch 199          └─ Batch 200

Each worker:
- Memory: < 1GB
- Time per batch: ~1-3 min
- Retries: 3x on failure
- Updates job progress in real-time
```

### Phase 3: Aggregation (5-15 minutes)
```
aggregate_scrape_results task:
├── Collect results from all 200 batches
├── Total profiles: ~500,000
│
├── Batch insert into scrape_results (chunks of 1000)
│   ├── Insert 1-1000
│   ├── Insert 1001-2000
│   ├── Insert 2001-3000
│   └── ... (500 inserts total)
│
├── Update scrape_jobs:
│   ├── status = "completed"
│   ├── total_scraped = 500,000
│   ├── progress = 100.0
│   └── completed_at = NOW()
│
└── Job complete ✅
```

### Phase 4: Result Retrieval (< 1 second per page)
```
Client polls /api/job-status/{job_id}
├── Check every 5 seconds
├── Progress: 0% → 25% → 50% → 75% → 100%
└── Status: "queued" → "processing" → "completed"

Client fetches /api/job-results/{job_id}?page=1&limit=1000
├── Page 1: Profiles 1-1000
├── Page 2: Profiles 1001-2000
├── Page 3: Profiles 2001-3000
└── ... (500 pages total)
```

---

## Scaling Diagram

### Development (1-100 profiles)
```
┌──────────┐    ┌────────┐    ┌──────────┐
│  Flask   │───→│ Redis  │───→│  Worker  │
│  (Local) │    │(Local) │    │  (x1)    │
└──────────┘    └────────┘    └──────────┘
Cost: $0/month
```

### Production (1K-10K profiles)
```
┌──────────┐    ┌──────────┐    ┌───────────┐
│  Flask   │───→│  Redis   │───→│  Workers  │
│ Standard │    │   Mini   │    │  (x2-4)   │
│   -1X    │    │          │    │ Standard  │
└──────────┘    └──────────┘    └───────────┘
Cost: ~$140/month
```

### Scale (100K-500K profiles)
```
┌──────────┐    ┌──────────┐    ┌───────────┐
│  Flask   │───→│  Redis   │───→│  Workers  │
│ Standard │    │ Premium  │    │  (x8-16)  │
│   -2X    │    │    -0    │    │ Standard  │
│  (x2)    │    │          │    │   -2X     │
└──────────┘    └──────────┘    └───────────┘
Cost: ~$465/month
```

### Enterprise (1M+ profiles)
```
┌──────────┐    ┌──────────┐    ┌───────────┐
│  Flask   │───→│  Redis   │───→│  Workers  │
│Performance│   │ Premium  │    │  (x16-32) │
│    -L     │    │    -5    │    │Performance│
│  (x4)     │    │          │    │    -L     │
└──────────┘    └──────────┘    └───────────┘
Cost: ~$1500/month
```

---

## Error Handling Flow

```
                    Request
                       ↓
              ┌────────────────┐
              │   Validation   │
              └────────┬───────┘
                       │
                   ✗ Invalid ──→ 400 Bad Request
                       │
                   ✓ Valid
                       ↓
              ┌────────────────┐
              │   Create Job   │
              └────────┬───────┘
                       │
                   ✗ DB Error ──→ 500 Internal Error
                       │
                   ✓ Created
                       ↓
              ┌────────────────┐
              │   Queue Tasks  │
              └────────┬───────┘
                       │
                   ✗ Queue Full ──→ 503 Service Unavailable
                       │
                   ✓ Queued
                       ↓
              ┌────────────────┐
              │ Worker Process │
              └────────┬───────┘
                       │
                   ✗ Fail ──→ Retry (3x)
                       │           │
                       │       After 3 fails
                       │           ↓
                       │      Update job:
                       │      status = "failed"
                       │      error_message = "..."
                       │
                   ✓ Success
                       ↓
              ┌────────────────┐
              │ Store Results  │
              └────────┬───────┘
                       │
                   ✗ DB Error ──→ Retry (3x)
                       │
                   ✓ Stored
                       ↓
              ┌────────────────┐
              │ Job Complete   │
              └────────────────┘
```

---

## Monitoring Points

```
┌─────────────────────────────────────────────────────────────┐
│                     MONITORING STACK                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Flask API Metrics                                       │
│     ├── Request rate (req/min)                             │
│     ├── Response time (ms)                                 │
│     ├── Error rate (%)                                     │
│     └── Active connections                                 │
│                                                             │
│  2. Celery Worker Metrics                                  │
│     ├── Tasks processed/min                                │
│     ├── Queue length                                       │
│     ├── Worker CPU/Memory                                  │
│     └── Task success rate                                  │
│                                                             │
│  3. Redis Metrics                                          │
│     ├── Queue depth                                        │
│     ├── Memory usage                                       │
│     ├── Connection count                                   │
│     └── Eviction rate                                      │
│                                                             │
│  4. Database Metrics                                       │
│     ├── Query performance                                  │
│     ├── Connection pool                                    │
│     ├── Table sizes                                        │
│     └── Index usage                                        │
│                                                             │
│  5. Business Metrics                                       │
│     ├── Jobs/day                                           │
│     ├── Profiles/day                                       │
│     ├── Success rate                                       │
│     └── Processing time                                    │
│                                                             │
│  Tools:                                                    │
│  ├── Heroku Metrics Dashboard                             │
│  ├── Sentry (errors & performance)                         │
│  ├── Supabase Dashboard                                    │
│  └── Custom logging                                        │
└─────────────────────────────────────────────────────────────┘
```

---

## File Structure Map

```
server/
│
├── 🚀 Core Application
│   ├── app.py                    # Main Flask app (refactored)
│   ├── wsgi.py                   # Production entry point
│   ├── celery_config.py          # Task queue config
│   ├── tasks.py                  # Background tasks
│   └── api_async.py              # Async endpoints
│
├── 🔧 Utilities
│   └── utils/
│       ├── __init__.py
│       ├── scraper.py            # Apify integration
│       ├── gender.py             # Gender detection
│       └── batch_processor.py   # Batch DB operations
│
├── ⚙️ Configuration
│   ├── requirements.txt          # Python dependencies
│   ├── Procfile                  # Heroku dyno config
│   ├── runtime.txt               # Python version
│   └── .env                      # Environment variables
│
├── 🗄️ Database
│   └── migrations/
│       └── 001_add_job_tracking.sql
│
├── 📚 Documentation
│   ├── README.md                 # Complete overview
│   ├── DEPLOYMENT.md             # Heroku deployment
│   ├── TESTING.md                # Testing guide
│   ├── TRANSFORMATION_SUMMARY.md # What changed
│   ├── COMPLETION_SUMMARY.md     # Quick reference
│   └── ARCHITECTURE.md           # This file
│
└── 🛠️ Scripts
    ├── quickstart.sh             # Local dev setup
    ├── test_api.sh               # API testing
    └── start_all.sh              # Start all services
```

---

**This architecture supports:**
- ✅ 1,000,000+ accounts/month
- ✅ Horizontal scaling (add more workers)
- ✅ Fault tolerance (automatic retries)
- ✅ Real-time progress tracking
- ✅ Efficient memory usage (< 1GB/worker)
- ✅ Zero-downtime deployments
