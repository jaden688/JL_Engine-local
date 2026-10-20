#!/usr/bin/env bash
# SparkByte / JL Engine launcher for Linux and macOS.
# Finds Julia, boots the engine, waits for health, opens the console.
# The Windows twin of this script is SparkByte.exe.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

HEALTH_URL="http://127.0.0.1:8081/health"
UI_URL="http://localhost:8081/"
OPEN_BROWSER=1
[[ "${1:-}" == "--no-browser" ]] && OPEN_BROWSER=0

echo "=== SparkByte / JL Engine launcher ==="
echo "Root: $ROOT"

open_url() {
  if command -v xdg-open >/dev/null 2>&1; then xdg-open "$1" >/dev/null 2>&1 || true
  elif command -v open   >/dev/null 2>&1; then open "$1"        >/dev/null 2>&1 || true
  else echo "Open your browser to: $1"; fi
}

# Already running? Just open the console.
if curl -sf --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
  echo "Engine already running on 127.0.0.1:8081 — opening console."
  [[ $OPEN_BROWSER == 1 ]] && open_url "$UI_URL"
  exit 0
fi

# Locate Julia: $SPARKBYTE_JULIA override, then PATH, then juliaup.
JULIA=""
if [[ -n "${SPARKBYTE_JULIA:-}" && -x "${SPARKBYTE_JULIA:-}" ]]; then
  JULIA="$SPARKBYTE_JULIA"
elif command -v julia >/dev/null 2>&1; then
  JULIA="$(command -v julia)"
elif [[ -x "$HOME/.juliaup/bin/julia" ]]; then
  JULIA="$HOME/.juliaup/bin/julia"
fi

if [[ -z "$JULIA" ]]; then
  echo
  echo "Julia is not installed — SparkByte's engine runs on it."
  echo "Install it with juliaup:"
  echo "    curl -fsSL https://install.julialang.org | sh"
  echo "or from https://julialang.org/downloads — then run ./sparkbyte.sh again."
  exit 1
fi
echo "Julia: $JULIA"

# Python is optional (browsing / MCP bridge). Engine boots without it.
if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
  echo "Note: Python 3 not found — browsing tools will be disabled (engine still runs)."
fi

# Use the precompiled sysimage when present — ~5s boots instead of minutes.
JL_ARGS=(--project=. sparkbyte.jl)
if [[ -f "$ROOT/sparkbyte.sysimage.so" ]]; then
  JL_ARGS=(-J sparkbyte.sysimage.so --project=. sparkbyte.jl)
  echo "Sysimage: sparkbyte.sysimage.so (fast boot)"
fi

echo "Booting engine (first run installs Julia packages — can take a few minutes)..."
SPARKBYTE_LAUNCH_BROWSER=0 "$JULIA" "${JL_ARGS[@]}" &
ENGINE_PID=$!

# Poll health for up to ~15 min; bail if the engine dies first.
for i in $(seq 1 450); do
  if ! kill -0 "$ENGINE_PID" 2>/dev/null; then
    echo "Engine process exited before becoming healthy."
    wait "$ENGINE_PID" 2>/dev/null || true
    exit 1
  fi
  if curl -sf --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
    echo
    echo "Engine is up: $UI_URL"
    [[ $OPEN_BROWSER == 1 ]] && open_url "$UI_URL"
    break
  fi
  (( i % 15 == 0 )) && echo "  ...still booting ($(( i * 2 ))s)"
  sleep 2
done

wait "$ENGINE_PID"
