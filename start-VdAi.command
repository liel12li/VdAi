#!/bin/bash
# Double-click on macOS / Linux to launch VdAi.
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
    exec python3 run.py "$@"
else
    exec python run.py "$@"
fi
