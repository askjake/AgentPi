#!/bin/bash
# Start Intelligent Backend

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Load environment
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Activate venv if exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

echo "🚀 Starting Intelligent Backend..."
python3 intelligent_backend.py
