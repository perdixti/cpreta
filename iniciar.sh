#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then
    exec .venv/bin/python start_background.py "$@"
fi
exec python3 start_background.py "$@"
