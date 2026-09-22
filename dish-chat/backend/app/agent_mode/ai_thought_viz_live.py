#!/usr/bin/env python3
"""
AI Thought Visualization - LIVE MODE
Captures and displays REAL agent reasoning in real-time
"""

from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO, emit
import threading
import time
import json
import queue
from datetime import datetime
import sys
import traceback

app = Flask(__name__)
app.config['SECRET_KEY'] = 'ai-thought-viz-live'
socketio = SocketIO(app, cors_allowed_origins="*")

# Global state for capturing live events
live_events = queue.Queue()
thought_graph = {"nodes": [], "links": []}
context_memory = {}
tool_timeline = []
metrics = {"tokens": 0, "tools": 0, "time": 0}
node_counter = 0

# Interceptor class that can be imported by the agent
class ThoughtInterceptor:
    """
    Import this in your agent code to capture live thoughts:
    
    from ai_thought_viz_live import interceptor
    
    # In your agent code:
    interceptor.thought("Analyzing the problem...")
    interceptor.tool_call("web_search", {"query": "..."})
    interceptor.decision("Using approach A because...")
    """
    
    def __init__(self):
        self.enabled = True
        self.start_time = time.time()
    
    def thought(self, text, category="thinking"):
        """Capture a reasoning step"""
        if not self.enabled:
            return
        
        event = {
            "type": "thought",
            "category": category,
            "text": text,
            "timestamp": datetime.now().isoformat(),
            "elapsed": time.time() - self.start_time
        }
        live_events.put(event)
    
    def tool_call(self, tool_name, params=None, result=None):
        """Capture a tool execution"""
        if not self.enabled:
            return
        
        event = {
            "type": "tool",
            "tool": tool_name,
            "params": params or {},
            "result": result,
            "timestamp": datetime.now().isoformat(),
            "elapsed": time.time() - self.start_time
        }
        live_events.put(event)
    
    def decision(self, text, options=None):
        """Capture a decision point"""
        if not self.enabled:
            return
        
        event = {
            "type": "decision",
            "text": text,
            "options": options or [],
            "timestamp": datetime.now().isoformat(),
            "elapsed": time.time() - self.start_time
        }
        live_events.put(event)
    
    def context_update(self, key, value):
        """Update context memory"""
        if not self.enabled:
            return
        
        event = {
            "type": "context",
            "key": key,
            "value": value,
            "timestamp": datetime.now().isoformat()
        }
        live_events.put(event)
    
    def metric_update(self, metric_type, value):
        """Update performance metrics"""
        if not self.enabled:
            return
        
        event = {
            "type": "metric",
            "metric": metric_type,
            "value": value,
            "timestamp": datetime.now().isoformat()
        }
        live_events.put(event)

# Global interceptor instance
interceptor = ThoughtInterceptor()

