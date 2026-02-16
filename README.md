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
- `wiz-claimed-by-{machine_id}` — Distributed lock claim (multi-machine)
- `fix-stalled` — Circuit breaker triggered (no progress)
- `escalated-to-human` — Max review cycles reached, needs human

### Feature Cycle

Automated propose→approve→implement workflow:

1. **Propose** — Agent creates `feature-candidate` issues with design details
2. **Approve** — Human approves via `feature-approved` label (Telegram notification sent), or auto-approves when `require_approval: false`
3. **Implement** — Agent implements in a worktree, pushes, labels `feature-implemented`

**Label lifecycle:** `feature-candidate` → `feature-approved` → `feature-implemented`

### Content Cycle

1. **Blog Writer** — Two-phase with automatic mode transition:
   - **Propose mode** — Analyzes recent project activity (session logs + GitHub issues/comments) and proposes a topic, stored in long-term memory
   - **Write mode** — On next run, picks up the pending topic and writes a full draft
   - Creates Google Docs for review (when configured) or saves to local markdown
   - Image generation prompts included in output
2. **Social Manager** — Creates Typefully drafts for X and LinkedIn, with companion Google Docs and image prompts

## Coordination

Multiple safety mechanisms prevent agents from stepping on each other:

| Mechanism | What It Does |
|-----------|-------------|
| **Distributed locks** | GitHub labels (`wiz-claimed-by-{machine_id}`) prevent multiple machines from picking up the same issue |
| **File locks** | Per-issue locks with TTL prevent two agents on the same machine from fixing the same issue |
| **Label state machine** | Issues transition through labels; agents only pick up issues matching their phase |
| **Duplicate detection** | Bug hunter receives existing issues in its prompt to avoid duplicates |
| **Stagnation detector** | Checks actual `git diff` for file changes; circuit-breaks when no progress detected |
| **Loop tracker** | Caps fix→review cycles per issue (default 3), then escalates to human |
| **Strike tracker** | Tracks per-issue and per-file failure counts for escalation |
| **Worktrees** | Each fix runs in an isolated git worktree to avoid conflicts |

## Agents

| Agent | Model | Role |
|-------|-------|------|
| Bug Hunter | Codex | Scans repos for bugs, creates prioritized GitHub issues (P0-P4) |
| Bug Fixer | Claude | Fixes bugs in worktrees (sequential or parallel), writes regression tests |
| Reviewer | Codex | Reviews fixes with structured JSON or keyword verdict parsing, creates PRs or sends back |
| Feature Proposer | Claude | Proposes features, auto-approves or notifies via Telegram, implements in worktrees |
| Blog Writer | Claude | Two-phase: proposes topics from project activity, writes drafts with Google Docs integration |
| Social Manager | Claude | Creates social media drafts via Typefully REST API for X + LinkedIn |

Each agent has its own `CLAUDE.md` instruction file in `agents/<agent-name>/`.

## Setup

### Prerequisites

