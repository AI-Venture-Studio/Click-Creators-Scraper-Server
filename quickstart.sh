#!/bin/bash
# Quick Start Script for Local Development
# Run this to test the async Instagram Scraper API locally

set -e

echo "🚀 Instagram Scraper API - Local Quick Start"
echo "============================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check Python version
echo "📋 Checking prerequisites..."
python3 --version || {
    echo -e "${RED}❌ Python 3 not found. Please install Python 3.11+${NC}"
    exit 1
}

# Check Redis
if ! command -v redis-cli &> /dev/null; then
    echo -e "${YELLOW}⚠️  Redis not found. Installing...${NC}"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        brew install redis
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        sudo apt-get update && sudo apt-get install -y redis-server
    else
        echo -e "${RED}❌ Please install Redis manually${NC}"
        exit 1
    fi
fi

# Start Redis
echo "🔄 Starting Redis..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    brew services start redis
else
    sudo systemctl start redis
fi

# Check if Redis is running
redis-cli ping > /dev/null 2>&1 && echo -e "${GREEN}✅ Redis is running${NC}" || {
    echo -e "${RED}❌ Redis failed to start${NC}"
    exit 1
}

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "🔧 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "📦 Installing dependencies..."
pip install -r requirements.txt --quiet

# Check for .env file
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}⚠️  .env file not found. Creating from template...${NC}"
    cat > .env << 'EOF'
# Flask Configuration
FLASK_ENV=development
PORT=5001
SECRET_KEY=dev-secret-key-change-in-production
API_SECRET_KEY=dev-api-key-change-in-production
APP_VERSION=1.0.0

# Redis (Local)
REDIS_URL=redis://localhost:6379/0

# Supabase (REQUIRED - Update these!)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key

# Apify (REQUIRED - Update these!)
APIFY_API_KEY=your-apify-api-key

# Platform-specific Apify Actor IDs (for multi-platform support)
INSTAGRAM_APIFY_ACTOR_ID=your-instagram-actor-id
TIKTOK_APIFY_ACTOR_ID=your-tiktok-actor-id
THREADS_APIFY_ACTOR_ID=your-threads-actor-id
X_APIFY_ACTOR_ID=your-x-actor-id

# Airtable (REQUIRED - Update these!)
AIRTABLE_ACCESS_TOKEN=your-airtable-token
AIRTABLE_BASE_ID=your-base-id
NUM_VA_TABLES=80

# CORS
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5001

# Sentry (Optional)
# SENTRY_DSN=your-sentry-dsn
EOF
    echo -e "${YELLOW}⚠️  Please update .env with your credentials!${NC}"
    echo ""
    echo "Required variables:"
    echo "  - SUPABASE_URL"
    echo "  - SUPABASE_SERVICE_ROLE_KEY"
    echo "  - APIFY_API_KEY"
    echo "  - INSTAGRAM_APIFY_ACTOR_ID (Instagram scraping)"
    echo "  - TIKTOK_APIFY_ACTOR_ID (TikTok scraping - optional)"
    echo "  - THREADS_APIFY_ACTOR_ID (Threads scraping - optional)"
    echo "  - X_APIFY_ACTOR_ID (X/Twitter scraping - optional)"
    echo "  - AIRTABLE_ACCESS_TOKEN"
    echo "  - AIRTABLE_BASE_ID"
    echo ""
    read -p "Press Enter after updating .env..."
fi

# Check if database migration was applied
echo ""
echo "📊 Database Migration"
echo "===================="
echo "Have you applied the database migration (migrations/001_add_job_tracking.sql) in Supabase?"
echo ""
echo "If not, please:"
echo "1. Go to Supabase Dashboard → SQL Editor"
echo "2. Copy content from migrations/001_add_job_tracking.sql"
echo "3. Execute the SQL"
echo ""
read -p "Press Enter when migration is complete..."

# Create test script
cat > test_api.sh << 'EOF'
#!/bin/bash
# Test the API

