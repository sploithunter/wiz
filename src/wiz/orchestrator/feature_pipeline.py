"""Feature cycle pipeline: propose or implement features."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from wiz.agents.feature_proposer import FeatureProposerAgent
from wiz.bridge.client import BridgeClient
from wiz.bridge.monitor import BridgeEventMonitor
from wiz.bridge.runner import SessionRunner
from wiz.config.schema import RepoConfig, WizConfig
from wiz.coordination.github_issues import GitHubIssues
from wiz.coordination.worktree import WorktreeManager
from wiz.notifications.telegram import TelegramNotifier
from wiz.orchestrator.state import CycleState

logger = logging.getLogger(__name__)


class FeatureCyclePipeline:
    """Runs feature cycle per repo: propose or implement approved features."""

    def __init__(self, config: WizConfig) -> None:
        self.config = config

    def _create_runner(self) -> SessionRunner:
        client = BridgeClient(self.config.global_.coding_agent_bridge_url)
        monitor = BridgeEventMonitor(self.config.global_.coding_agent_bridge_url)
        return SessionRunner(client, monitor)

    def run_repo(self, repo: RepoConfig) -> CycleState:
        """Run the feature cycle for a single repo."""
        state = CycleState(repo=repo.name)
        start = time.time()

        github = GitHubIssues(
            repo.github,
            allowed_authors=repo.allowed_issue_authors or None,
        )
        worktree = WorktreeManager(
            Path(repo.path), self.config.worktrees.base_dir,
        )

        notifier = TelegramNotifier.from_config(self.config.telegram)

        logger.info("=== %s: feature_cycle ===", repo.name)
        try:
            runner = self._create_runner()
            agent = FeatureProposerAgent(
                runner, self.config.agents.feature_proposer, github, worktree,
                notifier=notifier,
            )
            result = agent.run(
                repo.path,
                timeout=self.config.agents.feature_proposer.session_timeout,
            )
            mode = result.get("mode", "unknown")
            success = result.get("success", False)
            skipped = result.get("skipped", False)

            logger.info(
                "Feature cycle %s: mode=%s success=%s skipped=%s",
                repo.name, mode, success, skipped,
            )

            if skipped:
                state.add_phase(
                    f"feature_{mode}", True, result, time.time() - start,
                )
            else:
                state.add_phase(
                    f"feature_{mode}", success, result, time.time() - start,
                )
        except Exception as e:
            logger.error("Feature cycle failed for %s: %s", repo.name, e, exc_info=True)
            state.add_phase("feature", False, {"error": str(e)}, time.time() - start)

        # Worktree cleanup based on config
        self._cleanup_worktrees(worktree)

        state.total_elapsed = time.time() - start
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

    def run_all(self) -> list[CycleState]:
        """Run feature cycle for all enabled repos."""
        results = []
        for repo in self.config.repos:
            if not repo.enabled:
                continue
            state = self.run_repo(repo)
            results.append(state)
        return results