def process_events():
    """Background thread to process events and broadcast to clients"""
    global node_counter
    
    while True:
        try:
            event = live_events.get(timeout=0.1)
            
            if event["type"] == "thought":
                # Add node to graph
                node_counter += 1
                node = {
                    "id": node_counter,
                    "label": event["text"][:50] + "..." if len(event["text"]) > 50 else event["text"],
                    "category": event["category"],
                    "timestamp": event["timestamp"],
                    "full_text": event["text"]
                }
                thought_graph["nodes"].append(node)
                
                # Link to previous node
                if len(thought_graph["nodes"]) > 1:
                    thought_graph["links"].append({
                        "source": node_counter - 1,
                        "target": node_counter
                    })
                
                socketio.emit('graph_update', thought_graph)
                socketio.emit('event_log', {
                    "timestamp": event["timestamp"],
                    "type": "thought",
                    "message": event["text"]
                })
            
            elif event["type"] == "tool":
                # Add to timeline
                tool_timeline.append({
                    "tool": event["tool"],
                    "timestamp": event["timestamp"],
                    "params": event["params"],
                    "result": event.get("result")
                })
                
                metrics["tools"] += 1
                
                socketio.emit('timeline_update', tool_timeline[-10:])  # Last 10
                socketio.emit('event_log', {
                    "timestamp": event["timestamp"],
                    "type": "tool",
                    "message": f"🔧 {event['tool']}"
                })
                socketio.emit('metrics_update', metrics)
            
            elif event["type"] == "decision":
                node_counter += 1
                node = {
                    "id": node_counter,
                    "label": "Decision: " + event["text"][:40],
                    "category": "decision",
                    "timestamp": event["timestamp"],
                    "full_text": event["text"],
                    "options": event["options"]
                }
                thought_graph["nodes"].append(node)
                
                if len(thought_graph["nodes"]) > 1:
                    thought_graph["links"].append({
                        "source": node_counter - 1,
                        "target": node_counter
                    })
                
                socketio.emit('graph_update', thought_graph)
                socketio.emit('event_log', {
                    "timestamp": event["timestamp"],
                    "type": "decision",
                    "message": f"⚖️  {event['text']}"
                })
            
            elif event["type"] == "context":
                context_memory[event["key"]] = event["value"]
                socketio.emit('context_update', context_memory)
            
            elif event["type"] == "metric":
                metrics[event["metric"]] = event["value"]
                socketio.emit('metrics_update', metrics)
        
        except queue.Empty:
            continue
        except Exception as e:
            print(f"Error processing event: {e}", file=sys.stderr)
            traceback.print_exc()

