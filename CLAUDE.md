# Wiz - Development Guide

## Project Overview
Wiz is a persistent, self-improving personal AI agent that orchestrates sub-agents
for continuous development, content creation, and project management.

## Architecture
- **Python 3.10+** with hatchling build system
- **Pydantic v2** for configuration validation
- **Click** for CLI
- Agents run via **Coding Agent Bridge** (REST + WebSocket)
- Coordination via **GitHub issues** and **git worktrees**
- Scheduling via **launchd**

## Key Directories
- `src/wiz/` - Main package
- `src/wiz/agents/` - Agent implementations (bug_hunter, bug_fixer, reviewer, etc.)
- `src/wiz/bridge/` - Bridge client, monitor, and runner
- `src/wiz/config/` - Configuration schema and loader
- `src/wiz/coordination/` - GitHub, worktrees, locks, strikes
- `src/wiz/memory/` - Short-term, long-term, session logging
- `src/wiz/notifications/` - Telegram notifications
- `src/wiz/orchestrator/` - Pipeline, scheduler, escalation, reporter
- `agents/` - Per-agent CLAUDE.md instruction files
- `config/wiz.yaml` - Main configuration
- `tests/` - Test suite (unit, integration, e2e)

## Development
```bash
pip install -e ".[dev]"
pytest tests/ -v
ruff check src/
```

## Testing
- All changes must include tests
- Run `pytest tests/` before committing — **never commit with failing tests**
- Integration tests are marked `@pytest.mark.integration`
- E2E tests are marked `@pytest.mark.e2e`

## Worktree Safety
- Sub-agents run inside `.worktrees/<type>-<issue>/` and may run `pip install -e .`, which redirects the system-wide editable install to the worktree. This is expected — `scripts/wake.sh` re-anchors the install to the main repo on every launch.
- Do not modify files outside your worktree's scope.

## Configuration
All settings in `config/wiz.yaml`. See `src/wiz/config/schema.py` for all options.

## Protected Files (Self-Improvement)
When Wiz runs dev cycles on itself, these files require human PR approval:
- `config/wiz.yaml`
- `CLAUDE.md`
- `agents/*/CLAUDE.md`
- `src/wiz/orchestrator/escalation.py`
- `src/wiz/config/schema.py`

---

## Operations & Debugging

### Coding Agent Bridge

The bridge is a Node.js server that manages tmux sessions for Claude Code / Codex.

**Location:** `/Users/jason/Documents/coding-agent-bridge`

**Start the bridge:**
```bash
cd /Users/jason/Documents/coding-agent-bridge
node bin/cli.js server          # default port 4003
node bin/cli.js server --debug  # verbose logging
```

**DO NOT** use `npm start` or `node dist/index.js` - those don't work. The correct
entry point is `node bin/cli.js server`.

**Health check:**
```bash
curl http://127.0.0.1:4003/health
# {"status":"ok","clients":0,"sessions":0}
```

**API reference:** See `/Users/jason/Documents/coding-agent-bridge/API.md` for the
complete REST + WebSocket API contract.

### Stale Session Cleanup

On startup, `SessionRunner.cleanup_stale_sessions()` automatically deletes all
sessions from the bridge. Any sessions left over from a previous Wiz run have no
backing tmux processes and are guaranteed stale. This runs once per runner instance.

You can also manually clean up:
```bash
# List all sessions
curl http://127.0.0.1:4003/sessions | python3 -m json.tool

# Delete a specific session
curl -X DELETE http://127.0.0.1:4003/sessions/<session-id>
```

### Session Lifecycle

1. Bridge creates a tmux session (named `bridge-<short-id>`)
2. Agent (claude/codex) starts inside the tmux pane
3. Claude Code hooks fire events to `~/.cin-interface/data/events.jsonl`
4. Bridge watches events.jsonl, correlates events to sessions
5. Events are broadcast via WebSocket to connected clients
6. Stop event = agent finished responding to the prompt

### Debugging a Stuck Session

```bash
# Check tmux sessions
tmux list-sessions

# See what's in a specific tmux pane
tmux capture-pane -t bridge-<id> -p

# Check if hooks are working
tail -f ~/.cin-interface/data/events.jsonl | python3 -m json.tool

# Check bridge logs (if started with --debug)
# Bridge logs to stdout

# Force-kill all tmux sessions (nuclear option)
tmux kill-server
```

### Hook Script

Location: `~/.cin-interface/hooks/coding-agent-hook.sh`

This script is called by Claude Code for every tool use, stop, session start/end, etc.
It normalizes events to JSON and appends to `~/.cin-interface/data/events.jsonl`.

**macOS caveat:** `date +%s%3N` doesn't work on macOS (outputs literal "N").
The hook uses `python3 -c 'import time; print(int(time.time()*1000))'` as a fallback.

### WebSocket Events for Completion Detection

Wiz monitors for these event types to detect when an agent is done:
- `stop` - Agent finished responding
- `session_end` - Session ended

Events arrive as: `{"type": "event", "data": {"type": "stop", ...}}`

The monitor also polls `GET /sessions/:id` for status changes to `idle` or `offline`
as a backup detection mechanism.

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Session created but times out | tmux pane didn't start agent | Check `tmux capture-pane`, verify claude is installed |
| No WebSocket events | Hook script not installed | Check `~/.claude/settings.json` for hooks config |
| `gh` commands fail | Label doesn't exist | `ensure_labels()` handles this automatically |
| Bridge health check fails | Bridge not running | `node bin/cli.js server` from bridge dir |
| 151 stale sessions | Previous crash without cleanup | Runner auto-cleans on startup |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CODING_AGENT_BRIDGE_DIR` | `~/Documents/coding-agent-bridge` | Bridge install path |
| `CODING_AGENT_BRIDGE_URL` | `http://127.0.0.1:4003` | Bridge API URL |
| `CODING_AGENT_BRIDGE_DATA_DIR` | `~/.cin-interface` | Hook data directory |

### Running Wiz

```bash
# Single dev cycle (all enabled repos)
wiz run dev-cycle

# Single repo only
wiz run dev-cycle --repo wiz

# Content cycle (blog + social)
wiz run content-cycle

# Feature cycle
wiz run feature-cycle

# Check status
wiz status

# Install/uninstall launchd schedules
wiz schedule install
wiz schedule uninstall
wiz schedule status
```

### Log Files

- Wake script logs: `logs/wake_YYYYMMDD_HHMMSS.log`
- Session logs: `memory/sessions/session_*.log`
- Bridge events: `~/.cin-interface/data/events.jsonl`
- Use `--json-logs` flag for structured JSON log output
- Use `--log-level debug` for verbose logging
