#!/bin/bash
# Deploy backend + verify API on live server (3.110.209.154)
# Run ON THE SERVER from defoex-backend after git pull:
#   bash deploy_live.sh

set -e
cd "$(dirname "$0")"

echo "=== 1. Schema + link adviser ↔ investor records ==="
python3 utils/fix_adviser_investor_link.py

echo ""
echo "=== 2. Restart API (gunicorn on port 8000) ==="

# Stop anything bound to port 8000 or old gunicorn on :80
pkill -f 'gunicorn.*wsgi:app' 2>/dev/null || true
pkill -f 'gunicorn.*app:app' 2>/dev/null || true
sleep 1

if systemctl is-active --quiet defoex 2>/dev/null; then
  sudo systemctl restart defoex
  echo "Restarted: defoex systemd service"
elif [ -f /etc/systemd/system/defoex.service ]; then
  sudo systemctl daemon-reload
  sudo systemctl enable defoex
  sudo systemctl restart defoex
  echo "Started: defoex systemd service"
elif command -v gunicorn >/dev/null 2>&1; then
  nohup gunicorn -w 4 -b 127.0.0.1:8000 wsgi:app >/tmp/defoex-gunicorn.log 2>&1 &
  echo "Started gunicorn wsgi:app on 127.0.0.1:8000 (log: /tmp/defoex-gunicorn.log)"
else
  echo "ERROR: gunicorn not found. Install: pip install gunicorn"
  exit 1
fi

sleep 2

echo ""
echo "=== 3. Smoke tests (API must NOT be 404) ==="
curl -s -o /dev/null -w "GET  /health → HTTP %{http_code}\n" http://127.0.0.1:8000/health || true
curl -s -o /dev/null -w "POST /api/auth/login → HTTP %{http_code}\n" \
  -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" -d '{}' || true
curl -s -o /dev/null -w "GET  /api/investment-plans/list → HTTP %{http_code}\n" \
  http://127.0.0.1:8000/api/investment-plans/list || true

echo ""
echo "=== 4. Nginx — proxy /api and /health to gunicorn :8000 ==="
if command -v nginx >/dev/null 2>&1 && [ -f deploy/nginx-defoex.conf ]; then
  sudo cp deploy/nginx-defoex.conf /etc/nginx/sites-available/defoex
  sudo ln -sf /etc/nginx/sites-available/defoex /etc/nginx/sites-enabled/defoex
  # Disable default site if it steals port 80 without /api proxy
  sudo rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
  sudo nginx -t
  sudo systemctl reload nginx
  echo "Nginx reloaded with /api → 127.0.0.1:8000"
  curl -s -o /dev/null -w "PUBLIC POST /api/auth/login → HTTP %{http_code}\n" \
    -X POST http://127.0.0.1/api/auth/login \
    -H "Content-Type: application/json" -d '{}' || true
else
  echo "nginx not installed — API only on 127.0.0.1:8000"
fi

echo ""
echo "✅ Deploy done. POST /api/auth/login should return 400 or 401 (NOT 404)."
