#!/bin/bash
# サーバーを起動する。--lan を付けると、同じ Wi-Fi の iPhone からも https で開ける(家の Wi-Fi だけで使う)
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo ".env がありません。先に scripts/setup.sh を実行してください"; exit 1; }
set -a; . ./.env; set +a

curl -s -m 2 http://localhost:11434/api/version >/dev/null || {
  echo "Ollama が動いていません。Ollama アプリを起動するか、brew services start ollama を実行してください"; exit 1; }
ls voices/*.aivmx >/dev/null 2>&1 || {
  echo "voices/ に声のファイル (.aivmx) がありません。README の「声のファイル」を見てください"; exit 1; }

if [ "${1:-}" = "--lan" ]; then
  scripts/make_certs.sh
  echo "iPhone からは https://$(cat certs/ip.txt):${AI_FRIEND_LAN_PORT:-8766} を開いてください"
fi
exec .venv/bin/python -u voice_app.py "$@"
