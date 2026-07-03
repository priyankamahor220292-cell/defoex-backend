#!/bin/bash
# Deploy backend + nginx on live server (188.208.141.253)
# Run ON THE SERVER:
#   cd ~/defoex-backend && bash deploy_live.sh
#
# Fixes: 502/404 on POST /api/auth/login (gunicorn down or nginx not proxying /api)

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec bash "$SCRIPT_DIR/deploy/fix_502_vps.sh"
