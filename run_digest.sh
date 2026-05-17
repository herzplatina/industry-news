#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

source "$SCRIPT_DIR/venv/bin/activate"
mkdir -p "$SCRIPT_DIR/logs"
python3 -m src.main >> "$SCRIPT_DIR/logs/digest_$(date +%Y-%m-%d).log" 2>&1
