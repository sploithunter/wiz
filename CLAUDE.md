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
- Run `pytest tests/` before committing
- Integration tests are marked `@pytest.mark.integration`
- E2E tests are marked `@pytest.mark.e2e`

## Configuration
All settings in `config/wiz.yaml`. See `src/wiz/config/schema.py` for all options.

## Protected Files (Self-Improvement)
When Wiz runs dev cycles on itself, these files require human PR approval:
- `config/wiz.yaml`
- `CLAUDE.md`
- `agents/*/CLAUDE.md`
- `src/wiz/orchestrator/escalation.py`
- `src/wiz/config/schema.py`
