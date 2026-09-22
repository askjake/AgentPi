#!/bin/bash
cd ~/dish-chat/frontend
nohup python3 server.py > ~/dish-chat/logs/frontend.log 2>&1 &
echo $! > ~/dish-chat/frontend.pid
echo "Frontend started (PID: $(cat ~/dish-chat/frontend.pid))"
