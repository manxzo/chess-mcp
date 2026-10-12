#!/usr/bin/env bash
# Inside the CT: pull the latest code and restart.
set -euo pipefail
sudo -u chess git -C /opt/chess-mcp pull -q --ff-only
sudo -u chess env HOME=/var/lib/chess-mcp UV_CACHE_DIR=/var/lib/chess-mcp/.cache/uv uv sync --frozen --no-dev --project /opt/chess-mcp -q
CLAUDE=/var/lib/chess-mcp/.local/bin/claude
if [ -x "$CLAUDE" ]; then
  sudo -u chess env HOME=/var/lib/chess-mcp "$CLAUDE" update >/dev/null 2>&1 || true
else
  sudo -u chess env HOME=/var/lib/chess-mcp bash -c 'curl -fsSL https://claude.ai/install.sh | bash' >/dev/null
fi
cp /opt/chess-mcp/deploy/chess.service /etc/systemd/system/chess.service && systemctl daemon-reload
systemctl restart chess.service
systemctl is-active chess.service
