#!/usr/bin/env bash
set -euo pipefail

# Start Xvfb for headful Chrome
Xvfb :99 -screen 0 1280x720x24 -nolisten tcp &
export DISPLAY=:99

# Wait for Xvfb to be ready
for i in $(seq 1 20); do
    if xdpyinfo -display :99 >/dev/null 2>&1; then
        break
    fi
    sleep 0.1
done

exec uv run python -m collector "$@"
