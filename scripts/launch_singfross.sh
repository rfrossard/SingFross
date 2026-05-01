#!/bin/bash
# SingFross launcher – run this to start the game
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"
exec python3 "$PROJECT_DIR/singfross.py" "$@"
