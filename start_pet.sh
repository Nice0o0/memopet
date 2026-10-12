#!/usr/bin/env bash
# MemoPet 一键启动（Linux/macOS）：前置为同级 ../rwkv 检出
cd "$(dirname "$0")"

PY=../rwkv/.venv/bin/python
[ -x ../rwkv/.venv312/bin/python ] && PY=../rwkv/.venv312/bin/python
if [ ! -x "$PY" ]; then
  echo "[memopet] 未找到 ../rwkv 的 venv，请先按 stateswap README 完成安装" >&2
  exit 1
fi

echo "[memopet] WebUI: http://127.0.0.1:8001"
exec "$PY" -m memopet.server --port 8001
