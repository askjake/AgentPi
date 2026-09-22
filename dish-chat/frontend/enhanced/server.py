#!/usr/bin/env python3
from flask import Flask, send_from_directory, jsonify
from flask_cors import CORS
import os

app = Flask(__name__, static_folder='static', static_url_path='/static')
CORS(app)

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/api/health')
def health():
    return jsonify({
        'status': 'healthy',
        'service': 'enhanced-frontend',
        'backend_url': os.environ.get('DISHCHAT_BACKEND_URL', 'http://127.0.0.1:8000')
    })

if __name__ == '__main__':
    app.run(host=os.environ.get('DISHCHAT_ENHANCED_HOST', '127.0.0.1'), port=int(os.environ.get('DISHCHAT_ENHANCED_PORT', '3001')), debug=False)

