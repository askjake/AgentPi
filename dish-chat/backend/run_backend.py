#!/usr/bin/env python3
"""
DishChat Intelligent Backend
Uses Coverity Assist for LLM responses
"""
import os
import sys
import json
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Load environment variables
from dotenv import load_dotenv
load_dotenv('/home/agentpi001/dish-chat/backend/.env')

# Coverity Assist Configuration
COVERITY_ASSIST_URL = os.getenv('COVERITY_ASSIST_URL', 'https://coverity-assist-stg.dishtv.technology/chat')
COVERITY_ASSIST_TOKEN = os.getenv('COVERITY_ASSIST_TOKEN', '')

def call_coverity_assist(messages):
    """Call Coverity Assist API for intelligent responses"""
    import requests
    
    try:
        # Prepare the request
        headers = {
            'Authorization': f'Bearer {COVERITY_ASSIST_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        # Convert messages to Coverity Assist format
        payload = {
            'messages': messages,
            'model': 'claude-sonnet-4',  # or whatever model is configured
            'temperature': 0.7
        }
        
        logger.info(f"Calling Coverity Assist: {COVERITY_ASSIST_URL}")
        
        # Make the request
        response = requests.post(
            COVERITY_ASSIST_URL,
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            # Extract the assistant's response
            if 'response' in data:
                return data['response']
            elif 'message' in data:
                return data['message']
            elif 'choices' in data and len(data['choices']) > 0:
                return data['choices'][0].get('message', {}).get('content', 'No response')
            else:
                return str(data)
        else:
            logger.error(f"Coverity Assist error: {response.status_code} - {response.text}")
            return f"I'm having trouble connecting to my AI brain. (Status: {response.status_code})"
            
    except requests.exceptions.Timeout:
        logger.error("Coverity Assist request timed out")
        return "I'm thinking too hard and timed out. Please try again!"
    except requests.exceptions.ConnectionError:
        logger.error("Cannot connect to Coverity Assist")
        return "I can't connect to my AI brain right now. Check if Coverity Assist is accessible."
    except Exception as e:
        logger.error(f"Error calling Coverity Assist: {e}")
        return f"Something went wrong: {str(e)}"

def get_simple_response(message):
    """Fallback responses if LLM is unavailable"""
    message_lower = message.lower()
    
    if 'hello' in message_lower or 'hi' in message_lower:
        return "Hello! I'm the DishChat agent running on agentpi001@172.16.235.90. How can I help you today?"
    elif 'help' in message_lower:
        return """I'm an AI assistant running on agentpi001@172.16.235.90. I can:
• Answer questions
• Have conversations
• Help with information
• Run commands (if configured)

Try asking me anything!"""
    elif 'status' in message_lower:
        return "I'm online and running on agentpi001@172.16.235.90. Backend is operational!"
    elif 'who are you' in message_lower or 'what are you' in message_lower:
        return "I'm an AI assistant powered by DishChat, running on agentpi001@172.16.235.90. I'm here to help you!"
    else:
        return f"I received your message: '{message}'. I'm running on agentpi001@172.16.235.90."

@app.route('/api/chat', methods=['POST', 'OPTIONS'])
def chat():
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        messages = data.get('messages', [])
        
        if not messages:
            return jsonify({"error": "No messages provided"}), 400
        
        # Get the last user message
        last_message = None
        for msg in reversed(messages):
            if msg.get('role') == 'user':
                last_message = msg.get('content', '')
                break
        
        if not last_message:
            return jsonify({"error": "No user message found"}), 400
        
        logger.info(f"User message: {last_message[:100]}")
        
        # Try to use Coverity Assist first
        if COVERITY_ASSIST_TOKEN:
            logger.info("Attempting Coverity Assist...")
            response_text = call_coverity_assist(messages)
        else:
            logger.warning("No Coverity Assist token, using simple responses")
            response_text = get_simple_response(last_message)
        
        # Return the response
        return jsonify({
            'response': response_text,
            'model': 'coverity-assist' if COVERITY_ASSIST_TOKEN else 'simple',
            'timestamp': datetime.now().isoformat(),
            'device': 'agentpi001@172.16.235.90'
        })
        
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}")
        return jsonify({
            'error': str(e),
            'response': "Sorry, I encountered an error processing your message."
        }), 500

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'service': 'intelligent-backend',
        'device': 'agentpi001@172.16.235.90',
        'coverity_assist': 'configured' if COVERITY_ASSIST_TOKEN else 'not configured',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/tools')
def tools():
    return jsonify({
        'tools': ['coverity-assist', 'chat'],
        'device': 'agentpi001@172.16.235.90'
    })

if __name__ == '__main__':
    logger.info("="*60)
    logger.info("Starting DishChat Intelligent Backend")
    logger.info(f"Device: agentpi001@172.16.235.90")
    logger.info(f"Coverity Assist: {'Configured' if COVERITY_ASSIST_TOKEN else 'Not configured'}")
    logger.info("="*60)
    app.run(host='0.0.0.0', port=8000, debug=False)
