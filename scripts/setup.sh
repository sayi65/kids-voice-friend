#!/bin/bash
# 初めて使う Mac での準備をまとめて行う。途中で止まっても、もう一度実行すれば続きから進む
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "$(uname -s)/$(uname -m)" != "Darwin/arm64" ]; then
  echo "Apple Silicon (M1 以降) の Mac だけに対応しています"; exit 1
fi
if ! command -v brew >/dev/null; then
  echo "Homebrew が必要です。https://brew.sh の手順で入れてから、もう一度実行してください"; exit 1
fi

[ -f .env ] || cp .env.example .env
set -a; . ./.env; set +a
MODEL="${AI_FRIEND_MODEL:-gemma4:12b}"

echo "== 1/5 ツールを入れる (uv, Ollama)"
command -v uv >/dev/null || brew install uv
if ! command -v ollama >/dev/null; then
  brew install ollama
fi

echo "== 2/5 Ollama を起動する"
if ! curl -s -m 2 http://localhost:11434/api/version >/dev/null; then
  if [ -d /Applications/Ollama.app ]; then open -a Ollama; else brew services start ollama; fi
  for _ in $(seq 1 30); do curl -s -m 2 http://localhost:11434/api/version >/dev/null && break; sleep 1; done
fi
curl -s -m 2 http://localhost:11434/api/version >/dev/null || { echo "Ollama が起動しませんでした。README の「困ったとき」を見てください"; exit 1; }

echo "== 3/5 返事を作るモデル ($MODEL) をダウンロードする (約 8GB)"
ollama pull "$MODEL"

echo "== 4/5 Python の環境を作る"
[ -d .venv ] || uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements.txt

echo "== 5/5 音声認識のモデルをダウンロードする (約 1.5GB)"
.venv/bin/python -c "import numpy as np, mlx_whisper; mlx_whisper.transcribe(np.zeros(16000, dtype=np.float32), path_or_hf_repo='mlx-community/whisper-large-v3-turbo', language='ja')" >/dev/null

echo
if ls voices/*.aivmx >/dev/null 2>&1; then
  echo "準備ができました。scripts/start.sh で起動してください"
else
  echo "準備ができました。最後に、声のファイル (.aivmx) を voices/ に置いてください (README の「声のファイル」)"
fi