# HTML template with live updates
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>AI Thought Visualization - LIVE</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Courier New', monospace;
            background: linear-gradient(135deg, #0a0a0a 0%, #1a0a2e 100%);
            color: #00ff00;
            overflow: hidden;
        }
        
        .header {
            background: rgba(255, 0, 255, 0.1);
            border-bottom: 2px solid #ff00ff;
            padding: 15px;
            text-align: center;
            box-shadow: 0 0 20px rgba(255, 0, 255, 0.5);
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { box-shadow: 0 0 20px rgba(255, 0, 255, 0.5); }
            50% { box-shadow: 0 0 40px rgba(255, 0, 255, 0.8); }
        }
        
        h1 {
            color: #ff00ff;
            text-shadow: 0 0 10px #ff00ff;
            font-size: 2em;
            letter-spacing: 3px;
        }
        
        .status {
            color: #00ff00;
            font-size: 0.9em;
            margin-top: 5px;
            animation: blink 1s infinite;
        }
        
        @keyframes blink {
            0%, 50%, 100% { opacity: 1; }
            25%, 75% { opacity: 0.5; }
        }
        
        .container {
            display: grid;
            grid-template-columns: 2fr 1fr;
            grid-template-rows: 1fr 1fr;
            gap: 10px;
            padding: 10px;
            height: calc(100vh - 100px);
        }
        
        .panel {
            background: rgba(0, 0, 0, 0.7);
            border: 1px solid #00ff00;
            border-radius: 5px;
            padding: 15px;
            overflow: auto;
            box-shadow: 0 0 15px rgba(0, 255, 0, 0.3);
        }
        
        .panel h2 {
            color: #00ffff;
            border-bottom: 1px solid #00ffff;
            padding-bottom: 5px;
            margin-bottom: 10px;
            font-size: 1.2em;
        }
        
        #graph { grid-row: 1 / 3; }
        
        #graph svg {
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.5);
            border-radius: 5px;
        }
        
        .node circle {
            stroke: #fff;
            stroke-width: 2px;
            cursor: pointer;
            transition: all 0.3s;
        }
        
        .node:hover circle {
            r: 12;
            filter: drop-shadow(0 0 10px currentColor);
        }
        
        .node text {
            font-size: 10px;
            fill: #fff;
            text-anchor: middle;
            pointer-events: none;
        }
        
        .link {
            stroke: #00ff00;
            stroke-opacity: 0.6;
            stroke-width: 2px;
            fill: none;
        }
        
        .event-item {
            padding: 5px;
            margin: 3px 0;
            background: rgba(0, 255, 0, 0.1);
            border-left: 3px solid #00ff00;
            font-size: 0.85em;
            animation: slideIn 0.3s;
        }
        
        @keyframes slideIn {
            from { transform: translateX(-20px); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
        
        .event-item.tool { border-left-color: #ff0000; background: rgba(255, 0, 0, 0.1); }
        .event-item.decision { border-left-color: #ffff00; background: rgba(255, 255, 0, 0.1); }
        
        .timestamp {
            color: #666;
            font-size: 0.8em;
        }
        
        .context-item {
            padding: 5px;
            margin: 5px 0;
            background: rgba(0, 255, 255, 0.1);
            border-radius: 3px;
        }
        
        .context-key {
            color: #00ffff;
            font-weight: bold;
        }
        
        .metric {
            display: inline-block;
            margin: 10px;
            padding: 10px 20px;
            background: rgba(255, 0, 255, 0.2);
            border: 1px solid #ff00ff;
            border-radius: 5px;
            text-align: center;
        }
        
        .metric-value {
            font-size: 2em;
            color: #ff00ff;
            font-weight: bold;
        }
        
        .metric-label {
            font-size: 0.8em;
            color: #aaa;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🧠 AI THOUGHT VISUALIZATION - LIVE MODE 🧠</h1>
        <div class="status">● CONNECTED - Capturing real-time reasoning</div>
    </div>
    
    <div class="container">
        <div class="panel" id="graph">
            <h2>Reasoning Graph (Live)</h2>
            <svg id="graph-svg"></svg>
        </div>
        
        <div class="panel">
            <h2>Context Memory</h2>
            <div id="context"></div>
            <h2 style="margin-top: 20px;">Metrics</h2>
            <div id="metrics">
                <div class="metric">
                    <div class="metric-value" id="metric-tokens">0</div>
                    <div class="metric-label">Tokens</div>
                </div>
                <div class="metric">
                    <div class="metric-value" id="metric-tools">0</div>
                    <div class="metric-label">Tools</div>
                </div>
                <div class="metric">
                    <div class="metric-value" id="metric-time">0s</div>
                    <div class="metric-label">Time</div>
                </div>
            </div>
        </div>
        
        <div class="panel">
            <h2>Event Log</h2>
            <div id="events"></div>
        </div>
    </div>
    
    <script>
        const socket = io();
        
        // D3 graph setup
        const svg = d3.select("#graph-svg");
        const width = svg.node().parentElement.clientWidth;
        const height = svg.node().parentElement.clientHeight;
        
        svg.attr("width", width).attr("height", height);
        
        const simulation = d3.forceSimulation()
            .force("link", d3.forceLink().id(d => d.id).distance(100))
            .force("charge", d3.forceManyBody().strength(-300))
            .force("center", d3.forceCenter(width / 2, height / 2))
            .force("collision", d3.forceCollide().radius(30));
        
        let linkGroup = svg.append("g").attr("class", "links");
        let nodeGroup = svg.append("g").attr("class", "nodes");
        
        const colorMap = {
            thinking: "#00ff00",
            tool: "#ff0000",
            decision: "#ffff00",
            result: "#00ffff"
        };
        
        socket.on('graph_update', function(data) {
            // Update links
            const links = linkGroup.selectAll("path")
                .data(data.links, d => `${d.source.id || d.source}-${d.target.id || d.target}`);
            
            links.enter()
                .append("path")
                .attr("class", "link")
                .merge(links);
            
            links.exit().remove();
            
            // Update nodes
            const nodes = nodeGroup.selectAll("g")
                .data(data.nodes, d => d.id);
            
            const nodeEnter = nodes.enter()
                .append("g")
                .attr("class", "node")
                .call(d3.drag()
                    .on("start", dragstarted)
                    .on("drag", dragged)
                    .on("end", dragended));
            
            nodeEnter.append("circle")
                .attr("r", 8)
                .attr("fill", d => colorMap[d.category] || "#00ff00");
            
            nodeEnter.append("text")
                .attr("dy", 20)
                .text(d => d.label);
            
            nodeEnter.append("title")
                .text(d => d.full_text);
            
            // Update simulation
            simulation.nodes(data.nodes);
            simulation.force("link").links(data.links);
            simulation.alpha(0.3).restart();
        });
        
        simulation.on("tick", () => {
            linkGroup.selectAll("path")
                .attr("d", d => {
                    const dx = d.target.x - d.source.x;
                    const dy = d.target.y - d.source.y;
                    return `M${d.source.x},${d.source.y} L${d.target.x},${d.target.y}`;
                });
            
            nodeGroup.selectAll("g")
                .attr("transform", d => `translate(${d.x},${d.y})`);
        });
        
        function dragstarted(event, d) {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
        }
        
        function dragged(event, d) {
            d.fx = event.x;
            d.fy = event.y;
        }
        
        function dragended(event, d) {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
        }
        
        // Event log updates
        socket.on('event_log', function(event) {
            const eventsDiv = document.getElementById('events');
            const item = document.createElement('div');
            item.className = `event-item ${event.type}`;
            item.innerHTML = `
                <span class="timestamp">${new Date(event.timestamp).toLocaleTimeString()}</span>
                <div>${event.message}</div>
            `;
            eventsDiv.insertBefore(item, eventsDiv.firstChild);
            
            // Keep only last 50 events
            while (eventsDiv.children.length > 50) {
                eventsDiv.removeChild(eventsDiv.lastChild);
            }
        });
        
        // Context updates
        socket.on('context_update', function(context) {
            const contextDiv = document.getElementById('context');
            contextDiv.innerHTML = Object.entries(context).map(([key, value]) => `
                <div class="context-item">
                    <span class="context-key">${key}:</span> ${JSON.stringify(value)}
                </div>
            `).join('');
        });
        
        // Metrics updates
        socket.on('metrics_update', function(metrics) {
            document.getElementById('metric-tokens').textContent = metrics.tokens || 0;
            document.getElementById('metric-tools').textContent = metrics.tools || 0;
            document.getElementById('metric-time').textContent = (metrics.time || 0).toFixed(1) + 's';
        });
        
        // Connection status
        socket.on('connect', function() {
            document.querySelector('.status').innerHTML = '● CONNECTED - Capturing real-time reasoning';
        });
        
        socket.on('disconnect', function() {
            document.querySelector('.status').innerHTML = '● DISCONNECTED - Waiting for connection...';
        });
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@socketio.on('connect')
def handle_connect():
    print("Client connected")
    # Send current state
    emit('graph_update', thought_graph)
    emit('context_update', context_memory)
    emit('metrics_update', metrics)

@socketio.on('disconnect')
def handle_disconnect():
    print("Client disconnected")

@app.route('/api/event', methods=['POST'])
def receive_event():
    """Receive events via HTTP POST from the interceptor."""
    try:
        event = request.get_json()
        if event:
            # Put event in the queue so the background thread processes it
            live_events.put(event)
            return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(f"Error receiving event: {e}")
    return jsonify({"status": "error"}), 400

if __name__ == '__main__':
    print("=" * 70)
    print("AI Thought Visualization - LIVE MODE")
    print("=" * 70)
    print()
    print("Starting live capture server...")
    print("Open your browser to: http://localhost:5000")
    print()
    print("To capture your agent's thoughts, add this to your agent code:")
    print()
    print("  from ai_thought_viz_live import interceptor")
    print()
    print("  # In your reasoning loop:")
    print("  interceptor.thought('Analyzing the problem...')")
    print("  interceptor.tool_call('web_search', {'query': 'example'})")
    print("  interceptor.decision('Choosing approach A')")
    print()
    print("Press Ctrl+C to stop")
    print("=" * 70)
    
    # Start event processor thread
    processor_thread = threading.Thread(target=process_events, daemon=True)
    processor_thread.start()
    
    socketio.run(app, host="0.0.0.0", port=5001, debug=False, allow_unsafe_werkzeug=True)
