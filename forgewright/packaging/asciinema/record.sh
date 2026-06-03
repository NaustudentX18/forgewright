#!/usr/bin/env bash
# Reproducibly record the forgewright asciinema demo.
#
# Usage:
#   bash packaging/asciinema/record.sh            # write demo.cast
#   bash packaging/asciinema/record.sh --gif      # also render demo.gif (needs `agg`)
#
# Requires:
#   - asciinema (>= 2.0) on $PATH
#   - forgewright installed and runnable (the `uv run` venv is fine)
#   - agg (https://github.com/asciinema/agg) ONLY if you pass --gif

set -euo pipefail

# Resolve repo root regardless of where the script is invoked from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CAST="$SCRIPT_DIR/demo.cast"
GIF="$SCRIPT_DIR/demo.gif"

cd "$REPO_ROOT"

if ! command -v asciinema >/dev/null 2>&1; then
  echo "asciinema not found. Install with one of:" >&2
  echo "  apt-get install -y asciinema" >&2
  echo "  pip  install asciinema"        >&2
  echo "  uv   tool install asciinema"   >&2
  exit 1
fi

if ! command -v forgewright >/dev/null 2>&1; then
  if [[ -x "$REPO_ROOT/.venv/bin/forgewright" ]]; then
    export PATH="$REPO_ROOT/.venv/bin:$PATH"
  else
    echo "forgewright not on PATH. Activate the venv or pip install -e ." >&2
    exit 1
  fi
fi

# Slightly larger terminal so the .cast is readable on the website.
export COLUMNS=100
export LINES=28

echo "Recording $CAST ..."
# --quiet: don't show the "asciinema: recording as ..." banner
# --cols/--rows: pin the terminal geometry
# --idle-time-limit: collapse long idle gaps (e.g. our `sleep 2.0`s)
asciinema rec \
  --quiet \
  --cols "$COLUMNS" \
  --rows "$LINES" \
  --idle-time-limit 1.5 \
  --command "bash $SCRIPT_DIR/demo.sh" \
  --overwrite \
  "$CAST"

echo "Wrote $CAST"

# Optional: render to a GIF.
if [[ "${1:-}" == "--gif" ]]; then
  if ! command -v agg >/dev/null 2>&1; then
    echo "agg not found on PATH. Install from https://github.com/asciinema/agg" >&2
    echo "  cargo install --git https://github.com/asciinema/agg" >&2
    echo "  # or download a pre-built binary from the releases page." >&2
    exit 1
  fi
  echo "Rendering $GIF ..."
  agg --font-size 14 --speed 1.2 "$CAST" "$GIF"
  echo "Wrote $GIF"
fi
