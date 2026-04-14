#!/usr/bin/env bash
# Start Next dev server with all output routed to logs/web.log.
set -euo pipefail
cd "$(dirname "$0")"

mkdir -p logs
: > logs/web.log

echo "Web → http://localhost:3000"
echo "Logs → $(pwd)/logs/web.log  (tail -f to follow)"
# FORCE_COLOR=0 strips ANSI codes so the file is grep-able.
FORCE_COLOR=0 exec npm run dev >>logs/web.log 2>&1
