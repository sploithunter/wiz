#!/bin/bash
# Wiz wake script - entry point for scheduled execution
# Usage: wake.sh <cycle_type>
# cycle_type: dev-cycle | content-cycle | feature-cycle

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIZ_DIR="$(dirname "$SCRIPT_DIR")"
CYCLE_TYPE="${1:-dev-cycle}"
shift || true

# Parse --config flag separately (must precede 'run' in the wiz command)
CONFIG_PATH=""
EXTRA_ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --config)
            CONFIG_PATH="$2"
            shift 2
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

# --- Environment setup for launchd ---
# launchd runs with minimal PATH/env. Source shell profile to get
# API keys and other exports, then ensure essential paths are set.
set +eu
[ -f "$HOME/.zprofile" ] && source "$HOME/.zprofile" 2>/dev/null
[ -f "$HOME/.zshrc" ] && source "$HOME/.zshrc" 2>/dev/null
set -eu
# Ensure essential tool paths (homebrew, pyenv, claude CLI)
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$HOME/.local/bin:$HOME/.pyenv/shims:$HOME/.pyenv/bin:$PATH"
# Load .env file if present (overrides for API keys, tokens)
if [ -f "$WIZ_DIR/.env" ]; then
    set +u; set -a; source "$WIZ_DIR/.env"; set +a; set -u
fi

# Logging
LOG_DIR="$WIZ_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/wake_$(date +%Y%m%d_%H%M%S).log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "=== Wiz Wake: $CYCLE_TYPE ==="

# Check if bridge is running, start if not
BRIDGE_DIR="${CODING_AGENT_BRIDGE_DIR:-$HOME/Documents/coding-agent-bridge}"
BRIDGE_URL="${CODING_AGENT_BRIDGE_URL:-http://127.0.0.1:4003}"
BRIDGE_DATA_DIR="${CODING_AGENT_BRIDGE_DATA_DIR:-$HOME/.cin-interface}"

if ! curl -s "$BRIDGE_URL/health" > /dev/null 2>&1; then
    log "Starting Coding Agent Bridge..."
    cd "$BRIDGE_DIR"
    node bin/cli.js server --data-dir "$BRIDGE_DATA_DIR" &
    BRIDGE_PID=$!
    # Wait up to 15s for bridge to come alive
    for i in $(seq 1 15); do
        if curl -s "$BRIDGE_URL/health" > /dev/null 2>&1; then
            break
        fi
        sleep 1
    done
    if ! curl -s "$BRIDGE_URL/health" > /dev/null 2>&1; then
        log "ERROR: Bridge failed to start after 15s"
        exit 1
    fi
    log "Bridge started (PID: $BRIDGE_PID)"
else
    log "Bridge already running"
    BRIDGE_PID=""
fi

# Stale session cleanup happens automatically inside Wiz's SessionRunner
# on first run (cleanup_stale_sessions). No separate step needed here.

# Ensure wiz is installed from the main repo, not a stale worktree.
# Sub-agents may run `pip install -e .` inside worktrees, which redirects
# the editable install. Re-anchor it every time to be safe.
log "Re-anchoring pip editable install to $WIZ_DIR"
pip3 install -e "$WIZ_DIR" --break-system-packages -q 2>&1 | tee -a "$LOG_FILE" || true

# Run the requested cycle
cd "$WIZ_DIR"
WIZ_CMD=(wiz)
if [ -n "$CONFIG_PATH" ]; then
    WIZ_CMD+=(--config "$CONFIG_PATH")
fi
WIZ_CMD+=(run "$CYCLE_TYPE")
if [ ${#EXTRA_ARGS[@]} -gt 0 ]; then
    WIZ_CMD+=("${EXTRA_ARGS[@]}")
fi
log "Running: ${WIZ_CMD[*]}"
set +e
"${WIZ_CMD[@]}" 2>&1 | tee -a "$LOG_FILE"
EXIT_CODE=${PIPESTATUS[0]}
set -e

log "Cycle complete (exit code: $EXIT_CODE)"

# Cleanup: stop bridge if we started it
if [ -n "${BRIDGE_PID:-}" ]; then
    log "Stopping bridge (PID: $BRIDGE_PID)"
    kill "$BRIDGE_PID" 2>/dev/null || true
fi

log "=== Wiz Wake Complete ==="
exit $EXIT_CODE
