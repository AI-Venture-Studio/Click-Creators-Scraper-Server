# 🚀 Production Deployment Guide

This guide covers deploying the Instagram Scraper API to Heroku with asynchronous task processing.

## 📋 Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [Local Development Setup](#local-development-setup)
4. [Database Setup (Supabase)](#database-setup)
5. [Heroku Deployment](#heroku-deployment)
6. [Environment Variables](#environment-variables)
7. [Testing the API](#testing-the-api)
8. [Monitoring & Troubleshooting](#monitoring--troubleshooting)

---

## 🏗️ Architecture Overview

### System Components

```
┌─────────────────┐
│   Client App    │
│  (Next.js/API)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐      ┌──────────────┐
│  Flask Web API  │◄────►│    Redis     │
│  (Gunicorn)     │      │   (Queue)    │
└────────┬────────┘      └──────▲───────┘
         │                       │
         │                       │
         ▼                       │
┌─────────────────┐             │
│    Supabase     │             │
│   (PostgreSQL)  │             │
└─────────────────┘             │
                                │
                        ┌───────┴────────┐
                        │ Celery Workers │
                        │   (4x dynos)   │
                        └────────────────┘
                                │
                                ▼
                        ┌────────────────┐
                        │  Apify Actor   │
                        │  (Scraping)    │
                        └────────────────┘
```

### Request Flow

**Synchronous Endpoints** (Existing):
- `/api/daily-selection`
- `/api/distribute/<campaign_id>`
- `/api/airtable-sync/<campaign_id>`
- `/api/sync-airtable-statuses`
- `/api/mark-unfollow-due`
- `/api/delete-completed-after-delay`

**Asynchronous Endpoints** (New):
- `/api/scrape-followers` → Returns job_id, queues tasks
- `/api/job-status/<job_id>` → Check job progress
- `/api/job-results/<job_id>` → Get completed results
- `/api/ingest` → Queue profile ingestion
- `/api/run-daily` → Queue daily pipeline

---

## ✅ Prerequisites

### Required Services
- **Heroku Account** (free tier OK for testing)
- **Supabase Project** (free tier OK)
- **Apify Account** with Instagram Follower Scraper actor
- **Airtable Account** with base configured
- **Sentry Account** (optional, for error tracking)

### Local Requirements
```bash
# Required software
python 3.11+
git
heroku CLI
redis (for local testing)
```

---

## 💻 Local Development Setup

### 1. Clone and Install Dependencies

```bash
cd server/

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Install and Start Redis Locally

**macOS (Homebrew):**
```bash
brew install redis
brew services start redis
```

**Ubuntu/Debian:**
```bash
sudo apt-get install redis-server
sudo systemctl start redis
```

**Windows:**
Download from https://redis.io/download

### 3. Configure Environment Variables

Create `.env` file in `server/` directory:

```env
# Flask
FLASK_ENV=development
PORT=5001
SECRET_KEY=your-secret-key-here
API_SECRET_KEY=your-api-key-here
APP_VERSION=1.0.0

# Redis (local)
REDIS_URL=redis://localhost:6379/0

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key

# Apify
APIFY_API_KEY=your-apify-api-key
APIFY_ACTOR_ID=your-actor-id

# Airtable
AIRTABLE_ACCESS_TOKEN=your-airtable-token
AIRTABLE_BASE_ID=your-base-id
NUM_VA_TABLES=80

# CORS (comma-separated)
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5001

# Sentry (optional)
SENTRY_DSN=your-sentry-dsn
```

### 4. Run Database Migrations

Go to Supabase SQL Editor and run:

```bash
# Copy content from migrations/001_add_job_tracking.sql
# Paste and execute in Supabase SQL Editor
```

This creates:
- `scrape_jobs` table for job tracking
- `scrape_results` table for storing profiles
- Indexes for performance
- Cleanup function

### 5. Start Local Services

**Terminal 1 - Flask API:**
```bash
python app.py
# Should start on http://localhost:5001
```

**Terminal 2 - Celery Worker:**
```bash
celery -A celery_config worker --loglevel=info --concurrency=2
```

**Terminal 3 - Celery Beat (optional, for scheduled tasks):**
```bash
celery -A celery_config beat --loglevel=info
```

### 6. Test Locally

```bash
# Test health check
curl http://localhost:5001/health

# Test async scraping (small batch)
curl -X POST http://localhost:5001/api/scrape-followers \
  -H "Content-Type: application/json" \
  -d '{
    "accounts": ["nike", "adidas"],
    "targetGender": "male",
    "totalScrapeCount": 10
  }'

# Check job status (use job_id from above response)
curl http://localhost:5001/api/job-status/<job_id>
```

---

## 🗄️ Database Setup

### Apply Migration to Supabase

1. Go to Supabase Dashboard → SQL Editor
2. Create new query
3. Copy content from `migrations/001_add_job_tracking.sql`
4. Execute the migration
5. Verify tables exist:

```sql
-- Check tables created
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
AND table_name IN ('scrape_jobs', 'scrape_results');
```

### Verify Existing Tables

Ensure these tables exist (created previously):
- `global_usernames`
- `raw_scraped_profiles`
- `campaigns`
- `daily_assignments`
- `source_profiles`

---

## 🚀 Heroku Deployment

### 1. Create Heroku App

```bash
# Login to Heroku
heroku login

# Create app (choose unique name)
heroku create your-instagram-scraper-api

# Add to existing git repo
cd server/
git init
heroku git:remote -a your-instagram-scraper-api
```

### 2. Add Redis Addon

```bash
# Add Redis (required for Celery)
heroku addons:create heroku-redis:mini

# Verify Redis URL is set
heroku config:get REDIS_URL
```

### 3. Set Environment Variables

```bash
# App configuration
heroku config:set FLASK_ENV=production
heroku config:set SECRET_KEY=$(openssl rand -hex 32)
heroku config:set API_SECRET_KEY=$(openssl rand -hex 32)
heroku config:set APP_VERSION=1.0.0

# Supabase
heroku config:set SUPABASE_URL=https://your-project.supabase.co
heroku config:set SUPABASE_SERVICE_ROLE_KEY=your-service-role-key

# Apify
heroku config:set APIFY_API_KEY=your-apify-api-key
heroku config:set APIFY_ACTOR_ID=your-actor-id

# Airtable
heroku config:set AIRTABLE_ACCESS_TOKEN=your-airtable-token
heroku config:set AIRTABLE_BASE_ID=your-base-id
heroku config:set NUM_VA_TABLES=80

# CORS (your production domain)
heroku config:set ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com

# Sentry (optional)
heroku config:set SENTRY_DSN=your-sentry-dsn
```

### 4. Verify Procfile

Ensure `Procfile` exists in `server/`:

```
web: gunicorn wsgi:app --workers 4 --timeout 120 --log-file -
worker: celery -A celery_config worker --loglevel=info --concurrency=4
```

### 5. Deploy to Heroku

```bash
# Commit all changes
git add .
git commit -m "Production ready with async tasks"

# Deploy
git push heroku main

# Check deployment logs
heroku logs --tail
```

### 6. Scale Dynos

```bash
# Scale web dyno (API server)
heroku ps:scale web=1:standard-1x

# Scale worker dynos (Celery workers)
heroku ps:scale worker=4:standard-1x

# Verify dynos running
heroku ps
```

---

## 🔐 Environment Variables

### Complete Environment Variable List

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `FLASK_ENV` | Yes | Environment mode | `production` |
| `PORT` | Auto | Server port (Heroku sets this) | `5000` |
| `SECRET_KEY` | Yes | Flask secret key | Random 32-byte hex |
| `API_SECRET_KEY` | Yes | API authentication key | Random 32-byte hex |
| `APP_VERSION` | No | Application version | `1.0.0` |
| `REDIS_URL` | Yes | Redis connection URL | Auto-set by Heroku addon |
| `SUPABASE_URL` | Yes | Supabase project URL | `https://xxx.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | Supabase service key | `eyJ...` |
| `APIFY_API_KEY` | Yes | Apify API key | `apify_api_...` |
| `APIFY_ACTOR_ID` | Yes | Instagram scraper actor ID | `username~actor-name` |
| `AIRTABLE_ACCESS_TOKEN` | Yes | Airtable personal access token | `pat...` |
| `AIRTABLE_BASE_ID` | Yes | Airtable base ID | `app...` |
| `NUM_VA_TABLES` | Yes | Number of VA tables | `80` |
| `ALLOWED_ORIGINS` | Yes | CORS allowed origins (comma-separated) | `https://app.com` |
| `SENTRY_DSN` | No | Sentry error tracking DSN | `https://...@sentry.io/...` |

---

## 🧪 Testing the API

### 1. Test Health Check

```bash
curl https://your-app.herokuapp.com/health
```

Expected response:
```json
{
  "status": "healthy",
  "service": "Instagram Scraper API (Production)",
  "version": "1.0.0",
  "async_enabled": true
}
```

### 2. Test Async Scraping

```bash
curl -X POST https://your-app.herokuapp.com/api/scrape-followers \
  -H "Content-Type: application/json" \
  -d '{
    "accounts": ["nike", "adidas", "puma"],
    "targetGender": "male",
    "totalScrapeCount": 150
  }'
```

Expected response:
```json
{
  "success": true,
  "job_id": "uuid-here",
  "status_url": "/api/job-status/uuid-here",
  "results_url": "/api/job-results/uuid-here",
  "total_batches": 3,
  "message": "Job queued successfully. Poll status_url for progress."
}
```

### 3. Check Job Status

```bash
curl https://your-app.herokuapp.com/api/job-status/<job_id>
```

Statuses:
- `queued` - Job created, waiting to start
- `processing` - Workers are scraping
- `completed` - All done, results available
- `failed` - Error occurred, check error_message

### 4. Get Results

```bash
# Get first 1000 results
curl "https://your-app.herokuapp.com/api/job-results/<job_id>?page=1&limit=1000"
```

### 5. Test Profile Ingestion

```bash
curl -X POST https://your-app.herokuapp.com/api/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "profiles": [
      {"id": "123", "username": "test_user", "full_name": "Test User"}
    ]
  }'
```

### 6. Test Daily Pipeline

```bash
curl -X POST https://your-app.herokuapp.com/api/run-daily \
  -H "Content-Type: application/json" \
  -d '{
    "campaign_date": "2025-10-15",
    "profiles_per_table": 180
  }'
```

---

## 📊 Monitoring & Troubleshooting

### View Logs

```bash
# View all logs
heroku logs --tail

# View only web dyno logs
heroku logs --tail --dyno web

# View only worker logs
heroku logs --tail --dyno worker

# Search logs
heroku logs --tail | grep "ERROR"
```

### Check Dyno Status

```bash
# List running dynos
heroku ps

# Restart all dynos
heroku restart

# Restart specific dyno type
heroku restart worker
```

### Redis Queue Inspection

```bash
# Connect to Redis
heroku redis:cli

# Check queue length
> LLEN celery

# Monitor Redis
heroku redis:info
```

### Database Queries

Check job statuses:
```sql
-- Active jobs
SELECT job_id, status, progress, profiles_scraped, created_at
FROM scrape_jobs
WHERE status IN ('queued', 'processing')
ORDER BY created_at DESC;

-- Failed jobs
SELECT job_id, error_message, created_at
FROM scrape_jobs
WHERE status = 'failed'
ORDER BY created_at DESC
LIMIT 10;
```

### Performance Metrics

Monitor in Heroku Dashboard:
- **Response time** - Should be < 200ms for async endpoints
- **Throughput** - Requests per minute
- **Memory usage** - Should stay under dyno limits
- **Error rate** - Should be < 1%

### Common Issues

**Issue: Tasks not processing**
```bash
# Check worker dynos are running
heroku ps

# Check Redis connection
heroku config:get REDIS_URL

# Restart workers
heroku restart worker
```

**Issue: "Job not found" errors**
```bash
# Verify database tables exist
# Run migration again if needed
```

**Issue: Timeout errors**
```bash
# Increase gunicorn timeout
# Update Procfile: --timeout 300

# Scale up worker dynos
heroku ps:scale worker=8:standard-2x
```

**Issue: Memory errors**
```bash
# Reduce batch sizes in tasks.py
# Scale to larger dyno types
heroku ps:resize worker=standard-2x
```

---

## 📈 Scaling Guide

### For 500K Accounts/Batch

**Recommended Configuration:**
```bash
# Web dyno (API)
heroku ps:scale web=2:standard-1x

# Worker dynos (processing)
heroku ps:scale worker=8:standard-2x

# Redis (upgrade if needed)
heroku addons:upgrade heroku-redis:premium-0
```

**Cost Estimate:**
- Web (2x Standard-1X): $50/month
- Workers (8x Standard-2X): $400/month  
- Redis Premium-0: $15/month
- **Total: ~$465/month**

### Performance Targets

| Metric | Target | Actual |
|--------|--------|--------|
| API Response Time | < 200ms | Monitor |
| Job Queue Time | < 30s | Monitor |
| Batch Processing | 50 accounts/batch | Fixed |
| Database Batch Size | 1000 profiles/batch | Fixed |
| Total Processing Time | 3-8 hours for 500K | Test |

---

## 🔄 Continuous Deployment

### GitHub Actions (Optional)

Create `.github/workflows/deploy.yml`:

```yaml
name: Deploy to Heroku

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: akhileshns/heroku-deploy@v3.12.12
        with:
          heroku_api_key: ${{secrets.HEROKU_API_KEY}}
          heroku_app_name: "your-app-name"
          heroku_email: "your-email@example.com"
          appdir: "server"
```

---

## 📝 API Documentation

### Async Endpoints

**POST /api/scrape-followers**
- Queue scraping job
- Returns immediately with job_id
- Max 50 accounts per batch

**GET /api/job-status/:job_id**
- Check job progress
- Returns status, progress %, profiles count

**GET /api/job-results/:job_id**
- Get completed job results
- Supports pagination (page, limit)

**POST /api/ingest**
- Queue profile ingestion
- Batch size: 1000 profiles

**POST /api/run-daily**
- Queue daily pipeline
- Runs selection → distribution → sync

---

## 🎯 Success Checklist

- [ ] Heroku app created
- [ ] Redis addon installed
- [ ] All environment variables set
- [ ] Database migration applied
- [ ] Code deployed to Heroku
- [ ] Web dyno running (1x minimum)
- [ ] Worker dynos running (4x minimum)
- [ ] Health check returns 200
- [ ] Test scraping job completes
- [ ] Job status endpoint works
- [ ] Results returned correctly
- [ ] Logs show no errors
- [ ] Sentry reporting errors (if enabled)

---

## 📞 Support

**Logs:** `heroku logs --tail`  
**Status:** `heroku ps`  
**Config:** `heroku config`  
**Redis:** `heroku redis:info`

For issues, check:
1. Heroku logs for errors
2. Supabase logs for database issues
3. Sentry dashboard for exceptions
4. Redis queue length for backlogs
