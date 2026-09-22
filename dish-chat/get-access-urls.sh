#!/bin/bash
# Get current access URLs for the chat-agent service

CURRENT_IP=$(hostname -I | awk '{print $1}')

echo ""
echo "=========================================="
echo "Chat-Agent Service Access URLs"
echo "=========================================="
echo ""
echo "📍 Current Server IP: $CURRENT_IP"
echo ""
echo "🔧 Backend API:"
echo "   - Internal: http://localhost:8000"
echo "   - External: http://$CURRENT_IP:8000"
echo ""
echo "🎨 Frontend UI:"
echo "   - Internal: http://localhost:3000"
echo "   - External: http://$CURRENT_IP:3000"
echo ""
echo "💡 Services are bound to 0.0.0.0 and will work with any IP!"
echo ""
