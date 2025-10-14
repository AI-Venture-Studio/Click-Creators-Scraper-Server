# 🧪 Testing Guide - Async Instagram Scraper API

## Quick Test Commands

### 1. Local Testing (Development)

**Start Services:**
```bash
# Terminal 1 - Flask API
cd server
source venv/bin/activate
python app.py

# Terminal 2 - Celery Worker
celery -A celery_config worker --loglevel=info --concurrency=2

# Terminal 3 - Test commands
```

**Test Health Check:**
```bash
curl http://localhost:5001/health
```

**Test Small Scraping Job (10 profiles):**
```bash
curl -X POST http://localhost:5001/api/scrape-followers \
  -H "Content-Type: application/json" \
  -d '{
    "accounts": ["nike", "adidas"],
    "targetGender": "male",
    "totalScrapeCount": 10
  }'
```

**Check Job Status:**
```bash
# Replace JOB_ID with actual ID from above response
curl http://localhost:5001/api/job-status/JOB_ID
```

**Get Results:**
```bash
curl http://localhost:5001/api/job-results/JOB_ID
```

---

### 2. Production Testing (Heroku)

**Test Health:**
```bash
curl https://your-app.herokuapp.com/health
```

**Test Async Scraping (100 profiles):**
```bash
curl -X POST https://your-app.herokuapp.com/api/scrape-followers \
  -H "Content-Type: application/json" \
  -d '{
    "accounts": ["nike", "adidas", "puma", "reebok"],
    "targetGender": "male",
    "totalScrapeCount": 100
  }'
```

**Monitor Progress:**
```bash
# Save job_id from above, then poll status
JOB_ID="your-job-id"

while true; do
  curl -s "https://your-app.herokuapp.com/api/job-status/$JOB_ID" | jq '.progress, .status'
  sleep 5
done
```

---

### 3. Scale Testing (500K profiles)

**Large Batch Test:**
```bash
# Read accounts from file (one per line)
ACCOUNTS=$(cat instagram_accounts.txt | jq -R . | jq -s .)

curl -X POST https://your-app.herokuapp.com/api/scrape-followers \
  -H "Content-Type: application/json" \
  -d "{
    \"accounts\": $ACCOUNTS,
    \"targetGender\": \"male\",
    \"totalScrapeCount\": 500000
  }"
```

**Monitor Workers:**
```bash
# Check worker status
heroku ps

# Monitor logs
heroku logs --tail --dyno worker

# Check Redis queue
heroku redis:cli
> LLEN celery
```

---

## Test Scenarios

### Scenario 1: End-to-End Scraping (10 accounts → 1000 profiles)

```bash
# 1. Submit job
RESPONSE=$(curl -s -X POST http://localhost:5001/api/scrape-followers \
  -H "Content-Type: application/json" \
  -d '{
    "accounts": ["nike","adidas","puma","reebok","underarmour","newbalance","asics","saucony","brooks","hoka"],
    "targetGender": "male",
    "totalScrapeCount": 1000
  }')

JOB_ID=$(echo $RESPONSE | jq -r '.job_id')
echo "Job ID: $JOB_ID"

# 2. Wait for completion (poll every 10 seconds)
while true; do
  STATUS=$(curl -s "http://localhost:5001/api/job-status/$JOB_ID" | jq -r '.status')
  echo "Status: $STATUS"
  
  if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ]; then
    break
  fi
  
  sleep 10
done

# 3. Get results
curl -s "http://localhost:5001/api/job-results/$JOB_ID?limit=100" | jq '.profiles | length'
```

### Scenario 2: Profile Ingestion (1000 profiles)

```bash
# Generate test profiles
PROFILES=$(for i in {1..1000}; do
  echo "{\"id\":\"$i\",\"username\":\"user_$i\",\"full_name\":\"User $i\"}"
done | jq -s .)

# Ingest
curl -X POST http://localhost:5001/api/ingest \
  -H "Content-Type: application/json" \
  -d "{\"profiles\": $PROFILES}"
```

### Scenario 3: Daily Pipeline

```bash
# Run full daily pipeline
curl -X POST http://localhost:5001/api/run-daily \
  -H "Content-Type: application/json" \
  -d '{
    "campaign_date": "2025-10-15",
    "profiles_per_table": 180
  }'

# Monitor task
TASK_ID=$(curl -s -X POST http://localhost:5001/api/run-daily \
  -H "Content-Type: application/json" \
  -d '{"profiles_per_table": 180}' | jq -r '.task_id')

echo "Task ID: $TASK_ID"

# Check logs for completion
heroku logs --tail | grep "$TASK_ID"
```

---

## Performance Benchmarks

### Expected Performance

| Test Case | Profiles | Expected Time | Memory |
|-----------|----------|---------------|--------|
| Small (10 profiles) | 10 | 10-30 sec | < 100 MB |
| Medium (1K profiles) | 1,000 | 2-5 min | < 300 MB |
| Large (10K profiles) | 10,000 | 15-30 min | < 500 MB |
| XL (100K profiles) | 100,000 | 2-4 hours | < 1 GB |
| XXL (500K profiles) | 500,000 | 5-10 hours | < 2 GB |

### Measure Performance

```bash
# Start time
START=$(date +%s)

# Submit job
JOB_ID=$(curl -s -X POST http://localhost:5001/api/scrape-followers \
  -H "Content-Type: application/json" \
  -d '{
    "accounts": ["nike","adidas"],
    "targetGender": "male",
    "totalScrapeCount": 100
  }' | jq -r '.job_id')

# Wait for completion
while true; do
  STATUS=$(curl -s "http://localhost:5001/api/job-status/$JOB_ID" | jq -r '.status')
  
  if [ "$STATUS" = "completed" ]; then
    END=$(date +%s)
    DURATION=$((END - START))
    echo "Completed in $DURATION seconds"
    
    # Get metrics
    curl -s "http://localhost:5001/api/job-status/$JOB_ID" | jq '{
      profiles_scraped,
      total_scraped,
      total_filtered,
      duration: '$DURATION'
    }'
    break
  fi
  
  sleep 5
done
```

