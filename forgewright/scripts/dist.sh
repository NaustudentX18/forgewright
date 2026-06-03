#!/usr/bin/env bash
# Print the right install command(s) for the current platform.
#
# Used by README.md / docs / "how to install" snippets. If you're reading
# this on a friendlier machine than the one in front of you, just look
# at the `case` block — it enumerates every supported platform.
#
# Exit codes:
#   0  — known platform, install commands printed
#   1  — unsupported platform (so CI / packaging can detect it)

set -euo pipefail

os=$(uname -s | tr '[:upper:]' '[:lower:]')
arch=$(uname -m)

# Normalise Apple Silicon and Intel Macs to the same bucket.
case "$arch" in
  x86_64)   arch="x86_64" ;;
  aarch64|arm64) arch="aarch64" ;;
  *)        arch="unknown" ;;
esac

case "$os/$arch" in
  linux/x86_64|linux/aarch64)
    cat <<'EOF'
uv tool install forgewright          # recommended (https://docs.astral.sh/uv/)
pipx install forgewright             # alt (https://pipx.pypa.io/)
docker run --rm ghcr.io/forest/forgewright   # container, no install
EOF
    ;;
  darwin/x86_64|darwin/aarch64)
    cat <<'EOF'
brew install forest/tap/forgewright  # recommended (https://brew.sh/)
uv tool install forgewright          # alt
EOF
    ;;
  *)
    echo "Unsupported: $os/$arch" >&2
    echo "Try one of:" >&2
    echo "  uv tool install forgewright" >&2
    echo "  pipx install forgewright" >&2
    echo "  docker run --rm ghcr.io/forest/forgewright" >&2
    exit 1
    ;;
esac
