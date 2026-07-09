#!/bin/bash
# Forward the remote inference server port to local machine.
# Run this on your local PC.

set -e

REMOTE_HOST="10.65.14.8"
REMOTE_USER="lzh"
REMOTE_PORT=8000
LOCAL_PORT=8000

echo "Creating SSH tunnel: localhost:$LOCAL_PORT -> $REMOTE_HOST:$REMOTE_PORT"
echo "Keep this terminal open. Press Ctrl+C to stop."
ssh -L "${LOCAL_PORT}:localhost:${REMOTE_PORT}" "${REMOTE_USER}@${REMOTE_HOST}"
