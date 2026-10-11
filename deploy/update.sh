#!/usr/bin/env bash
# Inside the CT: pull the latest code and restart.
set -euo pipefail
sudo -u chess git -C /opt/chess-mcp pull -q --ff-only
sudo -u chess env HOME=/var/lib/chess-mcp UV_CACHE_DIR=/var/lib/chess-mcp/.cache/uv uv sync --frozen --no-dev --project /opt/chess-mcp -q
systemctl restart chess.service
systemctl is-active chess.service
