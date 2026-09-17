#!/bin/bash
# Install Telegram Bot API Local Server
# Run as root on the VPS
set -e

echo ">>> Installing build dependencies..."
apt-get update -qq
apt-get install -y -qq make git zlib1g-dev libssl-dev gperf cmake g++ > /dev/null

echo ">>> Cloning telegram-bot-api..."
cd /opt
if [ -d telegram-bot-api ]; then
    cd telegram-bot-api && git pull
else
    git clone --recursive https://github.com/tdlib/telegram-bot-api.git
    cd telegram-bot-api
fi

echo ">>> Building (this takes 5-10 minutes)..."
rm -rf build && mkdir build && cd build
cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX:PATH=/usr/local ..
cmake --build . --target install -j "$(nproc)"

echo ">>> Creating systemd service..."
cat > /etc/systemd/system/telegram-bot-api.service <<'UNIT'
[Unit]
Description=Telegram Bot API Local Server
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/telegram-bot-api \
    --http-port=8081 \
    --local \
    --dir=/opt/telegram-bot-api-data \
    --log=/var/log/telegram-bot-api.log
Restart=always
RestartSec=5
User=saveitdl

[Install]
WantedBy=multi-user.target
UNIT

mkdir -p /opt/telegram-bot-api-data
chown -R saveitdl:saveitdl /opt/telegram-bot-api-data

systemctl daemon-reload
systemctl enable telegram-bot-api
systemctl start telegram-bot-api

echo ""
echo ">>> Telegram Bot API Local Server installed!"
echo ">>> Running on http://localhost:8081"
echo ""
echo "Now add to /opt/saveitdl/.env:"
echo "  BOT_API_URL=http://localhost:8081/bot"
echo ""
echo "Then restart the bot:"
echo "  systemctl restart saveitdl"
echo ""
echo "File limit is now 2 GB instead of 50 MB."
