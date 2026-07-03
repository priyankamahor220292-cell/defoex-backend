#!/bin/bash
# Fix 502 Bad Gateway on http://188.208.141.253
# Run ON THE VPS (SSH in first):
#   cd ~/defoex-backend && bash deploy/fix_502_vps.sh

set -e

BACKEND_DIR="${HOME}/defoex-backend"
[ -d "$BACKEND_DIR" ] || BACKEND_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BACKEND_DIR"

echo "=== DefOex 502 fix (backend: $BACKEND_DIR) ==="

echo "=== 1. Python venv + deps ==="
if [ -d venv ]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
elif [ -d .venv ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  python3 -m venv venv
  # shellcheck disable=SC1091
  source venv/bin/activate
fi
pip install -q -r requirements.txt gunicorn

echo "=== 2. Stop stale gunicorn ==="
pkill -f 'gunicorn.*wsgi:app' 2>/dev/null || true
pkill -f 'gunicorn.*app:app' 2>/dev/null || true
sleep 1

echo "=== 3. Start gunicorn on 127.0.0.1:8000 ==="
nohup gunicorn -w 4 -b 127.0.0.1:8000 wsgi:app >/tmp/defoex-gunicorn.log 2>&1 &
sleep 3

HC=$(curl -s -o /tmp/defoex-health.json -w "%{http_code}" http://127.0.0.1:8000/health || echo "000")
echo "GET 127.0.0.1:8000/health → HTTP $HC"
head -c 120 /tmp/defoex-health.json 2>/dev/null; echo

LC=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" -d '{}' || echo "000")
echo "POST 127.0.0.1:8000/api/auth/login → HTTP $LC (expect 400)"

if [ "$HC" != "200" ]; then
  echo "ERROR: gunicorn failed. Last log lines:"
  tail -40 /tmp/defoex-gunicorn.log
  echo ""
  echo "Common causes:"
  echo "  • PostgreSQL not running: sudo systemctl start postgresql"
  echo "  • Wrong DB credentials in .env"
  echo "  • Missing database: createdb defoex_database"
  exit 1
fi

echo "=== 4. Nginx — proxy /api and /health to :8000 ==="
if ! command -v nginx >/dev/null 2>&1; then
  echo "WARN: nginx not installed — API only on 127.0.0.1:8000"
  exit 0
fi

sudo cp deploy/nginx-defoex.conf /etc/nginx/sites-available/defoex
sudo ln -sf /etc/nginx/sites-available/defoex /etc/nginx/sites-enabled/defoex
sudo rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
sudo nginx -t
sudo systemctl reload nginx

PHC=$(curl -s -o /tmp/defoex-pub-health.json -w "%{http_code}" http://127.0.0.1/health || echo "000")
PLC=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://127.0.0.1/api/auth/login \
  -H "Content-Type: application/json" -d '{}' || echo "000")
echo "PUBLIC /health → HTTP $PHC (expect 200 JSON)"
echo "PUBLIC /api/auth/login → HTTP $PLC (expect 400, NOT 502)"
head -c 120 /tmp/defoex-pub-health.json 2>/dev/null; echo

if [ "$PLC" = "502" ] || [ "$PLC" = "404" ]; then
  echo "ERROR: nginx still broken. Run: sudo nginx -T | grep -A8 location"
  exit 1
fi

echo ""
echo "✅ Fixed. Try login at http://188.208.141.253/login"
