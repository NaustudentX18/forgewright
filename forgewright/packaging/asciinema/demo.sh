#!/usr/bin/env bash
# Source-of-truth demo for the asciinema recording at packaging/asciinema/demo.cast.
#
# This script types out (with realistic pauses) the commands a first-time user
# runs to see what forgewright does. The recording driver is `record.sh`,
# which wraps this script in `asciinema rec`.
#
# To run interactively (no recording):
#   bash packaging/asciinema/demo.sh
#
# To re-record:
#   bash packaging/asciinema/record.sh
#
# NOTE: We deliberately do NOT use `set -o pipefail`. Many of the lines below
# are `cmd | head -N`; once `head` exits, the upstream process gets SIGPIPE
# and a non-zero exit code, which would otherwise abort the demo.

# Abort on unset variables and on errors in the *current* command (not pipes).
set -eu

# Make the terminal legible. The defaults below are also what `record.sh`
# sets via the `asciinema rec --cols/--rows` flags so the .cast renders
# correctly on the website.
export FORGEWRIGHT_PROVIDER=stub
export FORGEWRIGHT_MODEL=stub-model
export PYTHONUNBUFFERED=1
# Suppress loguru's INFO/WARNING chatter so only the rich panel reaches the
# terminal — the demo is about *what the user sees*, not what we log.
export LOGURU_LEVEL=ERROR

clear
printf '\n'
printf '  forgewright — an open-source, CLI-first AI agent framework.\n'
printf '  https://github.com/forest/forgewright\n'
printf '\n'
sleep 1.2

# 1) Version check -----------------------------------------------------------
printf '$ forgewright --version\n'
forgewright --version
sleep 1.5

# 2) Help (truncated to keep the demo short) --------------------------------
printf '\n$ forgewright --help\n'
# `|| true` defends against SIGPIPE from `head` closing the pipe.
forgewright --help 2>&1 | head -20 || true
sleep 1.2

# 3) Build (stub provider) ---------------------------------------------------
printf '\n$ forgewright build "say hi"\n'
sleep 0.4
forgewright build "say hi" || true
sleep 1.6

# 4) A second build, slightly more interesting ------------------------------
printf '\n$ forgewright build "what is 2 + 2?"\n'
sleep 0.4
forgewright build "what is 2 + 2?" || true
sleep 1.6

# 5) The REPL — pipe a small script so the recording is deterministic. ----
#    `forgewright` with no args drops into the prompt-toolkit REPL.
#    We feed it /help and /exit and let the renderer draw the table.
printf '\n$ forgewright\n'
sleep 0.4
printf '/help\n/exit\n' | forgewright || true
sleep 1.5

# 6) Final CTA ---------------------------------------------------------------
printf '\n'
printf '  Install:\n'
printf '    pipx install forgewright\n'
printf '    brew  install forest/tap/forgewright\n'
printf '    docker run --rm ghcr.io/forest/forgewright\n'
printf '\n'
printf '  -> https://github.com/forest/forgewright\n'
printf '\n'
sleep 2.0
