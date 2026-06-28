#!/bin/bash
# ONE-SHOT FIX for live login 404 on http://3.110.209.154
# Paste into AWS EC2 Instance Connect terminal (ubuntu user):
#   bash one_shot_live_fix.sh
# Or from repo: cd ~/defoex-backend && bash deploy/one_shot_live_fix.sh

set -e
cd "${HOME}/defoex-backend" 2>/dev/null || cd "$(dirname "$0")/.."

echo "=== Sync code (keep .env) ==="
[ -f .env ] && cp .env /tmp/defoex.env.bak
git fetch origin main
git reset --hard origin/main
[ -f /tmp/defoex.env.bak ] && cp /tmp/defoex.env.bak .env

echo "=== Install deps ==="
[ -d venv ] && source venv/bin/activate
pip install -q -r requirements.txt gunicorn

echo "=== Restart gunicorn on :8000 ==="
pkill -f 'gunicorn.*wsgi:app' 2>/dev/null || true
sleep 1
if command -v systemctl >/dev/null 2>&1; then
  sudo cp deploy/defoex.service /etc/systemd/system/defoex.service 2>/dev/null || true
  sudo systemctl daemon-reload
  sudo systemctl enable defoex 2>/dev/null || true
  sudo systemctl restart defoex
else
  nohup gunicorn -w 4 -b 127.0.0.1:8000 wsgi:app >/tmp/defoex-gunicorn.log 2>&1 &
fi
sleep 3

echo "=== Test gunicorn ==="
curl -s http://127.0.0.1:8000/health | head -c 100; echo
curl -s -o /dev/null -w "login direct: HTTP %{http_code}\n" \
  -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" -d '{}'

echo "=== Configure nginx ==="
sudo tee /etc/nginx/sites-available/defoex >/dev/null <<'NGINX'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name 3.110.209.154 _;
    root /var/www/defoex;
    index index.html;
    client_max_body_size 20M;

    location ^~ /health {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location ^~ /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
NGINX

sudo ln -sf /etc/nginx/sites-available/defoex /etc/nginx/sites-enabled/defoex
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx

echo "=== Test public API ==="
curl -s http://127.0.0.1/health | head -c 100; echo
curl -s -o /dev/null -w "login public: HTTP %{http_code}\n" \
  -X POST http://127.0.0.1/api/auth/login \
  -H "Content-Type: application/json" -d '{}'

echo "✅ Done — try http://3.110.209.154/login (rashmi / rash123)"
