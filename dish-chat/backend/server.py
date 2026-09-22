#!/usr/bin/env python3
"""
DishChat Backend with Real Coverity Assist Integration
"""
import sys
import os
import json
import logging
import requests
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Load environment variables
COVERITY_ASSIST_URL = os.getenv('COVERITY_ASSIST_URL', 'https://coverity-assist-stg.dishtv.technology/chat')
COVERITY_ASSIST_TOKEN = os.getenv('COVERITY_ASSIST_TOKEN', '')

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'service': 'intelligent-backend',
        'agent_tools': True,
        'tools_count': 0,
        'device': os.uname().nodename,
        'coverity_assist': 'configured',
        'coverity_url': COVERITY_ASSIST_URL,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/tools')
def list_tools():
    """List available agent tools"""
    return jsonify({
        'available': True,
        'count': 13,
        'tools': [
            'agent_git_clone', 'agent_create_venv', 'agent_run_python',
            'agent_list_artifacts', 'agent_run_shell', 'agent_network_scan',
            'agent_check_device', 'agent_save_device_info', 'agent_list_devices',
            'agent_docker_ps', 'agent_system_info', 'agent_mqtt_publish',
            'agent_wake_on_lan'
        ]
    })

@app.route('/api/chat', methods=['POST', 'OPTIONS'])
def chat():
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        messages = data.get('messages', [])
        
        if not messages:
            return jsonify({'error': 'No messages'}), 400
        
        # Get last user message
        last_msg = ""
        for msg in reversed(messages):
            if msg.get('role') == 'user':
                last_msg = msg.get('content', '')
                break
        
        logger.info(f"User message: {last_msg[:100]}")
        
        # Call Coverity Assist
        try:
            response = call_coverity_assist(messages)
            logger.info(f"Coverity response received: {len(response)} chars")
            
            return jsonify({
                'response': response,
                'model': 'coverity-assist',
                'device': os.uname().nodename,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Coverity Assist error: {e}")
            return jsonify({
                'response': f"❌ Error calling Coverity Assist: {str(e)}\n\nPlease check configuration.",
                'model': 'error',
                'device': os.uname().nodename,
                'timestamp': datetime.now().isoformat()
            })
        
    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({'error': str(e)}), 500

def call_coverity_assist(messages):
    """Call Coverity Assist API"""
    headers = {
        'Content-Type': 'application/json',
    }
    
    # Add auth token if available
    if COVERITY_ASSIST_TOKEN:
        headers['Authorization'] = f'Bearer {COVERITY_ASSIST_TOKEN}'
    
    payload = {
        'messages': messages
    }
    
    logger.info(f"Calling Coverity Assist: {COVERITY_ASSIST_URL}")
    
    try:
        response = requests.post(
            COVERITY_ASSIST_URL,
            headers=headers,
            json=payload,
            timeout=30
        )
        
        logger.info(f"Coverity response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            # Coverity Assist returns content/response/text field
            return data.get('content') or data.get('response') or data.get('text') or 'No response'
        else:
            error_msg = f"Coverity Assist returned status {response.status_code}"
            logger.error(error_msg)
            return f"❌ {error_msg}\n\nResponse: {response.text[:200]}"
            
    except requests.exceptions.Timeout:
        return "❌ Request to Coverity Assist timed out (30s)"
    except requests.exceptions.ConnectionError as e:
        return f"❌ Cannot connect to Coverity Assist: {str(e)}"
    except Exception as e:
        return f"❌ Error calling Coverity Assist: {str(e)}"

if __name__ == '__main__':
    logger.info("🚀 Starting DishChat Backend with Coverity Assist")
    logger.info(f"Coverity Assist URL: {COVERITY_ASSIST_URL}")
    logger.info(f"Token configured: {'Yes' if COVERITY_ASSIST_TOKEN else 'No'}")
    
    app.run(host='0.0.0.0', port=8000, debug=False)
