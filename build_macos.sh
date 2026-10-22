#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(uname -s)" != Darwin ]]; then
    echo 'Run this script on macOS (Intel or Apple Silicon).' >&2
    exit 1
fi
python3.11 -m venv .build-venv
.build-venv/bin/python -m pip install -r requirements.txt -r requirements-build.txt
.build-venv/bin/python -m pip check
.build-venv/bin/python build.py "$@"
