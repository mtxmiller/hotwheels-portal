#!/bin/bash
# Run the Hot Wheels Portal scanner

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Activate venv and run
source venv/bin/activate
python scanner.py "$@"
