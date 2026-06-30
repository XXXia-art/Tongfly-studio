#!/bin/bash
# Start the Tongfly Studio frontend locally, connected to the inference server.
# Run this on your local PC.
#
# If you are using the SSH tunnel (start-tunnel.sh), the API is at localhost:8000
# and no VITE_API_BASE_URL is needed.
# If you are connecting directly over the LAN, set VITE_API_BASE_URL accordingly.

set -e

cd "$(dirname "$0")"

# Change this if your server is reachable directly over the network.
# Example: VITE_API_BASE_URL=http://10.65.14.8:8000
VITE_API_BASE_URL="${VITE_API_BASE_URL:-http://localhost:8000}"

echo "Starting frontend with API: $VITE_API_BASE_URL"
npm run dev -- --host