- Python >= 3.10
- [Coding Agent Bridge](https://github.com/jasonjmcghee/coding-agent-bridge) running (`node bin/cli.js server`)
- GitHub CLI (`gh`) authenticated
- Claude Code and/or Codex CLI installed

### Install

```bash
# Quick setup (installs deps, configures hooks, creates dirs)
./scripts/setup.sh

# Or manually
pip install -e ".[dev]"
```

### Configure

Edit `config/wiz.yaml`:

```yaml
global:
  machine_id: "macbook-1"  # Enables distributed locking across machines

repos:
  - name: "my-repo"
    path: "/path/to/repo"
    github: "owner/repo"
    enabled: true
    self_improve: false  # Set true for Wiz's own repo

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
  feature_proposer:
    require_approval: true  # false = auto-approve candidates
    auto_propose_features: true
  blog_writer:
    auto_propose_topics: true
    context_sources:
      session_logs: true
      github_activity: true
      exclude_repos: ["genesis"]  # Substring match — excludes all matching repos

dev_cycle:
  parallel_fixes: false  # true = fix multiple issues concurrently via ThreadPoolExecutor

google_docs:
  enabled: false  # Set true + run `wiz google-auth` for Google Docs integration
```

See `src/wiz/config/schema.py` for all available options.

## Usage

### Global CLI Options

```bash
# Use a custom config file
wiz --config /path/to/wiz.yaml run dev-cycle

# Override log level (overrides config file setting)
wiz --log-level DEBUG run dev-cycle

# JSON structured logs
wiz --json-logs run dev-cycle
```

The `--config` (`-c`) flag specifies a custom config path. When used with `wiz schedule install`, the generated launchd plists pass this path through to `wake.sh`, so scheduled runs use the correct config. The `wiz_dir` (used for launchd plist location and worktrees) is resolved by walking upward from the config file looking for `scripts/wake.sh`.

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

# Rejection learning cycle (analyze review patterns, propose CLAUDE.md improvements)
wiz run rejection-cycle
```

### Rejection Learning Cycle

Analyzes persistent rejection journal data to identify recurring patterns in reviewer feedback. When enough rejections accumulate (configurable threshold), proposes CLAUDE.md instruction updates via GitHub issues (`wiz-improvement` label) for human review.

```yaml
rejection_learner:
  enabled: true
  min_rejections: 5      # minimum rejections before analysis runs
  lookback_days: 7       # analyze rejections from the last N days
  target_agents: [bug-fixer, feature-proposer]
```

Rejection data is stored in `memory/rejections/{repo}.jsonl` — one JSON object per reviewer rejection.

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

Schedules are defined in `config/wiz.yaml` under the `schedule` key. The scheduler generates launchd plists with `StartCalendarInterval` entries and installs them in `<wiz_dir>/launchd/` (repo-local, not `~/Library/LaunchAgents/`).

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

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CODING_AGENT_BRIDGE_DIR` | `~/Documents/coding-agent-bridge` | Bridge install path |
| `CODING_AGENT_BRIDGE_URL` | `http://127.0.0.1:4003` | Bridge API URL |
| `CODING_AGENT_BRIDGE_DATA_DIR` | `~/.cin-interface` | Hook data directory |
| `TYPEFULLY_API_KEY` | — | API key for Typefully social media integration |
| `GITHUB_TOKEN` | — | GitHub personal access token (used by `gh` CLI) |
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token for notifications (alternative to config) |

These can also be set in `config/wiz.yaml` under their respective sections. `scripts/wake.sh` sources shell profiles to pick up environment variables for launchd-scheduled runs.

### Configuration Reference

All settings live in `config/wiz.yaml`. Key sections beyond the basic example above:

```yaml
global:
  log_level: "info"             # Applied when --log-level CLI flag is not set
  machine_id: "macbook-1"       # Enables distributed locking when set
  timezone: "America/New_York"

repos:
  - name: "my-repo"
    path: "/path/to/repo"
    github: "owner/repo"
    enabled: true
    self_improve: false
    allowed_issue_authors: []   # Restrict which GitHub users can create issues for this repo

testing:
  run_full_suite_before_pr: true       # Instruction for agents to run full test suite
  require_new_tests_for_fixes: true    # Instruction for agents to write regression tests
  require_new_tests_for_features: true # Instruction for agents to write feature tests
  no_known_bugs_for_completion: true   # Instruction for agents to check for known bugs

worktrees:
  base_dir: ".worktrees"
  stale_days: 7                 # Auto-cleanup worktrees older than N days
  auto_cleanup_merged: true     # Remove worktrees whose branches are merged

locking:
  ttl: 600                      # File lock TTL in seconds
  lock_dir: ".wiz/locks"

escalation:
  max_issue_strikes: 3
  max_file_strikes: 3
  strike_file: ".wiz/strikes.json"
```

The `testing` section values are passed to agent prompts as instructions — agents are told to follow these policies when fixing bugs or implementing features. See `src/wiz/config/schema.py` for the complete schema.

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

- **Auto-merge** — When `reviewer.auto_merge: true` (default), approved PRs are squash-merged automatically after review. Set `auto_merge: false` to require manual merging
- **Three-strike escalation** — Issues that fail repeatedly get escalated with Telegram alerts
- **Self-improvement guard** — When Wiz works on its own repo (`self_improve: true`), the reviewer checks changed files against protected patterns (`config/wiz.yaml`, `CLAUDE.md`, `schema.py`, `escalation.py`). Protected file changes get `requires-human-review` label and Telegram notification instead of auto-closing
- **Structured approval parsing** — Reviewer uses 3-tier verdict: (1) JSON `{"verdict": "approved"}`, (2) keyword scan with word boundaries, (3) fallback to session success
- **Distributed locking** — GitHub label-based claims prevent cross-machine conflicts
- **File locking** — Prevents concurrent modification conflicts on the same machine
- **Stagnation circuit breaker** — Checks actual `git diff` for file changes, stops agents that aren't making progress
- **Loop cap** — Fix-review cycles are capped per issue (default 3), then escalates to human

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
│   ├── social_manager.py
│   └── rejection_learner.py
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
│   ├── distributed_lock.py
│   ├── file_lock.py
│   ├── worktree.py
│   ├── strikes.py
│   ├── loop_tracker.py
│   └── stagnation.py
├── memory/          # Agent memory
│   ├── short_term.py
│   ├── long_term.py
│   ├── rejection_journal.py
│   └── session_logger.py
├── integrations/    # External services
│   ├── google_docs.py
│   ├── image_prompts.py
│   └── typefully.py
├── notifications/   # Alerting
│   └── telegram.py
└── orchestrator/    # Pipeline execution
    ├── pipeline.py
    ├── content_pipeline.py
    ├── feature_pipeline.py
    ├── rejection_pipeline.py
    ├── self_improve.py
    ├── scheduler.py
    ├── escalation.py
    ├── reporter.py
    └── state.py
```
