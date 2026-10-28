#!/bin/bash
set -e

echo "=========================================="
echo " Starting RBHS All-in-One Cloud Service "
echo "=========================================="

# 1. Start WhatsApp Gateway in background
echo "Launching Node.js WhatsApp Gateway..."
node bot.js &

# 2. Start Gunicorn Web Service in foreground
echo "Launching Gunicorn on port $PORT..."
exec gunicorn app:app --workers 2 --threads 4 --worker-class gthread --bind 0.0.0.0:$PORT
