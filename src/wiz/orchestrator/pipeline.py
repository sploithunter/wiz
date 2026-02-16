"""Dev cycle pipeline orchestrator.

Timeout management pattern from harness-bench ralph_base.py:655-773.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from wiz.agents.bug_fixer import BugFixerAgent
from wiz.agents.bug_hunter import BugHunterAgent
from wiz.agents.reviewer import ReviewerAgent
from wiz.bridge.client import BridgeClient
from wiz.bridge.monitor import BridgeEventMonitor
from wiz.bridge.runner import SessionRunner
from wiz.config.schema import RepoConfig, WizConfig
from wiz.coordination.distributed_lock import DistributedLockManager
from wiz.coordination.file_lock import FileLockManager
from wiz.coordination.github_issues import GitHubIssues
from wiz.coordination.github_prs import GitHubPRs
from wiz.coordination.loop_tracker import LoopTracker
from wiz.coordination.strikes import StrikeTracker
from wiz.coordination.worktree import WorktreeManager
from wiz.notifications.telegram import TelegramNotifier
from wiz.orchestrator.state import CycleState

logger = logging.getLogger(__name__)


class DevCyclePipeline:
    """Runs dev cycle phases sequentially per repo with shared timeout budget."""

    def __init__(self, config: WizConfig, notifier: TelegramNotifier) -> None:
        self.config = config
        self.notifier = notifier

    def _time_remaining(self, start: float, total: float) -> float:
        return max(0, total - (time.time() - start))

    def _create_runner(self) -> SessionRunner:
        client = BridgeClient(self.config.global_.coding_agent_bridge_url)
        monitor = BridgeEventMonitor(self.config.global_.coding_agent_bridge_url)
        return SessionRunner(client, monitor)

    def run_repo(self, repo: RepoConfig, phases: list[str] | None = None) -> CycleState:
        """Run the dev cycle for a single repo."""
        state = CycleState(repo=repo.name)
        cycle_timeout = self.config.dev_cycle.cycle_timeout
        start_time = time.time()
        phases = phases or self.config.dev_cycle.phases

        # Shared resources
        github = GitHubIssues(
            repo.github,
            allowed_authors=repo.allowed_issue_authors or None,
        )
        prs = GitHubPRs(repo.github)
        worktree = WorktreeManager(Path(repo.path), self.config.worktrees.base_dir)
        locks = FileLockManager(
            Path(repo.path), self.config.locking.lock_dir, self.config.locking.ttl
        )
        strikes = StrikeTracker(Path(repo.path) / self.config.escalation.strike_file)
        loop_tracker = LoopTracker(
            strikes, self.config.agents.reviewer.max_review_cycles
        )

        # Distributed locking (multi-machine) — only when machine_id is configured
        distributed_locks: DistributedLockManager | None = None
        if self.config.global_.machine_id:
            distributed_locks = DistributedLockManager(
                github, self.config.global_.machine_id
            )
            cleaned = distributed_locks.cleanup_stale()
            if cleaned:
                logger.info("Cleaned up %d stale distributed claims", cleaned)

        for phase in phases:
            remaining = self._time_remaining(start_time, cycle_timeout)
            if remaining <= 0:
                logger.warning("Cycle timeout reached, skipping %s", phase)
                state.timed_out = True
                break

            logger.info(
                "=== %s: %s (%.0fs remaining) ===", repo.name, phase, remaining
            )
            phase_start = time.time()

            try:
                if phase == "bug_hunt":
                    result = self._run_bug_hunt(repo, github, remaining)
                elif phase == "bug_fix":
                    result = self._run_bug_fix(
                        repo, github, worktree, locks, remaining,
                        distributed_locks=distributed_locks,
                    )
                elif phase == "review":
                    result = self._run_review(
                        repo, github, prs, loop_tracker, remaining,
                        distributed_locks=distributed_locks,
                    )
                else:
                    valid_phases = ["bug_hunt", "bug_fix", "review"]
                    logger.warning(
                        "Unknown phase: %s (valid: %s)", phase, ", ".join(valid_phases)
                    )
                    result = {"skipped": True, "reason": f"unknown_phase: {phase}"}
                    phase_elapsed = time.time() - phase_start
                    state.add_phase(phase, False, result, phase_elapsed)
                    continue

                phase_elapsed = time.time() - phase_start
                state.add_phase(phase, True, result, phase_elapsed)

            except Exception as e:
                phase_elapsed = time.time() - phase_start
                logger.error("Phase %s failed: %s", phase, e, exc_info=True)
                state.add_phase(phase, False, {"error": str(e)}, phase_elapsed)

        # Worktree cleanup based on config
        self._cleanup_worktrees(worktree)

        state.total_elapsed = time.time() - start_time
        return state

    def _cleanup_worktrees(self, worktree: WorktreeManager) -> None:
        """Run worktree cleanup based on config settings."""
        wt_config = self.config.worktrees
        try:
            removed = worktree.cleanup_stale(stale_days=wt_config.stale_days)
            if removed:
                logger.info("Cleaned up %d stale worktrees", removed)
        except Exception as e:
            logger.warning("Stale worktree cleanup failed: %s", e)

        if wt_config.auto_cleanup_merged:
            try:
                removed = worktree.cleanup_merged()
                if removed:
                    logger.info("Cleaned up %d merged worktrees", removed)
            except Exception as e:
                logger.warning("Merged worktree cleanup failed: %s", e)

    def run_all(self, phases: list[str] | None = None) -> list[CycleState]:
        """Run dev cycle for all enabled repos."""
        results = []
        for repo in self.config.repos:
            if not repo.enabled:
                continue
            state = self.run_repo(repo, phases)
            results.append(state)
        return results

    def _run_bug_hunt(
        self, repo: RepoConfig, github: GitHubIssues, timeout: float
    ) -> dict[str, Any]:
        runner = self._create_runner()
        agent = BugHunterAgent(runner, self.config.agents.bug_hunter, github)
        existing = github.list_issues(labels=["wiz-bug"])
        return agent.run(
            repo.path,
            timeout=min(timeout, self.config.agents.bug_hunter.session_timeout),
            existing_issues=existing,
        )

    def _run_bug_fix(
        self,
        repo: RepoConfig,
        github: GitHubIssues,
        worktree: WorktreeManager,
        locks: FileLockManager,
        timeout: float,
        distributed_locks: DistributedLockManager | None = None,
    ) -> dict[str, Any]:
        runner = self._create_runner()
        agent = BugFixerAgent(
            runner, self.config.agents.bug_fixer, github, worktree, locks,
            distributed_locks=distributed_locks,
            parallel=self.config.dev_cycle.parallel_fixes,
        )
        return agent.run(
            repo.path,
            timeout=min(timeout, self.config.agents.bug_fixer.session_timeout),
        )

    def _run_review(
        self,
        repo: RepoConfig,
        github: GitHubIssues,
        prs: GitHubPRs,
        loop_tracker: LoopTracker,
        timeout: float,
        distributed_locks: DistributedLockManager | None = None,
    ) -> dict[str, Any]:
        runner = self._create_runner()
        agent = ReviewerAgent(
            runner,
            self.config.agents.reviewer,
            github,
            prs,
            loop_tracker,
            self.notifier,
            repo_name=repo.name,
            distributed_locks=distributed_locks,
            self_improve=repo.self_improve,
        )
        return agent.run(
            repo.path,
            timeout=min(timeout, self.config.agents.reviewer.session_timeout),
        )
