#!/usr/bin/env bash
set -Eeuo pipefail
APP_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$APP_ROOT"
if [[ ! -f .install-complete ]]; then
  ./packaging/macos/install-macos.sh
  touch .install-complete
fi
exec ./sparkbyte.sh
