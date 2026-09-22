#!/bin/bash
echo "Starting Dish-Chat services..."
~/dish-chat/start-backend.sh
sleep 3
~/dish-chat/start-frontend.sh
echo ""
echo "Services starting..."
HOST_IP=$(hostname -I | awk '{print $1}')
echo "Backend:  http://${HOST_IP}:8000"
echo "Frontend: http://${HOST_IP}:3000"
echo ""
echo "Also accessible at:"
echo "Backend:  http://0.0.0.0:8000"
echo "Frontend: http://0.0.0.0:3000"
