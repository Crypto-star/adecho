#!/usr/bin/env bash
# Start the API with all logs routed to logs/api.log. Terminal stays minimal.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "No venv. Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi
source .venv/bin/activate

mkdir -p logs
# Roll previous log aside so each `run.sh` start gets a clean file,
# but individual --reload restarts APPEND (don't lose the active run).
if [ -s logs/api.log ]; then
  mv logs/api.log "logs/api.$(date +%Y%m%d-%H%M%S).log"
fi
: > logs/api.log

echo "API → http://localhost:8000"
echo "Logs → $(pwd)/logs/api.log  (tail -f to follow)"
exec uvicorn app.main:app \
  --host 0.0.0.0 --port 8000 --reload \
  --no-access-log --log-level warning \
  >>logs/api.log 2>&1
