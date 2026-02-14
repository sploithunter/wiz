# Wiz: Personal AI Agent Specification

**Version:** 0.1.0
**Author:** Jason + Claude Opus 4.6
**Date:** 2026-02-13
**Status:** Draft

---

## 1. Vision

Wiz is a persistent, self-improving personal AI agent that orchestrates specialized
sub-agents to perform continuous development, content creation, and project management.
It runs on subscriptions (not API keys) via Coding Agent Bridge, uses proven patterns
from Harness Bench (Ralph Loop, stagnation detection, process group management), and
coordinates work through GitHub issues and git worktrees.

Wiz improves itself. The same dev cycle that runs on target repositories runs on the
Wiz repository. PRs are generated for human review. Nothing ships without passing tests.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Wiz Master Agent                      │
│  (Scheduling, Memory, Routing, Escalation, Config)       │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ │
│  │Bug Hunter│ │Bug Fixer │ │ Reviewer │ │  Feature   │ │
│  │(Codex)   │ │(Claude)  │ │(Codex)   │ │ Proposer   │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └─────┬──────┘ │
│       │             │            │              │        │
│  ┌────┴─────┐ ┌────┴──────────┐               │        │
│  │Blog      │ │Social Manager │               │        │
│  │Writer    │ │(Typefully)    │               │        │
│  └──────────┘ └───────────────┘               │        │
│                                                          │
├─────────────────────────────────────────────────────────┤
│              Coding Agent Bridge                         │
│  (tmux sessions, event capture, prompt delivery)         │
├─────────────────────────────────────────────────────────┤
│              GitHub (Issues, PRs, Worktrees)             │
└─────────────────────────────────────────────────────────┘
```

### 2.1 Layer Responsibilities

**Wiz Master Agent** - Top-level orchestrator. Reads config, loads memory, determines
which agents to run based on schedule and current state, manages escalation, writes
session logs.

**Coding Agent Bridge** - Execution layer. Creates tmux sessions for Claude Code and
Codex, delivers prompts via paste-buffer, captures events via hooks, manages session
lifecycle. Wiz does not interact with tmux directly; it goes through the bridge API.

**GitHub** - Coordination layer. Issues are the shared state between agents. Bug hunter
creates issues. Bug fixer references issues in commits. Reviewer comments on issues.
Feature proposer opens PRs. All audit trails live in GitHub.

### 2.2 Execution Model

Agents run via subscription through Coding Agent Bridge. Sessions are:

1. **Created** by Wiz via bridge API (tmux session with agent CLI)
2. **Given a prompt** via paste-buffer injection
3. **Monitored** via bridge event stream (WebSocket or polling)
4. **Killed** after timeout or completion via process group termination

Agents do NOT run continuously. Wiz wakes via launchd, spawns agents for a
configurable time window, then kills them. This prevents runaway sessions and
keeps subscription usage bounded.

---

## 3. Repository Structure

```
wiz/
├── SPEC.md                          # This file
├── CLAUDE.md                        # Master agent instructions
├── README.md                        # Project overview
├── package.json                     # Dependencies and scripts
├── tsconfig.json                    # TypeScript config
│
├── src/
│   ├── orchestrator/
│   │   ├── scheduler.ts             # launchd integration, wake/kill cycles
│   │   ├── router.ts                # Routes work to appropriate agents
│   │   ├── escalation.ts            # Three-strike policy, human escalation
│   │   └── state.ts                 # Global state management
│   │
│   ├── memory/
│   │   ├── short-term.ts            # Loads/saves short-term memory
│   │   ├── long-term.ts             # Topic file indexing and retrieval
│   │   └── session-logger.ts        # Writes session logs
│   │
│   ├── agents/
│   │   ├── base-agent.ts            # Abstract base for all agents
│   │   ├── bug-hunter.ts            # Bug finding agent (Codex)
│   │   ├── bug-fixer.ts             # Bug fixing agent (Claude Code)
│   │   ├── reviewer.ts              # Fix review agent (Codex)
│   │   ├── feature-proposer.ts      # Daily feature agent (Claude Code)
│   │   ├── blog-writer.ts           # Blog content agent (Claude Code)
│   │   └── social-manager.ts        # Social posting agent (Claude Code)
│   │
│   ├── coordination/
│   │   ├── github-issues.ts         # Issue creation, updating, closing
│   │   ├── github-prs.ts            # PR creation for features
│   │   ├── worktree-manager.ts      # Git worktree lifecycle
│   │   ├── file-lock.ts             # File-level locking
│   │   └── loop-tracker.ts          # Per-issue and per-file strike tracking
│   │
│   ├── bridge/
│   │   ├── client.ts                # Coding Agent Bridge API client
│   │   └── session-monitor.ts       # Watches bridge events for completion
│   │
│   └── config/
│       ├── loader.ts                # Config file parsing and validation
│       └── defaults.ts              # Default configuration values
│
├── config/
│   └── wiz.yaml                     # User configuration (see Section 10)
│
├── memory/
│   ├── short-term.md                # ~50 lines, loaded every session
│   ├── long-term/
│   │   ├── index.md                 # Keyword -> topic mapping
│   │   └── topics/                  # Deep context per topic
│   └── sessions/                    # Timestamped session logs
│
├── agents/                          # CLAUDE.md files for each sub-agent
│   ├── bug-hunter/
│   │   └── CLAUDE.md
│   ├── bug-fixer/
│   │   └── CLAUDE.md
│   ├── reviewer/
│   │   └── CLAUDE.md
│   ├── feature-proposer/
│   │   └── CLAUDE.md
│   ├── blog-writer/
│   │   └── CLAUDE.md
│   └── social-manager/
│       └── CLAUDE.md
│
├── scripts/
│   ├── wake.sh                      # Entry point for launchd
│   ├── run-dev-cycle.sh             # Bug hunt -> fix -> review
│   ├── run-content-cycle.sh         # Blog + social
│   └── run-feature-cycle.sh         # Daily feature PR
│
├── launchd/
│   ├── com.wiz.dev-cycle.plist      # Dev cycle schedule
│   ├── com.wiz.content-cycle.plist  # Content schedule
│   └── com.wiz.feature-cycle.plist  # Feature schedule
│
└── tests/
    ├── unit/
    ├── integration/
    └── e2e/
