#!/bin/bash
cd ~/dish-chat/backend
source .venv/bin/activate
nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > ~/dish-chat/logs/backend.log 2>&1 &
echo $! > ~/dish-chat/backend.pid
echo "Backend started (PID: $(cat ~/dish-chat/backend.pid))"
