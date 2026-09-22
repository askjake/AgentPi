#!/usr/bin/env python3
"""Test the visualization by sending HTTP POST requests"""

import requests
import time
from datetime import datetime

# URL of your viz server
VIZ_URL = "http://localhost:5001/api/event"

def send_event(event):
    """Send an event to the viz server"""
    try:
        response = requests.post(VIZ_URL, json=event, timeout=1)
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

print("=" * 70)
print("Testing visualization server at", VIZ_URL)
print("Make sure the viz server is running!")
print("=" * 70)
print()

# Test 1: Thought
print("1. Sending thought...")
send_event({
    "type": "thought",
    "category": "thinking",
    "text": "Hello! This is a test thought from the test script",
    "timestamp": datetime.now().isoformat()
})
time.sleep(1)

# Test 2: Tool call
print("2. Sending tool call...")
send_event({
    "type": "tool",
    "tool": "test_tool",
    "params": {"param1": "value1"},
    "result": "Success!",
    "timestamp": datetime.now().isoformat()
})
time.sleep(1)

# Test 3: Decision
print("3. Sending decision...")
send_event({
    "type": "decision",
    "text": "Should I do A or B?",
    "options": ["Option A", "Option B"],
    "timestamp": datetime.now().isoformat()
})
time.sleep(1)

# Test 4: Context
print("4. Sending context update...")
send_event({
    "type": "context",
    "key": "test_status",
    "value": "running",
    "timestamp": datetime.now().isoformat()
})
time.sleep(1)

# Test 5: Metrics
print("5. Sending metrics...")
send_event({
    "type": "metric",
    "metric": "tokens",
    "value": 100,
    "timestamp": datetime.now().isoformat()
})
time.sleep(0.5)

send_event({
    "type": "metric",
    "metric": "tools",
    "value": 1,
    "timestamp": datetime.now().isoformat()
})
time.sleep(0.5)

# Test 6: Sequence of thoughts
print("6. Sending thought sequence...")
for i in range(5):
    send_event({
        "type": "thought",
        "category": "thinking",
        "text": f"Processing step {i+1} of 5...",
        "timestamp": datetime.now().isoformat()
    })
    print(f"   Sent thought {i+1}/5")
    time.sleep(0.5)

print()
print("=" * 70)
print("✅ Test complete!")
print("Check your browser at http://localhost:5001")
print("You should see:")
print("  • Green nodes in the graph")
print("  • Events in the log")
print("  • Context showing 'test_status: running'")
print("  • Metrics showing 100 tokens, 1 tool")
print("=" * 70)

