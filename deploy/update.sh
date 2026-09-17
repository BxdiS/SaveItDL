#!/bin/bash
# Pull latest code and restart the bot
set -e

cd /opt/saveitdl/repo
git pull origin main

cp *.py /opt/saveitdl/
cp -r core /opt/saveitdl/
cp -r platforms /opt/saveitdl/
cp requirements.txt /opt/saveitdl/

/opt/saveitdl/venv/bin/pip install -r /opt/saveitdl/requirements.txt -q

systemctl restart saveitdl
echo "Updated and restarted."
