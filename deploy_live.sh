#!/bin/bash
# Deploy backend fixes to live server (3.110.209.154)
# Run from defoex-backend folder on the SERVER after git pull:
#   bash deploy_live.sh

set -e
cd "$(dirname "$0")"

echo "=== 1. Add adviser.investor_id column + link records ==="
python3 utils/fix_adviser_investor_link.py

echo ""
echo "=== 2. Restart API service ==="
if systemctl is-active --quiet defoex 2>/dev/null; then
  sudo systemctl restart defoex
  echo "Restarted: defoex systemd service"
elif systemctl is-active --quiet gunicorn 2>/dev/null; then
  sudo systemctl restart gunicorn
  echo "Restarted: gunicorn"
else
  echo "No systemd service found. Restart manually, e.g.:"
  echo "  pkill -f 'gunicorn.*app:app' ; gunicorn -w 4 -b 0.0.0.0:80 app:app"
fi

echo ""
echo "=== 3. Smoke test ==="
curl -s -o /dev/null -w "GET /health → HTTP %{http_code}\n" http://127.0.0.1/health || true
curl -s -o /dev/null -w "GET /api/investment-plans/list → HTTP %{http_code}\n" http://127.0.0.1/api/investment-plans/list || true

echo ""
echo "✅ Done. /api/investment-plans/get-investor-details should no longer return 404."
