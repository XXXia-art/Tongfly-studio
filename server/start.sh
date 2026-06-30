#!/bin/bash
# Start the Tongfly Studio inference server on the remote GPU server.
# Run this on the server (e.g. lzh@10.65.14.8).

set -e

cd "$(dirname "$0")"

CONDA_ENV="drone"
LOG_FILE="server.log"

echo "Starting inference server with conda env: $CONDA_ENV"
nohup conda run --no-capture-output -n "$CONDA_ENV" python main.py > "$LOG_FILE" 2>&1 &
echo $! > server.pid

echo "Server PID: $(cat server.pid)"
echo "Log file: $LOG_FILE"
echo "Waiting for health check..."

for i in {1..60}; do
  if curl -s http://localhost:8000/health >/dev/null 2>&1; then
    echo "Server is ready: http://$(hostname -I | awk '{print $1}'):8000"
    exit 0
  fi
  sleep 2
done

echo "Server did not become ready within 2 minutes. Check $LOG_FILE"
exit 1
