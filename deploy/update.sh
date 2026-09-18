#!/bin/bash
# Pull latest code and restart the bot
set -e

cd /opt/saveitdl/repo
git pull origin main

/opt/saveitdl/venv/bin/pip install -r requirements.txt -q

systemctl restart saveitdl
echo "Updated and restarted."
