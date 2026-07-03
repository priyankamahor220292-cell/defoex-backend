#!/bin/bash
# Fix 502 Bad Gateway on http://188.208.141.253
# Run ON THE VPS after SSH login:
#   cd ~/defoex-backend && bash deploy/fix_502_vps.sh

set -e

BACKEND_DIR="${HOME}/defoex-backend"
[ -d "$BACKEND_DIR" ] || BACKEND_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BACKEND_DIR"

echo "=== DefOex full VPS fix ($BACKEND_DIR) ==="

# ── 0. Pull latest code (keep server .env) ───────────────────────
if [ -d .git ]; then
  echo "=== 0. git pull ==="
  [ -f .env ] && cp .env /tmp/defoex.env.bak
  git fetch origin main
  git reset --hard origin/main
  [ -f /tmp/defoex.env.bak ] && cp /tmp/defoex.env.bak .env && echo "Restored .env"
fi

if [ ! -f .env ]; then
  echo "ERROR: .env missing. Copy .env.example and set DB_USER/DB_PASSWORD."
  exit 1
fi

# shellcheck disable=SC1091
set -a && source .env && set +a
DB_NAME="${DB_NAME:-defoex_database}"
DB_USER="${DB_USER:-postgres}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"

# ── 1. PostgreSQL ────────────────────────────────────────────────
echo "=== 1. PostgreSQL ==="
if command -v systemctl >/dev/null 2>&1; then
  sudo systemctl start postgresql 2>/dev/null || true
fi

if ! command -v psql >/dev/null 2>&1; then
  echo "Installing PostgreSQL..."
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y postgresql postgresql-contrib
  sudo systemctl enable postgresql
  sudo systemctl start postgresql
fi

# Create DB user if missing (peer auth as postgres)
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1; then
  echo "Creating PostgreSQL user: ${DB_USER}"
  sudo -u postgres psql -c "CREATE USER \"${DB_USER}\" WITH PASSWORD '${DB_PASSWORD}';" || true
  sudo -u postgres psql -c "ALTER USER \"${DB_USER}\" WITH SUPERUSER;" 2>/dev/null || true
fi

# Create database if missing
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
  echo "Creating database: ${DB_NAME}"
  sudo -u postgres createdb -O "${DB_USER}" "${DB_NAME}" 2>/dev/null \
    || sudo -u postgres psql -c "CREATE DATABASE \"${DB_NAME}\" OWNER \"${DB_USER}\";"
fi

# ── 2. Python venv + deps ────────────────────────────────────────
echo "=== 2. Python venv + deps ==="
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

# ── 3. DB tables + seed (if empty) ───────────────────────────────
echo "=== 3. Database tables ==="
TABLE_COUNT=$(python3 - <<'PY' 2>/dev/null || echo 0
import os, sys
sys.path.insert(0, os.getcwd())
from dotenv import load_dotenv
load_dotenv()
from app import app
from extensions import db
from sqlalchemy import text
with app.app_context():
    try:
        n = db.session.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'"
        )).scalar()
        print(n or 0)
    except Exception:
        print(0)
PY
)

if [ "${TABLE_COUNT:-0}" -lt 3 ]; then
  echo "Running reset_db.py (fresh schema + superadmin seed)..."
  python3 reset_db.py
else
  echo "Tables exist ($TABLE_COUNT) — skipping reset_db.py"
fi

# ── 4. Gunicorn via systemd ──────────────────────────────────────
echo "=== 4. Start gunicorn on 127.0.0.1:8000 ==="
pkill -f 'gunicorn.*wsgi:app' 2>/dev/null || true
sleep 1

VENV_BIN="$(pwd)/venv/bin"
[ -x "$VENV_BIN/gunicorn" ] || VENV_BIN="$(pwd)/.venv/bin"
RUN_USER="$(whoami)"

sudo tee /etc/systemd/system/defoex.service >/dev/null <<EOF
[Unit]
Description=DefOex IntraTech Flask API
After=network.target postgresql.service

[Service]
User=${RUN_USER}
Group=${RUN_USER}
WorkingDirectory=${BACKEND_DIR}
Environment="PATH=${VENV_BIN}"
EnvironmentFile=-${BACKEND_DIR}/.env
ExecStart=${VENV_BIN}/gunicorn -w 4 -b 127.0.0.1:8000 wsgi:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable defoex
sudo systemctl restart defoex
sleep 3

HC=$(curl -s -o /tmp/defoex-health.json -w "%{http_code}" http://127.0.0.1:8000/health || echo "000")
echo "GET 127.0.0.1:8000/health → HTTP $HC"
head -c 150 /tmp/defoex-health.json 2>/dev/null; echo

LC=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" -d '{}' || echo "000")
echo "POST 127.0.0.1:8000/api/auth/login → HTTP $LC (expect 400)"

if [ "$HC" != "200" ]; then
  echo "ERROR: gunicorn not healthy. Logs:"
  sudo journalctl -u defoex -n 40 --no-pager
  exit 1
fi

# ── 5. Nginx proxy /api + /health ────────────────────────────────
echo "=== 5. Nginx ==="
if ! command -v nginx >/dev/null 2>&1; then
  sudo apt-get install -y nginx
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
echo "PUBLIC /health → HTTP $PHC"
echo "PUBLIC /api/auth/login → HTTP $PLC"
head -c 150 /tmp/defoex-pub-health.json 2>/dev/null; echo

if [ "$PLC" = "502" ] || [ "$PLC" = "404" ]; then
  echo "ERROR: nginx still broken."
  sudo nginx -T 2>/dev/null | grep -A6 "location \^~ /api" || true
  exit 1
fi

# ── 6. Frontend build (optional) ─────────────────────────────────
FRONTEND_DIR=""
for d in "../defoex-frontend" "$HOME/defoex-frontend"; do
  [ -f "$d/package.json" ] && FRONTEND_DIR="$(cd "$d" && pwd)" && break
done

if [ -n "$FRONTEND_DIR" ] && command -v npm >/dev/null 2>&1; then
  echo "=== 6. Frontend build → /var/www/defoex ==="
  cd "$FRONTEND_DIR"
  git pull origin main 2>/dev/null || true
  [ -f .env.production ] && cp .env.production .env
  npm ci --silent 2>/dev/null || npm install --silent
  npm run build
  sudo mkdir -p /var/www/defoex
  sudo rm -rf /var/www/defoex/*
  sudo cp -r build/* /var/www/defoex/
  echo "Frontend deployed"
fi

echo ""
echo "✅ Done — login at http://188.208.141.253/login"
echo "   superadmin / Defoex@2024"
