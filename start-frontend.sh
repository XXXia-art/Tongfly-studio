#!/bin/bash
# Start the Tongfly Studio frontend with the built-in UDP output bridge.
# The browser talks to Vite over HTTP; Vite forwards mode/content JSON as UDP.

set -e

cd "$(dirname "$0")"

TONGFLY_MODE_UDP_HOST="${TONGFLY_MODE_UDP_HOST:-127.0.0.1}"
TONGFLY_MODE_UDP_PORT="${TONGFLY_MODE_UDP_PORT:-9100}"
TONGFLY_CONTENT_UDP_HOST="${TONGFLY_CONTENT_UDP_HOST:-127.0.0.1}"
TONGFLY_CONTENT_UDP_PORT="${TONGFLY_CONTENT_UDP_PORT:-9200}"

echo "Starting frontend"
echo "Mode UDP target: ${TONGFLY_MODE_UDP_HOST}:${TONGFLY_MODE_UDP_PORT}"
echo "Content UDP target: ${TONGFLY_CONTENT_UDP_HOST}:${TONGFLY_CONTENT_UDP_PORT}"
npm run dev -- --host