```

---

## 4. Memory System

### 4.1 Short-Term Memory

**File:** `memory/short-term.md`
**Size limit:** 50 lines
**Loaded:** Every session, every agent

Contains:
- User profile (name, preferences, coding style)
- Currently tracked repositories and their state
- Last 2-3 session summaries (what was done, what's pending)
- Active escalations awaiting human review

Updated at the end of every session by the master agent.

### 4.2 Long-Term Memory

**Directory:** `memory/long-term/`
**Loaded:** On-demand when a topic is referenced

**Index file** (`index.md`) maps keywords to topic files:

```
genesis, harness-bench, benchmarking -> topics/genesis-project.md
coding-agent-bridge, bridge, cab -> topics/coding-agent-bridge.md
blog, content, digital-thoughts -> topics/blog-content.md
preferences, style, conventions -> topics/preferences.md
```

**Topic files** contain deep context: project architecture, past decisions, known
issues, lessons learned. Updated by agents when they discover relevant information.

### 4.3 Session Logs

**Directory:** `memory/sessions/`
**Format:** `YYYY-MM-DD-HH-MM-{cycle-type}.md`

Each session log records:
- Which agents ran and on which repos
- Issues created, fixed, reviewed, escalated
- PRs opened
- Content drafted
- Errors encountered
- Duration and completion status

---

## 5. Dev Cycle: Bug Hunt -> Fix -> Review

This is the core development loop. It runs as a sequential pipeline within a single
wake cycle.

### 5.1 Phase 1: Bug Hunter

**Agent:** Codex (GPT 5.3) via Coding Agent Bridge
**Input:** Target repository
**Output:** GitHub issues with proof-of-concept code

**Behavior:**

1. Clone/pull latest from target repo (or use existing worktree)
2. Analyze codebase systematically
3. For each bug found:
   a. Write a proof-of-concept demonstrating the bug
   b. Classify severity:
      - **P0: Security** - vulnerabilities, injection, auth bypass
      - **P1: Correctness** - logic errors, data corruption, crashes
      - **P2: Reliability** - race conditions, resource leaks, error handling
      - **P3: Performance** - inefficiencies, unnecessary work, scaling issues
      - **P4: UX/Polish** - interface issues, unclear errors, minor improvements
   c. Submit GitHub issue with:
      - Title: `[P{N}] {Brief description}`
      - Body: Description, reproduction steps, proof-of-concept code, expected behavior
      - Labels: `wiz-bug`, `p{n}-{category}`, `needs-fix`
4. Update short-term memory with summary of findings

**Constraints:**
- Must provide working PoC or the bug is not submitted
- Must not duplicate existing open issues (check first)
- Respects `max_issues_per_run` config (default: 10)

### 5.2 Phase 2: Bug Fixer

**Agent:** Claude Code (Opus 4.6) via Coding Agent Bridge
**Input:** Open GitHub issues labeled `needs-fix`, sorted by priority
**Output:** Fix commits on worktree branches, issues marked `needs-review`

**Behavior:**

1. Query GitHub for open issues labeled `needs-fix`, ordered P0 -> P4
2. For each issue (up to `max_fixes_per_run`):
   a. Check file lock status - skip if locked files overlap
   b. Acquire file locks for files to be modified
   c. Create git worktree: `git worktree add .worktrees/fix-{issue-number} -b fix/{issue-number}`
   d. Read the issue, understand the PoC
   e. Implement the fix
   f. Write tests that:
      - Reproduce the original bug (test fails without fix)
      - Verify the fix resolves the bug (test passes with fix)
      - Cover edge cases around the fix
   g. Run full test suite - fix must not break existing tests
   h. If tests pass:
      - Commit with message: `fix: {description} (closes #{issue-number})`
      - Push branch
      - Comment on issue: fix description, test results, branch name
      - Update issue labels: remove `needs-fix`, add `needs-review`
   i. If tests fail after 3 attempts (stagnation detection):
      - Comment on issue with what was tried and why it failed
      - Update issue labels: add `fix-stalled`
      - Increment strike counter (see Section 8)
   j. Release file locks
3. Update short-term memory with summary of fixes

**Constraints:**
- Never pushes directly to main/master
- All fixes go through worktree branches
- No fix is marked `needs-review` if any test fails
- Respects file locks from other agents
- Stagnation limit: 3 attempts per fix before escalating

### 5.3 Phase 3: Reviewer

**Agent:** Codex (GPT 5.3) via Coding Agent Bridge
**Input:** GitHub issues labeled `needs-review`
**Output:** Issues closed (adequate) or reopened (inadequate)

**Behavior:**

1. Query GitHub for issues labeled `needs-review`
2. For each issue:
   a. Read the original bug report and PoC
   b. Read the fix branch diff
   c. Read the new tests
   d. Evaluate against criteria:
      - Does the fix actually address the root cause (not just symptoms)?
      - Are the tests meaningful (not tautological)?
      - Does the fix introduce new issues?
      - Is the code quality acceptable?
      - Does the fix handle edge cases?
   e. If adequate:
      - Comment: review summary, approval rationale
      - Create PR from fix branch to main
      - Close the issue with label `fix-verified`
   f. If inadequate:
      - Comment: specific problems found, what needs to change
      - Remove `needs-review` label, add back `needs-fix`
      - Increment loop counter for this issue
3. If loop counter >= `max_review_cycles` (default: 3):
   - Add label `escalated-to-human`
   - Remove `needs-fix` label (stop the loop)
   - Comment: summary of all attempts and why they failed

**Constraints:**
- Reviews must be specific and actionable, not vague
- Must check that tests actually exercise the fix (not just pass trivially)
- PRs created by reviewer go to human for final merge

---

## 6. Feature Proposer

**Agent:** Claude Code (Opus 4.6) via Coding Agent Bridge
**Frequency:** Configurable (default: 1 per day, set to 0 to disable)

**Behavior:**

1. Check `feature_backlog` in config or GitHub issues labeled `feature-candidate`
2. If backlog is empty and `auto_propose_features` is true:
   a. Analyze the codebase for improvement opportunities
   b. Check memory for past features to avoid overlap
   c. Propose a feature with scope estimate
   d. Create GitHub issue labeled `feature-candidate` for human approval
   e. Stop here (human must approve before implementation)
3. If backlog has approved items (labeled `feature-approved`):
   a. Pick the highest-priority approved feature
   b. Create worktree: `git worktree add .worktrees/feature-{issue-number} -b feature/{issue-number}`
   c. Implement with full test coverage
   d. Run full test suite
   e. Open PR with:
      - Description of what was added and why
      - Test plan
      - Reference to the feature issue
   f. Label issue `feature-pr-open`
4. No feature is implemented without human-approved issue

**Constraints:**
- Features per run: configurable via `features_per_run` (default: 1, 0 = disabled)
- Must not touch files locked by bug-fix agents
- PR is always to main, never direct push
- All tests must pass before PR is opened
- Feature scope must be completable in one session

---

## 7. Content Pipeline

### 7.1 Blog Writer

**Agent:** Claude Code (Opus 4.6) via Coding Agent Bridge
**Output:** Blog post drafts saved to a configurable location

**Behavior:**

1. Check topic backlog (config or memory)
2. If no topics queued and `auto_propose_topics` is true:
   a. Analyze recent project activity (commits, issues, PRs)
   b. Propose topics based on what's been built/learned
   c. Save proposals for human review
   d. Stop here until human approves a topic
3. If approved topic exists:
   a. Load topic context from long-term memory
   b. Load style guide from CLAUDE.md
   c. Write draft
   d. Save draft to configured output (local file, Notion, etc.)
   e. Update memory with topics covered to prevent overlap

**Style is defined in `agents/blog-writer/CLAUDE.md`** and must include:
- Tone and voice rules
- Structural requirements (headers, length, format)
- Topics to focus on (Genesis, Harness Bench, AI development)
- Topics to avoid
- Engagement patterns (closing asks, etc.)

### 7.2 Social Manager

**Agent:** Claude Code (Opus 4.6) via Coding Agent Bridge
**Output:** Typefully drafts for X/Twitter

**Behavior:**

1. Check for recent blog posts, project milestones, or manual topic queue
2. Generate social content appropriate for the platform:
   - X/Twitter: concise, engaging, thread-ready if longer
   - Adapt tone for platform conventions
3. Create Typefully draft via API (does NOT publish directly)
4. All drafts go to human review before publishing

**Integration:**
- Uses Typefully MCP tools for draft creation
- Scheduling via Typefully's `next-free-slot` or explicit times
- Can pull from blog content, project changelogs, GitHub activity

**Constraints:**
- Never publishes without human review
- Frequency configurable via `social_posts_per_week` (default: 3, 0 = disabled)
- Must check memory for recent posts to avoid repetition

---

## 8. Escalation and Loop Prevention

### 8.1 Three-Strike Policy

Tracked in `.wiz/strikes.json` locally and mirrored in GitHub issue labels.

```json
{
  "issues": {
    "42": {
      "strikes": 2,
      "history": [
        {"attempt": 1, "date": "2026-02-13", "reason": "Fix didn't address root cause"},
        {"attempt": 2, "date": "2026-02-13", "reason": "Tests still failing on edge case"}
      ]
    }
  },
  "files": {
    "src/auth/login.ts": {
      "failed_fixes": 3,
      "issues": [42, 47, 51],
      "flagged": true
    }
  }
}
```

**Per-issue tracking:**
- Strike 1-2: Issue returns to `needs-fix` with reviewer feedback
- Strike 3: Issue labeled `escalated-to-human`, removed from automated cycle
- Human resolves or provides guidance, then re-enters the cycle

**Per-file tracking:**
- If the same file causes review rejections across 3+ different issues,
  the file is flagged as `needs-human-attention`
- Agent adds a comment to each related issue explaining the pattern
- Prevents agents from repeatedly failing on code they don't understand

### 8.2 Stagnation Detection

Borrowed from Harness Bench's Ralph Loop:

- If a bug fixer makes no file changes for `stagnation_limit` (default: 3)
  consecutive attempts on the same issue, it stops and escalates
- Prevents infinite loops where the agent keeps trying the same approach
- Tracked via git diff between attempts

### 8.3 Timeout Enforcement

Every agent session has a hard timeout:

- `session_timeout`: Maximum time for a single agent session (default: 600s)
- `cycle_timeout`: Maximum time for an entire dev cycle run (default: 3600s)

On timeout, the process group is killed via `SIGKILL` (same as Harness Bench).
Partial work is committed if possible, otherwise discarded.

---

## 9. File Locking

**Directory:** `.wiz/locks/` in each target repository

**Lock format:** One file per locked path.

```
# .wiz/locks/src--auth--login.ts.lock
{
  "file": "src/auth/login.ts",
  "agent": "bug-fixer",
  "issue": 42,
  "acquired": "2026-02-13T07:15:00Z",
  "expires": "2026-02-13T07:25:00Z"
}
```

**Rules:**

1. Before modifying a file, agent checks for existing lock
2. If unlocked: acquire lock with configurable TTL (default: 600s)
3. If locked by another agent: skip this issue, move to next
4. If lock is expired: steal the lock (previous agent timed out)
5. On completion or failure: release lock explicitly
6. On agent kill (timeout): lock expires naturally via TTL

**File path encoding:** Forward slashes replaced with `--` in lock filenames.

Locks are local to the repository. They are in `.gitignore` and never committed.

---

## 10. Git Worktree Strategy

Each agent working on a repository gets its own worktree:

```
target-repo/
├── (main working tree - main branch)
├── .worktrees/
│   ├── fix-42/          # Bug fix for issue #42
│   ├── fix-47/          # Bug fix for issue #47
│   └── feature-12/      # Feature implementation
└── .wiz/
    ├── locks/
    └── strikes.json
```

**Lifecycle:**

1. **Create:** `git worktree add .worktrees/{type}-{issue} -b {type}/{issue}`
2. **Work:** Agent operates entirely within the worktree directory
3. **Complete:** Push branch, create PR or mark for review
4. **Cleanup:** `git worktree remove .worktrees/{type}-{issue}` after PR merge or escalation

**Cleanup policy:**
- Worktrees for merged PRs are removed immediately
- Worktrees for escalated issues are kept until human resolves
- Stale worktrees (no activity for `worktree_stale_days`, default: 7) are listed
  in the morning report for human decision

---

## 11. Configuration

**File:** `config/wiz.yaml`

All behavioral parameters are configurable. Sensible defaults allow starting
with minimal config.

```yaml
# ============================================================
# Wiz Configuration
# ============================================================

# --- Global ---
global:
  coding_agent_bridge_url: "http://127.0.0.1:4003"
  bridge_data_dir: "~/.coding-agent-bridge"
  log_level: "info"                       # debug | info | warn | error
  timezone: "America/New_York"

# --- Repositories ---
# List of repositories Wiz manages. The dev cycle runs on each.
repos:
  - name: "wiz"
    path: "/Users/jason/Documents/wiz"
    github: "sploithunter/wiz"
    enabled: true
    self_improve: true                    # Wiz runs dev cycle on itself

  - name: "harness-bench"
    path: "/Users/jason/repos/harnesss-bench"
    github: "sploithunter/harnesss-bench"
    enabled: true

  - name: "coding-agent-bridge"
    path: "/Users/jason/repos/coding-agent-bridge"
    github: "sploithunter/coding-agent-bridge"
    enabled: true

# --- Agents ---
agents:
  bug_hunter:
    model: "codex"                        # Codex GPT 5.3 via bridge
    max_issues_per_run: 10                # Max issues to create per repo per run
    min_severity: "P4"                    # Minimum severity to report (P0-P4)
    require_poc: true                     # Must include proof-of-concept
    session_timeout: 600                  # Seconds per session

  bug_fixer:
    model: "claude"                       # Claude Code Opus 4.6 via bridge
    max_fixes_per_run: 5                  # Max issues to fix per repo per run
    stagnation_limit: 3                   # Stop after N attempts with no progress
    session_timeout: 600                  # Seconds per session

  reviewer:
    model: "codex"                        # Codex GPT 5.3 via bridge
    max_reviews_per_run: 10               # Max issues to review per run
    max_review_cycles: 3                  # Strikes before escalation
    session_timeout: 300                  # Seconds per session

  feature_proposer:
    model: "claude"                       # Claude Code Opus 4.6 via bridge
    features_per_run: 1                   # Features to implement per run (0 = disabled)
    auto_propose_features: true           # Propose features when backlog is empty
    require_approval: true                # Human must approve before implementation
    session_timeout: 900                  # Seconds per session

  blog_writer:
    model: "claude"
    auto_propose_topics: true
    require_approval: true                # Human must approve topic before writing
    output_dir: "~/Documents/blog-drafts" # Where drafts are saved
    session_timeout: 600

  social_manager:
    model: "claude"
    social_posts_per_week: 3              # Posts to draft per week (0 = disabled)
    platforms:
      - "x"                               # X/Twitter via Typefully
    require_approval: true                # Human reviews before publishing
    session_timeout: 300

# --- Dev Cycle ---
dev_cycle:
  cycle_timeout: 3600                     # Max seconds for entire dev cycle
  phases:                                 # Which phases to run (in order)
    - "bug_hunt"
    - "bug_fix"
    - "review"
  parallel_fixes: false                   # Run fixes in parallel (advanced)

# --- Scheduling ---
# Cron-style scheduling via launchd.
# Set enabled: false to disable any schedule.
schedule:
  dev_cycle:
    enabled: true
    times:                                # When to run dev cycle
      - "07:00"                           # Morning
    days: ["mon", "tue", "wed", "thu", "fri"]

  feature_cycle:
    enabled: true
    times:
      - "09:00"
    days: ["mon", "wed", "fri"]

  content_cycle:
    enabled: true
    times:
      - "10:00"
    days: ["tue", "thu"]

# --- Worktrees ---
worktrees:
  base_dir: ".worktrees"                  # Relative to repo root
  stale_days: 7                           # Days before flagging stale worktrees
  auto_cleanup_merged: true               # Remove worktrees after PR merge

# --- File Locking ---
locking:
  ttl: 600                                # Lock TTL in seconds
  lock_dir: ".wiz/locks"                  # Relative to repo root

# --- Escalation ---
escalation:
  max_issue_strikes: 3                    # Per-issue strike limit
  max_file_strikes: 3                     # Per-file strike limit (across issues)
  strike_file: ".wiz/strikes.json"        # Relative to repo root

# --- Memory ---
memory:
  short_term_max_lines: 50
  session_log_retention_days: 30          # Days to keep session logs
  long_term_dir: "memory/long-term"

# --- Testing ---
testing:
  run_full_suite_before_pr: true          # Full test suite must pass before any PR
  require_new_tests_for_fixes: true       # Bug fixes must include regression tests
  require_new_tests_for_features: true    # Features must include tests
  no_known_bugs_for_completion: true      # Nothing marked done with known bugs
```

---

## 12. Scheduling and Lifecycle

### 12.1 launchd Integration

Each cycle type gets its own plist in `launchd/`. The `wake.sh` script:

1. Starts Coding Agent Bridge if not running
2. Loads config from `config/wiz.yaml`
3. Loads short-term memory
4. Runs the requested cycle (dev, content, or feature)
5. Updates short-term memory with session summary
6. Kills all agent sessions spawned during this cycle
7. Stops Coding Agent Bridge if no other cycles are pending

### 12.2 Session Lifecycle

```
launchd fires
  -> wake.sh starts
    -> bridge started (if not running)
      -> agent session created via bridge API
        -> prompt delivered via paste-buffer
          -> agent works (monitored via bridge events)
            -> completion detected OR timeout hit
              -> results captured
                -> session killed via bridge API
                  -> next agent in pipeline (or cycle ends)
                    -> bridge stopped
                      -> wake.sh exits
```

### 12.3 Manual Invocation

All cycles can be triggered manually:

```bash
# Run full dev cycle on all repos
./scripts/wake.sh dev-cycle

# Run dev cycle on specific repo
./scripts/wake.sh dev-cycle --repo wiz

# Run only bug hunting
./scripts/wake.sh dev-cycle --phase bug_hunt

# Run content cycle
./scripts/wake.sh content-cycle

# Run feature cycle
./scripts/wake.sh feature-cycle

# Check status of all repos
./scripts/wake.sh status
```

---

## 13. Self-Improvement Loop

When `self_improve: true` is set for the wiz repo in config:

1. The dev cycle runs on Wiz's own codebase
2. Bug hunter finds bugs in Wiz's orchestration, agents, config handling
3. Bug fixer fixes them with tests
4. Reviewer validates the fixes
5. Feature proposer adds capabilities to Wiz itself

**Safety rails:**

- Wiz cannot modify its own escalation policy or safety limits
- Changes to `config/wiz.yaml` defaults require human PR approval
- Changes to CLAUDE.md agent instructions require human PR approval
- All self-modifications go through PR review (never direct to main)
- Test suite must pass before any self-modification PR is opened

**Protected files** (require human review, never auto-merged):

```yaml
protected_files:
  - "config/wiz.yaml"
  - "CLAUDE.md"
  - "agents/*/CLAUDE.md"
  - "src/orchestrator/escalation.ts"
  - "src/config/defaults.ts"
```

---

## 14. Testing Philosophy

Testing is not optional. It is a structural requirement at every level.

### 14.1 Requirements

- **Unit tests** for every module in `src/`
- **Integration tests** for agent-to-bridge communication
- **Integration tests** for GitHub issue/PR workflows
- **E2E tests** for complete dev cycle (bug hunt -> fix -> review)
- **E2E tests** for content pipeline (topic -> draft -> Typefully)

### 14.2 Rules

1. No PR is opened if any test fails
2. No issue is marked "fixed" if any test fails
3. Bug fixes MUST include a regression test that fails without the fix
4. Features MUST include tests covering the new functionality
5. Test coverage must not decrease on any PR
6. Nothing is labeled "finished" with any known bugs anywhere in the codebase
7. Agents are instructed to create tests at every phase, not as an afterthought

### 14.3 Test Infrastructure

```
tests/
├── unit/
│   ├── orchestrator/
│   ├── memory/
│   ├── agents/
│   ├── coordination/
│   └── bridge/
├── integration/
│   ├── bridge-communication.test.ts
│   ├── github-workflow.test.ts
│   └── memory-persistence.test.ts
└── e2e/
    ├── dev-cycle.test.ts
    ├── content-cycle.test.ts
    └── self-improvement.test.ts
```

---

## 15. Content Topics: Genesis Project and Harness Bench

The blog writer and social manager should focus on:

### 15.1 Blog Topics
- Harness Bench: methodology, results, comparisons between AI coding tools
- Genesis Project: updates, architecture decisions, lessons learned
- Coding Agent Bridge: how multi-agent orchestration works
- Wiz itself: building a self-improving personal agent
- AI development workflows: practical insights from daily use

### 15.2 Social Topics (X/Twitter)
- Short insights from development work
- Benchmark results and comparisons
- "Today Wiz did X" updates showing autonomous agent work
- Threads on specific technical decisions
- Engagement with AI development community

---

## 16. Build Sequence

Each milestone must be validated and tested before moving to the next.
No milestone is complete with failing tests or known bugs.

### Milestone 1: Foundation
- [ ] Repository scaffold (directory structure, package.json, tsconfig)
- [ ] Configuration loader with validation
- [ ] Memory system (short-term load/save, long-term index/retrieve)
- [ ] Session logger
- [ ] Unit tests for all above

### Milestone 2: Bridge Integration
- [ ] Coding Agent Bridge client (create session, send prompt, kill session)
- [ ] Session monitor (detect completion via bridge events)
- [ ] Timeout enforcement with process group termination
- [ ] Integration tests against running bridge instance

### Milestone 3: Bug Hunter Agent
- [ ] Agent CLAUDE.md with severity classification rules
- [ ] GitHub issue creation with labels, PoC code blocks
- [ ] Duplicate issue detection
- [ ] Run against one target repo, validate output
- [ ] Tests for issue creation and deduplication

### Milestone 4: Bug Fixer Agent
- [ ] Agent CLAUDE.md with fix and testing requirements
- [ ] Git worktree creation and cleanup
- [ ] File locking (acquire, release, expiry)
- [ ] Stagnation detection
- [ ] GitHub issue commenting and label updates
- [ ] Run against real issues from Milestone 3, validate fixes
- [ ] Tests for worktree management, locking, stagnation

### Milestone 5: Reviewer Agent
- [ ] Agent CLAUDE.md with review criteria
- [ ] Review against fix branch diffs
- [ ] Issue close/reopen logic
- [ ] Loop counter and three-strike escalation
- [ ] PR creation for approved fixes
- [ ] Run against real fixes from Milestone 4, validate reviews
- [ ] Tests for review logic, escalation, PR creation

### Milestone 6: Complete Dev Cycle
- [ ] End-to-end pipeline: bug hunt -> fix -> review
- [ ] Per-issue and per-file strike tracking
- [ ] Cycle timeout enforcement
- [ ] Morning status report generation
- [ ] E2E tests for full cycle
- [ ] Run on multiple repos, validate stability

### Milestone 7: Scheduling
- [ ] launchd plist generation from config
- [ ] wake.sh entry point with cycle routing
- [ ] Bridge auto-start/stop
- [ ] Manual invocation CLI
- [ ] Install/uninstall scripts for launchd plists
- [ ] Validate scheduled runs over 48-hour period

### Milestone 8: Feature Proposer
- [ ] Agent CLAUDE.md with feature scoping rules
- [ ] Feature backlog management (GitHub issues)
- [ ] Approval workflow (propose -> human approve -> implement)
- [ ] PR creation with tests
- [ ] Tests for backlog management and PR creation

### Milestone 9: Self-Improvement
- [ ] Enable dev cycle on Wiz repo
- [ ] Protected file list enforcement
- [ ] Validate that Wiz can find/fix/review its own bugs
- [ ] Validate that safety rails prevent unsafe self-modification

### Milestone 10: Blog Writer
- [ ] Agent CLAUDE.md with voice, style, structure rules
- [ ] Topic backlog and proposal system
- [ ] Draft generation and storage
- [ ] Memory update to prevent topic overlap
- [ ] Tests for draft generation and deduplication

### Milestone 11: Social Manager
- [ ] Agent CLAUDE.md with platform-specific style rules
- [ ] Typefully integration for draft creation
- [ ] Content derivation from blog posts and project activity
- [ ] Scheduling via Typefully API
- [ ] Tests for Typefully integration

### Milestone 12: Polish and Hardening
- [ ] Error recovery for all failure modes
- [ ] Comprehensive logging and observability
- [ ] Performance optimization (parallel phases where safe)
- [ ] Documentation
- [ ] Full E2E test suite covering all cycles

---

## 17. Open Questions

Decisions to make during implementation:

1. **TypeScript vs Python for Wiz core?** Coding Agent Bridge is TypeScript.
   Harness Bench is Python. Either works. TypeScript keeps the stack consistent
   with the bridge. Python has better CLI tooling (Click, rich). Decide at
   Milestone 1.

2. **Notification delivery for escalations.** Terminal output is insufficient
   if Wiz runs while you're away. Options: macOS notifications, email, Slack,
   Typefully DM. Decide at Milestone 6.

3. **Blog output format.** Local markdown files? Notion? Direct to Substack?
   Depends on publishing workflow. Decide at Milestone 10.

4. **PR auto-merge policy.** Should reviewer-approved PRs auto-merge, or
   always require human? Conservative default: always human. Can be configured
   later. Decide at Milestone 5.

---

## Appendix A: Agent CLAUDE.md Template

Each sub-agent's CLAUDE.md follows this structure:

```markdown
# {Agent Name}

## Role
{One sentence description of what this agent does}

## Context
{What this agent needs to know about the project/user}

## Inputs
{What this agent receives: issues, topics, prompts}

## Outputs
{What this agent produces: issues, fixes, drafts, comments}

## Rules
{Specific behavioral rules, numbered and unambiguous}

## Quality Standards
{What "good" looks like for this agent's output}

## Testing Requirements
{Testing rules specific to this agent's work}

## Constraints
{What this agent must NOT do}
```

---

## Appendix B: GitHub Label Schema

```
wiz-bug              # Bug found by Wiz bug hunter
wiz-fix              # Fix created by Wiz bug fixer
wiz-feature          # Feature proposed by Wiz
needs-fix            # Awaiting bug fixer
needs-review         # Awaiting reviewer
fix-verified         # Reviewer approved the fix
fix-stalled          # Fixer hit stagnation limit
escalated-to-human   # Exceeded strike limit
feature-candidate    # Proposed feature awaiting approval
feature-approved     # Human-approved feature
feature-pr-open      # Feature has an open PR
p0-security          # Priority labels
p1-correctness
p2-reliability
p3-performance
p4-polish
```
