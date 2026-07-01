#!/bin/bash
# Start the Tongfly Studio inference server on RK3588.
# All dependencies are in the system Python3 (rknn-toolkit-lite2, torch, diffusers, etc.)

set -e

cd "$(dirname "$0")"

LOG_FILE="server.log"

echo "Starting inference server (RK3588 NPU) …"
nohup python3 main.py > "$LOG_FILE" 2>&1 &
echo $! > server.pid

echo "Server PID: $(cat server.pid)"
echo "Log file: $LOG_FILE"
echo "Waiting for health check (models load on first request) …"

for i in {1..10}; do
  if curl -s http://localhost:8000/health >/dev/null 2>&1; then
    echo "Server is ready: http://$(hostname -I | awk '{print $1}'):8000"
    exit 0
  fi
  sleep 1
done

echo "Server did not become ready . Check $LOG_FILE"
exit 1
