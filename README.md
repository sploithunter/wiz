# Wiz

Persistent, self-improving personal AI agent that orchestrates sub-agents for continuous development, content creation, and project management.

Wiz runs on a schedule via launchd, spawning AI coding agents (Claude Code, Codex) through the [Coding Agent Bridge](https://github.com/jasonjmcghee/coding-agent-bridge) to perform automated development tasks across multiple repositories.

## How It Works

Wiz operates through **cycles** — scheduled pipelines that coordinate multiple AI agents:

### Dev Cycle

The core loop: find bugs, fix them, review the fixes.

```
Bug Hunt (Codex)  →  Bug Fix (Claude)  →  Review (Codex)
     │                     │                    │
     ▼                     ▼                    ▼
  Creates              Picks up            Reviews fixes,
  GitHub issues        issues by           creates PRs or
  labeled              priority,           sends back for
  "wiz-bug"            fixes in            rework
                       worktrees
```

**Issue lifecycle via GitHub labels:**
- `wiz-bug` — New bug found by hunter
- `needs-fix` — Sent back from review for rework
- `needs-review` — Fix applied, awaiting review
- `fix-stalled` — Circuit breaker triggered (no progress)
- `escalated-to-human` — Max review cycles reached, needs human

### Feature Cycle

Two-phase with a human gate:

1. **Propose** — Agent creates `feature-candidate` issues with design details
2. **Implement** — After human approval (label changed to `feature-approved`), agent implements the feature

### Content Cycle

1. **Blog Writer** — Proposes topics or writes full drafts, uses long-term memory to avoid repeating topics
2. **Social Manager** — Creates Typefully drafts via MCP tools for scheduled social posting

## Coordination

Multiple safety mechanisms prevent agents from stepping on each other:

| Mechanism | What It Does |
|-----------|-------------|
| **File locks** | Per-issue locks with TTL prevent two agents from fixing the same issue |
| **Label state machine** | Issues transition through labels; agents only pick up issues matching their phase |
| **Duplicate detection** | Bug hunter receives existing issues in its prompt to avoid duplicates |
| **Stagnation detector** | Circuit-breaks after N consecutive no-change attempts |
| **Loop tracker** | Caps fix→review cycles per issue (default 3), then escalates to human |
| **Strike tracker** | Tracks per-issue and per-file failure counts for escalation |
| **Worktrees** | Each fix runs in an isolated git worktree to avoid conflicts |

## Agents

| Agent | Model | Role |
|-------|-------|------|
| Bug Hunter | Codex | Scans repos for bugs, creates prioritized GitHub issues (P0-P4) |
| Bug Fixer | Claude | Fixes bugs in worktrees, writes regression tests, commits |
| Reviewer | Codex | Reviews fixes, approves (creates PR) or rejects (sends back) |
| Feature Proposer | Claude | Proposes features or implements approved ones |
| Blog Writer | Claude | Writes technical blog posts from project context |
| Social Manager | Claude | Creates social media drafts via Typefully |

Each agent has its own `CLAUDE.md` instruction file in `agents/<agent-name>/`.

## Setup

### Prerequisites

- Python >= 3.10
- [Coding Agent Bridge](https://github.com/jasonjmcghee/coding-agent-bridge) running (`node bin/cli.js server`)
- GitHub CLI (`gh`) authenticated
- Claude Code and/or Codex CLI installed

### Install

```bash
pip install -e ".[dev]"
```

### Configure

Edit `config/wiz.yaml`:

```yaml
repos:
  - name: "my-repo"
    path: "/path/to/repo"
    github: "owner/repo"
    enabled: true

agents:
  bug_hunter:
    model: "codex"
    max_issues_per_run: 10
  bug_fixer:
    model: "claude"
    max_fixes_per_run: 5
  reviewer:
    model: "codex"
    max_reviews_per_run: 10
```

See `src/wiz/config/schema.py` for all available options.

## Usage

### Run cycles manually

```bash
# Full dev cycle for all repos
wiz run dev-cycle

# Dev cycle for a specific repo
wiz run dev-cycle --repo my-repo

# Single phase only
wiz run dev-cycle --phase bug_hunt

# Content cycle (blog + social)
wiz run content-cycle

# Feature cycle
wiz run feature-cycle
```

### Check status

```bash
wiz status
```

### Schedule via launchd

```bash
# Install schedules from config
wiz schedule install

# Check installed schedules
wiz schedule status

# Remove all schedules
wiz schedule uninstall
```

Schedules are defined in `config/wiz.yaml` under the `schedule` key. The scheduler generates launchd plists with `StartCalendarInterval` entries and installs them in `~/Library/LaunchAgents/`.

**Minimum 2-hour spacing between runs.** Agent sessions (Claude up to ~40min, Codex up to ~75min) plus pipeline overhead means a single run can take up to 110 minutes. Never schedule runs less than 2 hours apart.

Phases can be scheduled independently for better staggering:

```yaml
schedule:
  bug_hunt:   # odd hours
    times: ["07:00", "09:00", "11:00", "13:00", "15:00"]
    days: ["mon", "tue", "wed", "thu", "fri"]
  bug_fix:    # even hours
    times: ["08:00", "10:00", "12:00", "14:00", "16:00"]
    days: ["mon", "tue", "wed", "thu", "fri"]
  review:     # odd hours (after bug_fix)
    times: ["09:00", "11:00", "13:00", "15:00", "17:00"]
    days: ["mon", "tue", "wed", "thu", "fri"]
```

When per-phase schedules (`bug_hunt`, `bug_fix`, `review`) are present, they override the combined `dev_cycle` schedule. This staggers the work so bug_hunt finds issues, bug_fix picks them up next hour, and review follows the hour after.

The `scripts/wake.sh` entry point handles launchd's minimal environment by sourcing shell profiles and setting up PATH, API keys, and pyenv. It also re-anchors the `pip install -e` to the main repo on every launch (sub-agents may redirect it from worktrees).

### Logging

```bash
# Debug logging
wiz --log-level DEBUG run dev-cycle

# JSON structured logs
wiz --json-logs run dev-cycle
```

Log files:
- Wake script: `logs/wake_YYYYMMDD_HHMMSS.log`
- Session logs: `memory/sessions/session_*.log`
- Bridge events: `~/.cin-interface/data/events.jsonl`

## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│   launchd    │────▶│   wake.sh        │────▶│   wiz CLI   │
│  (schedule)  │     │  (env setup)     │     │  (Click)    │
└─────────────┘     └──────────────────┘     └──────┬──────┘
                                                     │
                                              ┌──────▼──────┐
                                              │  Pipeline    │
                                              │  Orchestrator│
                                              └──────┬──────┘
                                                     │
                          ┌──────────────────────────┼──────────────────┐
                          │                          │                  │
                    ┌─────▼─────┐            ┌───────▼──────┐   ┌──────▼─────┐
                    │ Bug Hunter│            │  Bug Fixer   │   │  Reviewer  │
                    │  (Codex)  │            │  (Claude)    │   │  (Codex)   │
                    └─────┬─────┘            └───────┬──────┘   └──────┬─────┘
                          │                          │                  │
                    ┌─────▼──────────────────────────▼──────────────────▼─────┐
                    │              Coding Agent Bridge (REST + WebSocket)     │
                    │              tmux sessions + hook-based event detection │
                    └────────────────────────────────────────────────────────┘
```

### Bridge Integration

The bridge manages tmux sessions where Claude Code / Codex run. Wiz communicates via:

- **REST API** — Create sessions, send prompts, check status
- **WebSocket** — Real-time event streaming for completion detection
- **Hooks** — Claude Code hooks fire events to `~/.cin-interface/data/events.jsonl`, which the bridge watches and broadcasts

`ensure_hooks()` in `runner.py` installs hooks into both global (`~/.claude/settings.json`) and project-level (`.claude/settings.local.json`) configs before each session, ensuring event detection works even if other Claude Code instances modify global settings.

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/

# Run linter
ruff check src/ tests/

# Run type checker
mypy src/wiz/
```

## Safety

- **PRs are never auto-merged** — Human review required for all changes
- **Three-strike escalation** — Issues that fail repeatedly get escalated with Telegram alerts
- **Self-improvement guard** — When Wiz works on its own repo, protected files (`config/wiz.yaml`, `CLAUDE.md`, `schema.py`, `escalation.py`) require human PR approval
- **File locking** — Prevents concurrent modification conflicts
- **Stagnation circuit breaker** — Stops agents that aren't making progress
- **Loop cap** — Fix-review cycles are capped to prevent infinite loops

## Project Structure

```
src/wiz/
├── agents/          # Agent implementations
│   ├── base.py      # BaseAgent ABC
│   ├── bug_hunter.py
│   ├── bug_fixer.py
│   ├── reviewer.py
│   ├── feature_proposer.py
│   ├── blog_writer.py
│   └── social_manager.py
├── bridge/          # Coding Agent Bridge client
│   ├── client.py    # REST client
│   ├── monitor.py   # WebSocket event monitor
│   ├── runner.py    # Session lifecycle + hooks
│   └── types.py     # SessionResult, etc.
├── config/          # Configuration
│   ├── schema.py    # Pydantic models
│   └── loader.py    # YAML loader
├── coordination/    # Multi-agent coordination
│   ├── github_issues.py
│   ├── github_prs.py
│   ├── file_lock.py
│   ├── worktree.py
│   ├── strikes.py
│   ├── loop_tracker.py
│   └── stagnation.py
├── memory/          # Agent memory
│   ├── short_term.py
│   ├── long_term.py
│   └── session_log.py
├── notifications/   # Alerting
│   └── telegram.py
└── orchestrator/    # Pipeline execution
    ├── pipeline.py
    ├── content_pipeline.py
    ├── scheduler.py
    ├── escalation.py
    ├── reporter.py
    └── state.py
```
