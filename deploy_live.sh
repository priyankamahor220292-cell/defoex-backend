#!/bin/bash
# Deploy backend + nginx on live server (3.110.209.154)
# Run ON THE SERVER:
#   cd ~/defoex-backend && bash deploy_live.sh
#
# Fixes: POST /api/auth/login returning 404 (stale gunicorn or nginx not proxying /api)

set -e
cd "$(dirname "$0")"

echo "=== 0. Sync code (keep server .env) ==="
if [ -f .env ]; then
  cp .env /tmp/defoex.env.bak
fi
git fetch origin main
git reset --hard origin/main
if [ -f /tmp/defoex.env.bak ]; then
  cp /tmp/defoex.env.bak .env
  echo "Restored .env"
fi

echo ""
echo "=== 1. Python deps + gunicorn ==="
if [ -d venv ]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
elif [ -d .venv ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi
pip install -q -r requirements.txt
pip install -q gunicorn

echo ""
echo "=== 2. Schema + adviser ↔ investor links ==="
python3 utils/fix_adviser_investor_link.py || true

echo ""
echo "=== 3. Restart API (gunicorn on 127.0.0.1:8000) ==="
pkill -f 'gunicorn.*wsgi:app' 2>/dev/null || true
pkill -f 'gunicorn.*app:app' 2>/dev/null || true
sleep 1

if [ -f deploy/defoex.service ] && command -v systemctl >/dev/null 2>&1; then
  sudo cp deploy/defoex.service /etc/systemd/system/defoex.service
  sudo systemctl daemon-reload
  sudo systemctl enable defoex
  sudo systemctl restart defoex
  echo "Restarted systemd service: defoex"
else
  nohup gunicorn -w 4 -b 127.0.0.1:8000 wsgi:app >/tmp/defoex-gunicorn.log 2>&1 &
  echo "Started gunicorn wsgi:app on 127.0.0.1:8000 (log: /tmp/defoex-gunicorn.log)"
fi

sleep 3

echo ""
echo "=== 4. Smoke tests (direct gunicorn — must NOT be 404) ==="
HC=$(curl -s -o /tmp/defoex-health.json -w "%{http_code}" http://127.0.0.1:8000/health || echo "000")
echo "GET  /health → HTTP $HC"
head -c 120 /tmp/defoex-health.json 2>/dev/null; echo

LC=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" -d '{}' || echo "000")
echo "POST /api/auth/login → HTTP $LC (expect 400, NOT 404)"

if [ "$HC" != "200" ] || [ "$LC" = "404" ]; then
  echo "ERROR: gunicorn is not serving routes. Check: tail -50 /tmp/defoex-gunicorn.log"
  journalctl -u defoex -n 30 --no-pager 2>/dev/null || true
  exit 1
fi

echo ""
echo "=== 5. Nginx — proxy /api and /health to gunicorn :8000 ==="
if command -v nginx >/dev/null 2>&1 && [ -f deploy/nginx-defoex.conf ]; then
  sudo cp deploy/nginx-defoex.conf /etc/nginx/sites-available/defoex
  sudo ln -sf /etc/nginx/sites-available/defoex /etc/nginx/sites-enabled/defoex
  sudo rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
  sudo nginx -t
  sudo systemctl reload nginx
  echo "Nginx reloaded"

  PHC=$(curl -s -o /tmp/defoex-pub-health.json -w "%{http_code}" http://127.0.0.1/health || echo "000")
  PLC=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST http://127.0.0.1/api/auth/login \
    -H "Content-Type: application/json" -d '{}' || echo "000")
  echo "PUBLIC GET  /health → HTTP $PHC (expect 200 JSON)"
  echo "PUBLIC POST /api/auth/login → HTTP $PLC (expect 400, NOT 404)"
  head -c 120 /tmp/defoex-pub-health.json 2>/dev/null; echo

  if [ "$PLC" = "404" ]; then
    echo "ERROR: nginx still returns 404 for /api. Check: sudo nginx -T | grep -A5 location"
    exit 1
  fi
else
  echo "WARN: nginx not installed — API only on 127.0.0.1:8000"
fi

echo ""
echo "=== 6. Frontend build → /var/www/defoex ==="
FRONTEND_DIR=""
for d in "../defoex-frontend" "$HOME/defoex-frontend" "/home/ubuntu/defoex-frontend"; do
  if [ -f "$d/package.json" ]; then
    FRONTEND_DIR="$(cd "$d" && pwd)"
    break
  fi
done

if [ -n "$FRONTEND_DIR" ] && command -v npm >/dev/null 2>&1; then
  echo "Building frontend in $FRONTEND_DIR"
  cd "$FRONTEND_DIR"
  if [ -f .env.production ]; then
    cp .env.production .env
  fi
  npm ci --silent 2>/dev/null || npm install --silent
  npm run build
  sudo mkdir -p /var/www/defoex
  sudo rm -rf /var/www/defoex/*
  sudo cp -r build/* /var/www/defoex/
  echo "Frontend deployed to /var/www/defoex"
  cd - >/dev/null
else
  echo "WARN: defoex-frontend not found or npm missing — skip static deploy"
  echo "      Clone frontend to ~/defoex-frontend and re-run this script"
fi

echo ""
echo "✅ Deploy done. Login at http://3.110.209.154/login should work."
echo "   Test: curl -s http://127.0.0.1/health  (must show JSON, not HTML)"
echo "   Test: curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1/api/auth/login -H 'Content-Type: application/json' -d '{}'"
echo "         (expect 400, NOT 404)"
