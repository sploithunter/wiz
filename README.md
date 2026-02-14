# Wiz

Persistent, self-improving personal AI agent that orchestrates sub-agents for continuous development, content creation, and project management.

## Architecture

Wiz runs scheduled cycles that spawn AI coding agents (Claude Code, Codex) through the [Coding Agent Bridge](https://github.com/jasonjmcghee/coding-agent-bridge) to perform automated development tasks.

### Cycles

- **Dev Cycle**: Bug Hunt → Bug Fix → Review (per repo)
- **Content Cycle**: Blog Writer → Social Manager
- **Feature Cycle**: Feature Proposal → Implementation

### Key Components

- **Bridge Client** - REST + WebSocket client for the Coding Agent Bridge
- **Agents** - Bug Hunter, Bug Fixer, Reviewer, Feature Proposer, Blog Writer, Social Manager
- **Coordination** - GitHub Issues/PRs, Git Worktrees, File Locks, Strike Tracking
- **Orchestrator** - Pipeline execution, escalation, reporting, scheduling

## Setup

### Prerequisites

- Python >= 3.10
- [Coding Agent Bridge](https://github.com/jasonjmcghee/coding-agent-bridge) running
- GitHub CLI (`gh`) authenticated
- Claude Code and/or Codex installed

### Install

```bash
pip install -e ".[dev]"
```

### Configure

Edit `config/wiz.yaml` with your repositories, agent settings, and schedule preferences.

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

### Logging

```bash
# Debug logging
wiz --log-level DEBUG run dev-cycle

# JSON structured logs
wiz --json-logs run dev-cycle
```

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

- PRs are never auto-merged (human review required)
- Three-strike escalation policy sends Telegram alerts
- Self-improvement guard protects critical config files
- File locking prevents concurrent modification conflicts
