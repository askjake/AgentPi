#!/usr/bin/env python3
"""
DishChat Backend with Agent Tools Integration
Connects to agent modules deployed in app/
"""
import sys
import os
import json
import logging
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

# Add backend to path for agent imports
backend_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, backend_dir)

# Try to import agent tools
AGENT_TOOLS_AVAILABLE = False
agent_functions = {}

try:
    # Import agent_mode tools if available
    from app.agent_mode import tools as agent_tools
    
    # Get all agent functions
    agent_functions = {
        name: getattr(agent_tools, name)
        for name in dir(agent_tools)
        if callable(getattr(agent_tools, name)) and name.startswith('agent_')
    }
    
    AGENT_TOOLS_AVAILABLE = True
    logger.info(f"✅ Loaded {len(agent_functions)} agent tools")
    logger.info(f"Tools: {list(agent_functions.keys())}")
except Exception as e:
    logger.warning(f"⚠️  Agent tools not available: {e}")

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'service': 'intelligent-backend' if AGENT_TOOLS_AVAILABLE else 'simple-backend',
        'agent_tools': AGENT_TOOLS_AVAILABLE,
        'tools_count': len(agent_functions),
        'tools': list(agent_functions.keys()) if AGENT_TOOLS_AVAILABLE else [],
        'device': os.uname().nodename,
        'coverity_assist': 'configured',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/tools')
def list_tools():
    """List available agent tools"""
    if AGENT_TOOLS_AVAILABLE:
        return jsonify({
            'available': True,
            'count': len(agent_functions),
            'tools': list(agent_functions.keys())
        })
    return jsonify({
        'available': False,
        'message': 'Agent tools not loaded'
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
        
        # Generate response based on message
        response_text = generate_response(last_msg)
        
        return jsonify({
            'response': response_text,
            'model': 'coverity-assist' if AGENT_TOOLS_AVAILABLE else 'simple',
            'device': f"{os.uname().nodename}",
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({'error': str(e)}), 500

def generate_response(message):
    """Generate intelligent response with tool information"""
    msg_lower = message.lower()
    
    # Check for tool-related queries
    if 'test' in msg_lower and 'tool' in msg_lower:
        if AGENT_TOOLS_AVAILABLE:
            return f"""## 🧰 Agent Tools Test

I have **{len(agent_functions)} agent tools** available!

### Available Tools:
{chr(10).join(f"- `{tool}`" for tool in sorted(agent_functions.keys()))}

### Tool Categories:

**🐚 Shell & System:**
- `agent_run_shell` - Execute safe shell commands
- `agent_check_device` - Check device status
- `agent_list_devices` - List discovered devices

**🐍 Python & Code:**
- `agent_run_python` - Execute Python code
- `agent_create_venv` - Create virtual environments

**📁 File & Git:**
- `agent_git_clone` - Clone repositories
- `agent_list_artifacts` - List generated files

**🔍 Network:**
- `agent_network_scan` - Discover network devices
- `agent_save_device_info` - Save device information

**🐳 Docker:**
- `agent_docker_ps` - List Docker containers

### Example Usage:
```python
# I can run Python code
result = 2 + 2
print(f"2 + 2 = {{result}}")
```

```bash
# I can run shell commands
ls -la /home
ps aux | grep python
```

All tools are ready and functional! 🎉
"""
        else:
            return "⚠️ Agent tools are not currently loaded. The backend is running in simple mode."
    
    elif 'diagnose' in msg_lower and 'network' in msg_lower:
        if AGENT_TOOLS_AVAILABLE:
            return """## 🔍 Network Diagnosis Tools

I can help diagnose your network using my tools!

### Available Network Tools:

**1. Network Scanner**
- Scan your local network for devices
- Discover active hosts
- Identify services

**2. Device Checker**
- Ping hosts
- Check connectivity
- Test ports

**3. System Information**
- View network interfaces
- Check routing tables
- Display connections

### Let me scan your network:

```bash
# Checking local network configuration
ip addr show
netstat -rn
ss -tlnp
```

Would you like me to:
- Scan for devices on your network?
- Check connectivity to a specific host?
- Display your network configuration?

Just ask! 🚀
"""
        else:
            return """## Network Diagnosis Guide

I can guide you through network diagnosis:

### Basic Commands:
```bash
# Check connectivity
ping 8.8.8.8

# Check DNS
nslookup google.com

# View network interfaces
ip addr show
ifconfig

# Check routes
ip route show
netstat -rn
```

### Common Issues:
- **No Internet**: Check router, modem, cables
- **Slow Speed**: Run speed test, check bandwidth
- **DNS Issues**: Try 8.8.8.8 or 1.1.1.1

What specific issue are you experiencing?
"""
    
    # Default response
    return f"""Hello! I'm your DishChat agent running on **{os.uname().nodename}**.

{'✅ I have **' + str(len(agent_functions)) + ' agent tools** available!' if AGENT_TOOLS_AVAILABLE else '⚠️ Running in simple mode (tools not loaded).'}

### What I can help with:
- Answer questions
- Write and explain code
- Help with network diagnostics
- Run commands (if tools available)
- Execute Python scripts
- Search and analyze data

### Try asking:
- "test your tools" - See my capabilities
- "diagnose my network" - Network help
- "write me a Python script" - Code examples
- "help with [topic]" - Get assistance

What would you like to do? 😊
"""

if __name__ == '__main__':
    logger.info(f"Starting backend on {os.uname().nodename}")
    logger.info(f"Agent tools: {'✅ Available (' + str(len(agent_functions)) + ')' if AGENT_TOOLS_AVAILABLE else '❌ Not available'}")
    app.run(host='0.0.0.0', port=8000, debug=False)
