#!/usr/bin/env bash
# Nova Console Unix Launcher (macOS / Linux)
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "Checking Python environment..."
if ! command -v python3 &> /dev/null; then
    echo "Python 3 is required but not found in PATH."
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment (.venv)..."
    python3 -m venv .venv
    source .venv/bin/activate
    echo "Installing requirements..."
    pip install -r requirements.txt
else
    source .venv/bin/activate
fi

python3 launch.py

