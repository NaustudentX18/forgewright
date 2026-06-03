#!/usr/bin/env bash
# Build sdist + wheel for the current platform.
set -euo pipefail
cd "$(dirname "$0")/.."
uv build --out-dir dist/
ls -lh dist/