echo "🧪 Testing API..."
echo ""

# Test health check
echo "1. Testing health check..."
curl -s http://localhost:5001/health | jq '.'

echo ""
echo "2. Testing async scraping (2 accounts, 10 profiles)..."
RESPONSE=$(curl -s -X POST http://localhost:5001/api/scrape-followers \
  -H "Content-Type: application/json" \
  -d '{
    "accounts": ["nike", "adidas"],
    "targetGender": "male",
    "totalScrapeCount": 10
  }')

echo "$RESPONSE" | jq '.'

JOB_ID=$(echo "$RESPONSE" | jq -r '.job_id')

if [ "$JOB_ID" != "null" ]; then
    echo ""
    echo "3. Job created! ID: $JOB_ID"
    echo "   Polling status every 5 seconds..."
    echo ""
    
    while true; do
        STATUS_RESPONSE=$(curl -s "http://localhost:5001/api/job-status/$JOB_ID")
        STATUS=$(echo "$STATUS_RESPONSE" | jq -r '.status')
        PROGRESS=$(echo "$STATUS_RESPONSE" | jq -r '.progress')
        
        echo "   Status: $STATUS | Progress: $PROGRESS%"
        
        if [ "$STATUS" = "completed" ]; then
            echo ""
            echo "✅ Job completed successfully!"
            echo ""
            echo "4. Fetching results..."
            curl -s "http://localhost:5001/api/job-results/$JOB_ID?limit=10" | jq '.profiles[] | {username, full_name}'
            break
        elif [ "$STATUS" = "failed" ]; then
            echo ""
            echo "❌ Job failed!"
            echo "$STATUS_RESPONSE" | jq '.error_message'
            break
        fi
        
        sleep 5
    done
else
    echo "❌ Failed to create job"
fi
EOF

chmod +x test_api.sh

# Instructions
echo ""
echo "✅ Setup complete!"
echo ""
echo "📝 Next steps:"
echo ""
echo "1️⃣  Start Flask API (Terminal 1):"
echo "   python app.py"
echo ""
echo "2️⃣  Start Celery Worker (Terminal 2):"
echo "   celery -A celery_config worker --loglevel=info --concurrency=2"
echo ""
echo "3️⃣  Test the API (Terminal 3):"
echo "   ./test_api.sh"
echo ""
echo "OR start everything at once:"
echo ""
echo "Option A - Using tmux (recommended):"
echo "   ./start_all.sh"
echo ""
echo "Option B - Manual in separate terminals:"
echo "   Terminal 1: python app.py"
echo "   Terminal 2: celery -A celery_config worker --loglevel=info"
echo "   Terminal 3: ./test_api.sh"
echo ""

# Create start_all.sh script
cat > start_all.sh << 'EOF'
#!/bin/bash
# Start all services in tmux

if ! command -v tmux &> /dev/null; then
    echo "tmux not found. Installing..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        brew install tmux
    else
        sudo apt-get install -y tmux
    fi
fi

# Create new tmux session
tmux new-session -d -s instagram_api

# Split window
tmux split-window -h
tmux select-pane -t 0
tmux split-window -v

# Activate venv in all panes
tmux send-keys -t 0 "source venv/bin/activate" C-m
tmux send-keys -t 1 "source venv/bin/activate" C-m
tmux send-keys -t 2 "source venv/bin/activate" C-m

# Start Flask API in pane 0
tmux send-keys -t 0 "python app.py" C-m

# Start Celery worker in pane 1
tmux send-keys -t 1 "celery -A celery_config worker --loglevel=info --concurrency=2" C-m

# Wait for services to start
sleep 3

# Run test in pane 2
tmux send-keys -t 2 "./test_api.sh" C-m

# Attach to session
tmux attach-session -t instagram_api
EOF

chmod +x start_all.sh

echo "🎉 Ready to go!"
echo ""
echo "Run: ./start_all.sh"
