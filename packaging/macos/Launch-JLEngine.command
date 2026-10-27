#!/usr/bin/env bash
set -Eeuo pipefail
APP_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$APP_ROOT"

if [[ ! -f .install-complete ]]; then
  ./packaging/macos/install-macos.sh
  touch .install-complete
fi

JULIA=""
if command -v julia >/dev/null 2>&1; then
  JULIA="$(command -v julia)"
elif [[ -x "$HOME/.juliaup/bin/julia" ]]; then
  JULIA="$HOME/.juliaup/bin/julia"
fi
if [[ -z "$JULIA" ]]; then
  echo "Julia was not found. Install Julia/juliaup, then relaunch JL Engine."
  exit 1
fi
exec "$JULIA" --project=. start.jl
