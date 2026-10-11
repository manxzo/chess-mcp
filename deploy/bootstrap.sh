#!/usr/bin/env bash
# Inside a fresh Ubuntu 26.04 CT: uv, Stockfish, the app, a `chess` user and the systemd unit.
# Usage: bootstrap.sh <container-ip> [git-ref]
set -euo pipefail
IP=$1; REF=${2:-main}
export DEBIAN_FRONTEND=noninteractive PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
systemctl mask netplan-configure.service >/dev/null 2>&1 || true
apt-get update -qq && apt-get install -y -qq git curl ca-certificates >/dev/null
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh >/dev/null
TMP=$(mktemp -d)
curl -fsSL -o "$TMP/sf.tar.gz" https://github.com/official-stockfish/Stockfish/releases/download/sf_19/stockfish-linux-x86-64-universal.tar.gz
tar -xzf "$TMP/sf.tar.gz" -C "$TMP"
install -m755 "$(find "$TMP" -type f -name 'stockfish*' ! -name '*.tar.gz' -perm -u+x | head -1)" /usr/local/bin/stockfish
useradd -r -m -d /var/lib/chess-mcp -s /usr/sbin/nologin chess 2>/dev/null || true
install -d -o chess -g chess /var/lib/chess-mcp /opt/chess-mcp
[ -d /opt/chess-mcp/.git ] || sudo -u chess git clone -q https://github.com/manxzo/chess-mcp.git /opt/chess-mcp
sudo -u chess git -C /opt/chess-mcp checkout -q "$REF"
sudo -u chess env HOME=/var/lib/chess-mcp UV_CACHE_DIR=/var/lib/chess-mcp/.cache/uv uv sync --frozen --no-dev --project /opt/chess-mcp -q
echo "CHESS_HOST=$IP" > /etc/chess-mcp.env
cp /opt/chess-mcp/deploy/chess.service /etc/systemd/system/chess.service
systemctl daemon-reload && systemctl enable --now chess.service
sleep 3
systemctl is-active chess.service
echo "token: $(cat /var/lib/chess-mcp/token)"