---

## Database Validation

### Check Job Records

```sql
-- Recent jobs
SELECT 
  job_id,
  status,
  progress,
  profiles_scraped,
  total_batches,
  created_at,
  completed_at,
  EXTRACT(EPOCH FROM (completed_at - created_at)) as duration_seconds
FROM scrape_jobs
ORDER BY created_at DESC
LIMIT 10;

-- Job success rate
SELECT 
  status,
  COUNT(*) as count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) as percentage
FROM scrape_jobs
GROUP BY status;
```

### Check Results

```sql
-- Results count by job
SELECT 
  job_id,
  COUNT(*) as profile_count
FROM scrape_results
GROUP BY job_id
ORDER BY profile_count DESC
LIMIT 10;

-- Sample results
SELECT 
  profile_id,
  username,
  full_name
FROM scrape_results
WHERE job_id = 'YOUR_JOB_ID'
LIMIT 10;
```

---

## Error Testing

### Test Error Handling

**Invalid Request:**
```bash
curl -X POST http://localhost:5001/api/scrape-followers \
  -H "Content-Type: application/json" \
  -d '{}'

# Should return 400 Bad Request
```

**Invalid Job ID:**
```bash
curl http://localhost:5001/api/job-status/invalid-id

# Should return 404 Not Found
```

**Job Not Completed:**
```bash
# Submit job
JOB_ID=$(curl -s -X POST http://localhost:5001/api/scrape-followers \
  -H "Content-Type: application/json" \
  -d '{"accounts":["nike"],"totalScrapeCount":10}' | jq -r '.job_id')

# Try to get results immediately
curl http://localhost:5001/api/job-results/$JOB_ID

# Should return 400 with "Job is not completed yet"
```

---

## Load Testing

### Using Apache Bench

```bash
# Install ab
sudo apt-get install apache2-utils  # Ubuntu
brew install httpd  # macOS

# Test health endpoint (100 requests, 10 concurrent)
ab -n 100 -c 10 http://localhost:5001/health

# Test async endpoint with POST data
ab -n 50 -c 5 -p data.json -T application/json \
  http://localhost:5001/api/scrape-followers
```

**data.json:**
```json
{
  "accounts": ["nike"],
  "targetGender": "male",
  "totalScrapeCount": 10
}
```

### Using wrk

```bash
# Install wrk
brew install wrk  # macOS
sudo apt-get install wrk  # Ubuntu

# Load test
wrk -t4 -c100 -d30s http://localhost:5001/health
```

---

## Integration Tests

### Python Test Script

```python
#!/usr/bin/env python3
import requests
import time
import json

API_URL = "http://localhost:5001"

def test_async_scraping():
    """Test complete async scraping workflow"""
    
    # 1. Submit job
    print("1. Submitting job...")
    response = requests.post(f"{API_URL}/api/scrape-followers", json={
        "accounts": ["nike", "adidas"],
        "targetGender": "male",
        "totalScrapeCount": 20
    })
    assert response.status_code == 202
    
    job_id = response.json()["job_id"]
    print(f"   Job ID: {job_id}")
    
    # 2. Poll status
    print("2. Waiting for completion...")
    while True:
        status_response = requests.get(f"{API_URL}/api/job-status/{job_id}")
        assert status_response.status_code == 200
        
        data = status_response.json()
        print(f"   Status: {data['status']}, Progress: {data['progress']}%")
        
        if data["status"] == "completed":
            break
        elif data["status"] == "failed":
            print(f"   Error: {data['error_message']}")
            return False
        
        time.sleep(5)
    
    # 3. Get results
    print("3. Fetching results...")
    results_response = requests.get(f"{API_URL}/api/job-results/{job_id}")
    assert results_response.status_code == 200
    
    results = results_response.json()
    print(f"   Total profiles: {results['total']}")
    print(f"   Sample: {json.dumps(results['profiles'][:3], indent=2)}")
    
    print("✅ Test passed!")
    return True

if __name__ == "__main__":
    test_async_scraping()
```

---

## Monitoring Commands

### Check System Health

```bash
# Heroku
heroku ps
heroku logs --tail
heroku config

# Redis
heroku redis:info
heroku redis:cli
> INFO
> DBSIZE

# Database
# Run in Supabase SQL Editor
SELECT 
  (SELECT COUNT(*) FROM scrape_jobs WHERE status = 'processing') as active_jobs,
  (SELECT COUNT(*) FROM scrape_jobs WHERE status = 'queued') as queued_jobs,
  (SELECT COUNT(*) FROM scrape_results) as total_results;
```

---

## Cleanup Commands

### Clear Test Data

```sql
-- Delete test jobs (older than 1 hour)
DELETE FROM scrape_jobs
WHERE created_at < NOW() - INTERVAL '1 hour'
AND status IN ('completed', 'failed');

-- Results will be auto-deleted due to CASCADE
```

### Reset Redis Queue

```bash
heroku redis:cli
> FLUSHDB
```

---

## Success Criteria

- [ ] Health check returns 200
- [ ] Small job (10 profiles) completes in < 1 min
- [ ] Medium job (1K profiles) completes in < 5 min
- [ ] Large job (10K profiles) completes in < 30 min
- [ ] Job status updates in real-time
- [ ] Results retrievable with pagination
- [ ] Failed jobs show error messages
- [ ] Workers process batches in parallel
- [ ] No memory leaks (check `heroku ps`)
- [ ] Logs show no critical errors
