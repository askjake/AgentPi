#!/usr/bin/env python3
"""
DishChat Agentic Backend - Proper Tool Integration
This backend connects to the actual agent (Claude/Assistant) with real tool calling
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

# Agent tool definitions matching frontend expectations
TOOL_DEFINITIONS = {
    'internal_search': {
        'description': 'Search internal DISH documentation',
        'parameters': ['query', 'top_k'],
        'endpoint': '/internal-search'
    },
    'public_web_search': {
        'description': 'Search public web',
        'parameters': ['query', 'max_results'],
        'endpoint': '/web-search'
    },
    'netra_search': {
        'description': 'Search Netra logs',
        'parameters': ['rec_id', 'search_date', 'query'],
        'endpoint': '/netra'
    },
    'cluster_inspect': {
        'description': 'Inspect Kubernetes cluster (read-only)',
        'parameters': ['task'],
        'endpoint': '/cluster'
    },
    'dish_internal_tool': {
        'description': 'Access DISH internal tools (CART, CCTools, Portal)',
        'parameters': ['service', 'endpoint', 'method'],
        'endpoint': '/dish-internal'
    },
    'agent_run_python': {
        'description': 'Execute Python code',
        'parameters': ['chat_id', 'code', 'filename'],
        'endpoint': '/run-python'
    },
    'agent_run_shell': {
        'description': 'Execute shell commands (secured)',
        'parameters': ['command'],
        'endpoint': '/run-shell'
    },
    'query_viewership': {
        'description': 'Query viewership data',
        'parameters': ['fromEpochTimeUtc', 'toEpochTimeUtc', 'serviceUids', 'viewingType'],
        'endpoint': '/viewership'
    },
    'get_popular_services': {
        'description': 'Get top services by viewership',
        'parameters': ['viewingType', 'fromEpochTimeUtc', 'toEpochTimeUtc', 'limit'],
        'endpoint': '/popular-services'
    }
}

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'service': 'agentic-backend',
        'agent_tools': True,
        'tools_count': len(TOOL_DEFINITIONS),
        'tools': list(TOOL_DEFINITIONS.keys()),
        'device': os.uname().nodename,
        'coverity_assist': 'configured',
        'coverity_url': COVERITY_ASSIST_URL,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/tools', methods=['GET'])
def list_tools():
    """List available agent tools with full definitions"""
    tools_list = []
    for name, definition in TOOL_DEFINITIONS.items():
        tools_list.append({
            'name': name,
            'description': definition['description'],
            'parameters': definition['parameters']
        })
    
    return jsonify({
        'available': True,
        'count': len(TOOL_DEFINITIONS),
        'tools': list(TOOL_DEFINITIONS.keys()),
        'definitions': tools_list
    })

@app.route('/api/tools/<tool_name>', methods=['POST', 'OPTIONS'])
def execute_tool(tool_name):
    """Execute a specific tool directly"""
    if request.method == 'OPTIONS':
        return '', 200
    
    if tool_name not in TOOL_DEFINITIONS:
        return jsonify({
            'error': f'Tool {tool_name} not found',
            'available_tools': list(TOOL_DEFINITIONS.keys())
        }), 404
    
    try:
        params = request.get_json() or {}
        logger.info(f"Executing tool: {tool_name} with params: {params}")
        
        # For testing, we'll simulate tool execution or call Coverity Assist
        # In production, this would call the actual tool implementation
        
        result = execute_tool_via_coverity(tool_name, params)
        
        return jsonify({
            'success': True,
            'tool': tool_name,
            'parameters': params,
            'result': result,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Tool execution error: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'tool': tool_name
        }), 500

@app.route('/api/chat', methods=['POST', 'OPTIONS'])
def chat():
    """Main chat endpoint with agent tool calling"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        messages = data.get('messages', [])
        reasoning_mode = data.get('reasoning_mode', False)
        attachments = data.get('attachments', [])
        chat_id = data.get('chat_id', f'chat_{int(datetime.now().timestamp())}')
        
        if not messages:
            return jsonify({'error': 'No messages provided'}), 400
        
        # Get last user message
        last_msg = ""
        for msg in reversed(messages):
            if msg.get('role') == 'user':
                last_msg = msg.get('content', '')
                break
        
        logger.info(f"Chat request - ID: {chat_id}, Reasoning: {reasoning_mode}, Message: {last_msg[:100]}")
        
        # Call Coverity Assist (which has tool access)
        try:
            response_data = call_coverity_assist_with_tools(
                messages=messages,
                reasoning_mode=reasoning_mode,
                attachments=attachments
            )
            
            return jsonify({
                'response': response_data.get('response', 'No response'),
                'reasoning': response_data.get('reasoning') if reasoning_mode else None,
                'tool_calls': response_data.get('tool_calls', []),
                'artifacts': response_data.get('artifacts', []),
                'model': 'coverity-assist-agentic',
                'chat_id': chat_id,
                'device': os.uname().nodename,
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Coverity Assist error: {e}")
            return jsonify({
                'response': f"❌ Error calling agent: {str(e)}\n\nBackend is configured but agent may be unavailable.",
                'model': 'error',
                'timestamp': datetime.now().isoformat()
            }), 500
        
    except Exception as e:
        logger.error(f"Chat endpoint error: {e}")
        return jsonify({'error': str(e)}), 500

def execute_tool_via_coverity(tool_name, params):
    """Execute tool by asking Coverity Assist to use it"""
    
    # Create a message that instructs the agent to use the specific tool
    instruction = f"Please use the {tool_name} tool with these exact parameters: {json.dumps(params)}. Execute the tool and return ONLY the tool result, no additional explanation."
    
    messages = [
        {
            'role': 'user',
            'content': instruction
        }
    ]
    
    try:
        response = call_coverity_assist_with_tools(messages)
        return response.get('response', 'Tool executed but no result returned')
    except Exception as e:
        logger.error(f"Tool execution via Coverity failed: {e}")
        return {
            'error': str(e),
            'tool': tool_name,
            'message': 'Tool execution failed. Agent may not be available.'
        }

def call_coverity_assist_with_tools(messages, reasoning_mode=False, attachments=None):
    """Call Coverity Assist API with tool support"""
    
    headers = {
        'Content-Type': 'application/json',
    }
    
    if COVERITY_ASSIST_TOKEN:
        headers['Authorization'] = f'Bearer {COVERITY_ASSIST_TOKEN}'
    
    # Build system message with tool context
    system_context = """You are an intelligent DISH Chat Agent with access to multiple tools.

Available Tools:
- internal_search: Search DISH internal documentation
- public_web_search: Search public web for current information
- netra_search: Search Netra logs and records
- cluster_inspect: Inspect Kubernetes cluster (read-only operations)
- dish_internal_tool: Access CART, CCTools, Portal
- agent_run_python: Execute Python code
- agent_run_shell: Execute shell commands (secured)
- query_viewership: Query viewership data
- get_popular_services: Get top services by viewership

When the user asks a question that requires information or actions, USE the appropriate tools.
Always explain what tools you're using and why."""

    if reasoning_mode:
        system_context += "\n\nREASONING MODE ENABLED: Explain your thinking process before responding."
    
    # Prepare payload
    enhanced_messages = [
        {'role': 'system', 'content': system_context}
    ] + messages
    
    # Add attachment context if any
    if attachments:
        attachment_context = "\n\nAttached files:\n"
        for att in attachments:
            attachment_context += f"- {att.get('name', 'unknown')} ({att.get('type', 'unknown')})\n"
            if att.get('content'):
                attachment_context += f"Content preview:\n{att['content'][:500]}...\n"
        
        # Add to last user message
        if enhanced_messages[-1]['role'] == 'user':
            enhanced_messages[-1]['content'] += attachment_context
    
    payload = {
        'messages': enhanced_messages
    }
    
    logger.info(f"Calling Coverity Assist: {COVERITY_ASSIST_URL}")
    
    try:
        response = requests.post(
            COVERITY_ASSIST_URL,
            headers=headers,
            json=payload,
            timeout=60  # Longer timeout for tool execution
        )
        
        logger.info(f"Coverity response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            # Extract response text
            response_text = data.get('content') or data.get('response') or data.get('text') or 'No response'
            
            # Try to parse tool calls from response
            tool_calls = extract_tool_calls_from_response(response_text, data)
            
            result = {
                'response': response_text,
                'tool_calls': tool_calls,
                'reasoning': data.get('reasoning') if reasoning_mode else None,
                'artifacts': data.get('artifacts', [])
            }
            
            return result
        else:
            error_msg = f"Coverity Assist returned status {response.status_code}"
            logger.error(error_msg)
            return {
                'response': f"❌ {error_msg}\n\nResponse: {response.text[:200]}",
                'tool_calls': []
            }
            
    except requests.exceptions.Timeout:
        return {
            'response': "❌ Request timed out after 60 seconds. The agent may be processing tools.",
            'tool_calls': []
        }
    except requests.exceptions.ConnectionError as e:
        return {
            'response': f"❌ Cannot connect to agent: {str(e)}",
            'tool_calls': []
        }
    except Exception as e:
        return {
            'response': f"❌ Error calling agent: {str(e)}",
            'tool_calls': []
        }

def extract_tool_calls_from_response(response_text, response_data):
    """Try to extract tool call information from the response"""
    tool_calls = []
    
    # Check if response data has tool_calls field
    if 'tool_calls' in response_data:
        return response_data['tool_calls']
    
    # Try to parse from response text
    # Look for patterns like "Using tool: internal_search"
    for tool_name in TOOL_DEFINITIONS.keys():
        if tool_name in response_text.lower():
            tool_calls.append({
                'name': tool_name,
                'parameters': {},
                'status': 'detected'
            })
    
    return tool_calls

@app.route('/api/transcribe', methods=['POST', 'OPTIONS'])
def transcribe_audio():
    """Transcribe audio to text (placeholder for now)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    # This would integrate with a speech-to-text service
    return jsonify({
        'transcript': 'Voice transcription not yet implemented',
        'message': 'This feature requires speech-to-text integration'
    })

@app.route('/api/artifacts/<artifact_id>', methods=['GET'])
def download_artifact(artifact_id):
    """Download generated artifact"""
    # This would retrieve artifacts from storage
    return jsonify({
        'error': 'Artifact download not yet implemented',
        'artifact_id': artifact_id
    }), 501

if __name__ == '__main__':
    logger.info("=" * 80)
    logger.info("🚀 Starting DishChat Agentic Backend")
    logger.info("=" * 80)
    logger.info(f"Coverity Assist URL: {COVERITY_ASSIST_URL}")
    logger.info(f"Token configured: {'Yes' if COVERITY_ASSIST_TOKEN else 'No'}")
    logger.info(f"Tools available: {len(TOOL_DEFINITIONS)}")
    logger.info(f"Tools: {', '.join(TOOL_DEFINITIONS.keys())}")
    logger.info("=" * 80)
    
    app.run(host='0.0.0.0', port=8000, debug=False)
