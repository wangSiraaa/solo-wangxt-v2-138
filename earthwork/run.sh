#!/usr/bin/env bash
# 本地一键启动（无 Postgres 时自动回退 data/*.json 文件存储）
set -e
cd "$(dirname "$0")"

PORT_API="${PORT_API:-8765}"
PORT_WEB="${PORT_WEB:-5173}"

echo "== 启动 FastAPI (http://127.0.0.1:${PORT_API}) =="
python3 -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT_API}" &
API_PID=$!

echo "== 启动 Vue3 + Three.js 前端 (http://127.0.0.1:${PORT_WEB}) =="
( cd frontend
  [ -d node_modules ] || npm install
  npx vite --host 127.0.0.1 --port "${PORT_WEB}" ) &
WEB_PID=$!

trap "kill ${API_PID} ${WEB_PID} 2>/dev/null || true" EXIT
wait
