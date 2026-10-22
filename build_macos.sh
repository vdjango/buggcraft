#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(uname -s)" != Darwin ]]; then
    echo 'Run this script on macOS (Intel or Apple Silicon).' >&2
    exit 1
fi
iconset="dist/Buggcraft.iconset"
mkdir -p "$iconset"
for size in 16 32 128 256 512; do
    for scale in 1 2; do
        pixels=$((size * scale))
        suffix=''
        [[ "$scale" == 2 ]] && suffix='@2x'
        sips -z "$pixels" "$pixels" resources/icons/1024x1024/app.png --out "$iconset/icon_${size}x${size}${suffix}.png" >/dev/null
    done
done
iconutil -c icns "$iconset" -o resources/icons/app.icns
python3.11 -m venv .build-venv
.build-venv/bin/python -m pip install -r requirements.txt -r requirements-build.txt
.build-venv/bin/python -m pip check
.build-venv/bin/python build.py "$@"
