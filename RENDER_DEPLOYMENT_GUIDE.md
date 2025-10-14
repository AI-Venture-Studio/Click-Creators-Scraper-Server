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
- ✅ **Worker service** (`aivs-celery-worker`) - Free tier

### Step 3: Configure Environment Variables

After the services are created, you need to manually set environment variables:

#### For BOTH Web Service AND Worker Service:

1. Go to each service in Render dashboard
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
5. Services will automatically redeploy with new environment variables

### Step 4: Wait for Deployment

Monitor the deployment logs:
- **Redis**: Should be ready in ~30 seconds
- **Web Service**: Should build and deploy in ~2-3 minutes
- **Worker Service**: Should build and deploy in ~2-3 minutes

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
   - Web service logs: Should show Flask requests
   - Worker service logs: Should show Celery worker ready and processing tasks
   - Redis logs: Should show connections from web and worker

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

- **Redis (Free)**: 25 MB storage, good for task queue
- **Web Service (Free)**: Spins down after 15 min inactivity, cold starts ~30s
- **Worker Service (Free)**: Spins down after 15 min inactivity

**Upgrade to Paid** ($7/month each) for:
- Always-on services (no cold starts)
- More memory and CPU
- Custom domains
- Priority support

---

## 📝 Important Notes

1. **Free tier sleeps**: Services spin down after 15 min of inactivity. First request after sleep takes ~30 seconds.
2. **Database migration**: Already applied locally. Tables exist in Supabase.
3. **Async jobs**: Background worker handles all Celery tasks automatically.
4. **Scaling**: Can upgrade individual services to paid plans as needed.

---

## ✅ Deployment Checklist

- [x] Code pushed to GitHub
- [x] render.yaml created and pushed
- [ ] Render account created and connected to GitHub
- [ ] Blueprint deployed from render.yaml
- [ ] Environment variables set in web service
- [ ] Environment variables set in worker service
- [ ] Health check endpoint returns "ok"
- [ ] Async endpoint test successful
- [ ] Worker logs show Celery ready
- [ ] Frontend updated with new API URL

---

**🎉 Once all checkboxes are complete, your Instagram scraper is LIVE and ready to handle 500K+ accounts per batch!**
