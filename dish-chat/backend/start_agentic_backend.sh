#!/bin/bash
# DishChat Agentic Backend Startup Script

cd /home/agentpi001/dish-chat/backend

# Load deployment-local credentials without committing them.
if [ -f .env ]; then
    set -a
    . ./.env
    set +a
fi

# Kill any existing backend processes
pkill -f "python3.*agentic_backend.py" || true
pkill -f "python3.*server.py" || true
sleep 2

# Export environment variables directly
export COVERITY_ASSIST_URL="https://coverity-assist-stg.dishtv.technology/chat"
: "${COVERITY_ASSIST_TOKEN:?COVERITY_ASSIST_TOKEN must be supplied in the environment}"
# Start the agentic backend
echo "Starting DishChat Agentic Backend..."
python3 agentic_backend.py > agentic_backend.log 2>&1 &
NEW_PID=$!

echo "Backend started with PID: $NEW_PID"
sleep 3

# Verify it's running
if ps -p $NEW_PID > /dev/null; then
    echo "✅ Backend is running on port 8000"
    tail -10 agentic_backend.log
else
    echo "❌ Backend failed to start"
    cat agentic_backend.log
    exit 1
fi
