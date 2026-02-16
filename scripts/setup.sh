#!/bin/bash
# Wiz setup script - one-time installation and configuration
# Usage: ./scripts/setup.sh
#
# Checks/installs: Python deps, Node.js, coding-agent-bridge, gh CLI,
# tmux, directory structure, hook script, Google Docs credentials.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIZ_DIR="$(dirname "$SCRIPT_DIR")"

# Colors (disabled if not a terminal)
if [ -t 1 ]; then
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    RED='\033[0;31m'
    BLUE='\033[0;34m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    GREEN='' YELLOW='' RED='' BLUE='' BOLD='' NC=''
fi

ok()   { echo -e "  ${GREEN}✓${NC} $*"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $*"; }
fail() { echo -e "  ${RED}✗${NC} $*"; }
info() { echo -e "  ${BLUE}→${NC} $*"; }
header() { echo -e "\n${BOLD}$*${NC}"; }

ERRORS=0

# ─── Python ───────────────────────────────────────────────────────────

header "1. Python"

if command -v python3 &>/dev/null; then
    PY_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
        ok "Python $PY_VERSION"
    else
        fail "Python $PY_VERSION found, but 3.10+ is required"
        ERRORS=$((ERRORS + 1))
    fi
else
    fail "python3 not found — install Python 3.10+"
    ERRORS=$((ERRORS + 1))
fi

if command -v pip3 &>/dev/null; then
    ok "pip3 available"
else
    fail "pip3 not found"
    ERRORS=$((ERRORS + 1))
fi

# ─── Node.js ──────────────────────────────────────────────────────────

header "2. Node.js (for coding-agent-bridge)"

if command -v node &>/dev/null; then
    NODE_VERSION=$(node --version 2>&1)
    ok "Node.js $NODE_VERSION"
else
    fail "node not found — install Node.js 18+ (https://nodejs.org)"
    ERRORS=$((ERRORS + 1))
fi

if command -v npm &>/dev/null; then
    ok "npm available"
else
    warn "npm not found — needed for bridge setup"
fi

# ─── CLI tools ────────────────────────────────────────────────────────

header "3. CLI tools"

if command -v gh &>/dev/null; then
    ok "GitHub CLI (gh)"
else
    fail "gh not found — install: brew install gh"
    ERRORS=$((ERRORS + 1))
fi

if command -v tmux &>/dev/null; then
    ok "tmux"
else
    fail "tmux not found — install: brew install tmux"
    ERRORS=$((ERRORS + 1))
fi

if command -v claude &>/dev/null; then
    ok "Claude CLI"
else
    warn "claude not found — needed for Claude-based agents"
fi

# ─── Directory structure ──────────────────────────────────────────────

header "4. Directory structure"

mkdir -p ~/.wiz
ok "~/.wiz/"

mkdir -p ~/.cin-interface/hooks
mkdir -p ~/.cin-interface/data
ok "~/.cin-interface/hooks/ and data/"

mkdir -p "$WIZ_DIR/logs"
ok "$WIZ_DIR/logs/"

# ─── Install Python package ──────────────────────────────────────────

header "5. Python dependencies"

info "Installing wiz with dev dependencies..."
if pip3 install --break-system-packages -e "$WIZ_DIR[dev]" -q 2>&1; then
    ok "wiz installed (editable mode)"
else
    fail "pip3 install failed"
    ERRORS=$((ERRORS + 1))
fi

# Verify import
if python3 -c "import wiz; print(f'wiz {wiz.__version__}')" 2>/dev/null; then
    ok "wiz importable"
else
    fail "wiz import failed after install"
    ERRORS=$((ERRORS + 1))
fi

# ─── Coding Agent Bridge ─────────────────────────────────────────────

header "6. Coding Agent Bridge"

BRIDGE_DIR="${CODING_AGENT_BRIDGE_DIR:-$HOME/Documents/coding-agent-bridge}"

if [ -d "$BRIDGE_DIR" ]; then
    ok "Bridge repo found at $BRIDGE_DIR"
    if [ -d "$BRIDGE_DIR/node_modules" ]; then
        ok "node_modules present"
    else
        info "Running npm install in bridge..."
        (cd "$BRIDGE_DIR" && npm install --silent 2>&1) && ok "npm install complete" || warn "npm install had issues"
    fi
    if [ -f "$BRIDGE_DIR/bin/cli.js" ]; then
        ok "Bridge entry point (bin/cli.js) exists"
    else
        fail "bin/cli.js not found — bridge may need rebuild"
    fi
else
    warn "Bridge not found at $BRIDGE_DIR"
    info "Clone it: git clone https://github.com/sploithunter/coding-agent-bridge.git $BRIDGE_DIR"
    info "Then run: cd $BRIDGE_DIR && npm install"
fi

# ─── Hook script ──────────────────────────────────────────────────────

header "7. Hook script"

HOOK_SCRIPT="$HOME/.cin-interface/hooks/coding-agent-hook.sh"
if [ -f "$HOOK_SCRIPT" ]; then
    ok "Hook script exists at $HOOK_SCRIPT"
else
    warn "Hook script not found at $HOOK_SCRIPT"
    info "The bridge should create this on first run."
    info "If not, check the bridge README for hook setup."
fi

# ─── Config ───────────────────────────────────────────────────────────

header "8. Configuration"

CONFIG_FILE="$WIZ_DIR/config/wiz.yaml"
if [ -f "$CONFIG_FILE" ]; then
    ok "Config file: $CONFIG_FILE"
else
    warn "No config file found"
    info "Create a config file at $CONFIG_FILE (see src/wiz/config/schema.py for options)"
fi

# ─── Google Docs (optional) ──────────────────────────────────────────

header "9. Google Docs (optional)"

GOOGLE_CREDS="$HOME/.wiz/google-credentials.json"
GOOGLE_TOKEN="$HOME/.wiz/google-token.json"

if [ -f "$GOOGLE_CREDS" ]; then
    ok "Google credentials file found"

    if [ -f "$GOOGLE_TOKEN" ]; then
        ok "Google token exists (already authorized)"
    else
        info "Credentials found but not yet authorized."
        echo ""
        read -rp "  Run Google Docs authorization now? [y/N] " REPLY
        if [[ "$REPLY" =~ ^[Yy]$ ]]; then
            info "Opening browser for Google OAuth consent..."
            wiz google-auth && ok "Google Docs authorized" || fail "Google Docs authorization failed"
        else
            info "Skipped. Run 'wiz google-auth' later to authorize."
        fi
    fi
else
    info "No Google credentials found at $GOOGLE_CREDS"
    info "To enable Google Docs integration:"
    info "  1. See docs/google-docs-setup.md for full guide"
    info "  2. Download OAuth Desktop credentials from Google Cloud Console"
    info "  3. Save to $GOOGLE_CREDS"
    info "  4. Run: wiz google-auth"
fi

# ─── Environment variables ────────────────────────────────────────────

header "10. Environment variables"

check_env() {
    local var="$1" required="$2" desc="$3"
    if [ -n "${!var:-}" ]; then
        ok "$var is set"
    elif [ "$required" = "required" ]; then
        fail "$var not set — $desc"
        ERRORS=$((ERRORS + 1))
    else
        info "$var not set — $desc (optional)"
    fi
}

check_env "GITHUB_TOKEN" "optional" "needed for gh CLI auth (or use 'gh auth login')"
check_env "TYPEFULLY_API_KEY" "optional" "needed for Typefully social posting"

# ─── Bridge health check ─────────────────────────────────────────────

header "11. Bridge connectivity"

BRIDGE_URL="${CODING_AGENT_BRIDGE_URL:-http://127.0.0.1:4003}"

if curl -s "$BRIDGE_URL/health" > /dev/null 2>&1; then
    ok "Bridge is running at $BRIDGE_URL"
else
    info "Bridge is not running (start with: node $BRIDGE_DIR/bin/cli.js server --data-dir ~/.cin-interface)"
fi

# ─── Tests ────────────────────────────────────────────────────────────

header "12. Test suite"

info "Running tests..."
if python3 -m pytest "$WIZ_DIR/tests/" -q --tb=line 2>&1 | tail -3; then
    ok "Tests complete"
else
    warn "Some tests failed (see output above)"
fi

# ─── Summary ──────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ "$ERRORS" -eq 0 ]; then
    echo -e "${GREEN}${BOLD}  Setup complete — no critical issues found.${NC}"
else
    echo -e "${YELLOW}${BOLD}  Setup complete with $ERRORS issue(s) to resolve.${NC}"
fi
echo ""
echo "  Next steps:"
echo "    1. Start the bridge:  node $BRIDGE_DIR/bin/cli.js server --data-dir ~/.cin-interface"
echo "    2. Run a dev cycle:   wiz run dev-cycle"
echo "    3. Run content:       wiz run content-cycle"
echo "    4. Install schedules: wiz schedule install"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
