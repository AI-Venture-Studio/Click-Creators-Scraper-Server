# 🚀 Render Deployment Guide - AIVS Instagram Scraper

## Prerequisites
✅ Code pushed to GitHub: https://github.com/AmoKorankye/AIVS-Instagram-Scraper-Server
✅ render.yaml configuration file created
✅ All dependencies listed in requirements.txt

---

## 📋 Step-by-Step Deployment Instructions

### Step 1: Create Render Account & Connect GitHub

1. **Go to Render**: https://render.com
2. **Sign up or log in** using your GitHub account
3. **Authorize Render** to access your GitHub repositories

### Step 2: Create New Blueprint Instance

1. **Click "New +"** in the top right
2. **Select "Blueprint"** from the dropdown
3. **Connect Repository**:
   - Repository: `AmoKorankye/AIVS-Instagram-Scraper-Server`
   - Branch: `main`
4. **Name the Blueprint**: `aivs-instagram-scraper`
5. **Click "Apply"**

Render will automatically detect `render.yaml` and create:
- ✅ **Redis service** (`aivs-redis`) - Free tier
- ✅ **Web service** (`aivs-instagram-scraper-api`) - Free tier
  - Runs both Flask API and Celery worker in the same container

**Note:** To stay within Render's free tier (1 free web service per account), we run the Celery worker alongside the Flask app in the same service.

### Step 3: Configure Environment Variables

After the services are created, you need to manually set environment variables:

#### For the Web Service:

1. Go to the web service in Render dashboard
2. Click **"Environment"** tab
3. Add these environment variables:

```bash
# Supabase (Database)
SUPABASE_URL=<your-supabase-url>
SUPABASE_SERVICE_ROLE_KEY=<your-supabase-service-role-key>

# Apify (Instagram Scraper)
APIFY_API_KEY=<your-apify-api-key>
APIFY_ACTOR_ID=<your-apify-actor-id>

# Airtable (VA Management)
AIRTABLE_ACCESS_TOKEN=<your-airtable-access-token>
AIRTABLE_BASE_ID=<your-airtable-base-id>

# Optional: Sentry (Error Tracking)
SENTRY_DSN=<your-sentry-dsn-if-you-have-one>
```

**💡 Get the actual values from your `.env` file:**
```bash
# Copy from /server/.env file
```

4. **Click "Save Changes"**
5. Service will automatically redeploy with new environment variables

### Step 4: Wait for Deployment

Monitor the deployment logs:
- **Redis**: Should be ready in ~30 seconds
- **Web Service**: Should build and deploy in ~2-3 minutes
  - This service runs both Flask API and Celery worker

### Step 5: Verify Deployment

Once all services show **"Live"** status:

1. **Test the API health endpoint**:
```bash
curl https://aivs-instagram-scraper-api.onrender.com/healthz
# Should return: "ok"
```

2. **Test async scraping endpoint**:
```bash
curl -X POST https://aivs-instagram-scraper-api.onrender.com/api/scrape-followers \
  -H "Content-Type: application/json" \
  -d '{
    "accounts": ["testaccount"],
    "targetGender": "male",
    "totalScrapeCount": 10
  }'
```

Should return a JSON response with `job_id` and status URLs.

3. **Check logs**:
   - Web service logs: Should show both Flask requests AND Celery worker messages
   - Look for: `celery@... ready` to confirm worker is running
   - Redis logs: Should show connections from the web service

---

## 🔍 Troubleshooting

### Issue: Services won't start
**Solution**: Check environment variables are set correctly in BOTH services

### Issue: Worker can't connect to Redis
**Solution**: Verify `REDIS_URL` is automatically populated from Redis service

### Issue: API returns 500 errors
**Solution**: Check web service logs for Python errors, verify all env vars are set

### Issue: Tasks not processing
**Solution**: Check worker service logs, ensure it's running and connected to Redis

---

## 📊 Service URLs (After Deployment)

- **API Base URL**: `https://aivs-instagram-scraper-api.onrender.com`
- **Health Check**: `https://aivs-instagram-scraper-api.onrender.com/healthz`
- **Async Endpoints**:
  - POST `/api/scrape-followers` - Queue scraping job
  - GET `/api/job-status/:job_id` - Check job status
  - GET `/api/job-results/:job_id` - Get results
  - POST `/api/ingest` - Queue profile ingestion
  - POST `/api/run-daily` - Queue daily pipeline

---

## 🎯 Next Steps After Deployment

1. **Update your frontend** to use the new API URL
2. **Set up monitoring** using Render's built-in metrics
3. **Configure custom domain** (optional, paid feature)
4. **Set up Sentry** for error tracking (optional)
5. **Schedule daily pipeline** using Render Cron Jobs or external scheduler

---

## 💰 Cost Breakdown

**100% FREE with Render Free Tier:**
- **Redis (Free)**: 25 MB storage, sufficient for task queue
- **Web Service (Free)**: 512 MB RAM, runs both Flask API + Celery worker
  - Spins down after 15 min inactivity
  - Cold starts take ~30 seconds

**Upgrade to Paid** ($7/month) for:
- Always-on service (no cold starts)
- 2 GB RAM (better for heavy workloads)
- Custom domains
- Priority support

---

## 📝 Important Notes

1. **Free tier sleeps**: Service spins down after 15 min of inactivity. First request after sleep takes ~30 seconds.
2. **Database migration**: Already applied locally. Tables exist in Supabase.
3. **Combined service**: Flask API and Celery worker run in the same container to stay within free tier limits.
4. **Async jobs**: Background worker handles all Celery tasks automatically.
5. **Scaling**: Can upgrade to paid plan for always-on service and better performance.

---

## ✅ Deployment Checklist

- [x] Code pushed to GitHub
- [x] render.yaml created and pushed
- [ ] Render account created and connected to GitHub
- [ ] Blueprint deployed from render.yaml
- [ ] Environment variables set in web service
- [ ] Health check endpoint returns "ok"
- [ ] Async endpoint test successful
- [ ] Web service logs show both Flask AND Celery worker running
- [ ] Frontend updated with new API URL

---

**🎉 Once all checkboxes are complete, your Instagram scraper is LIVE and ready to handle 500K+ accounts per batch!**
