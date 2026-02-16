"""Rejection learning pipeline: analyze rejection patterns and propose improvements."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from wiz.agents.rejection_learner import RejectionLearnerAgent
from wiz.bridge.client import BridgeClient
from wiz.bridge.monitor import BridgeEventMonitor
from wiz.bridge.runner import SessionRunner
from wiz.config.schema import WizConfig
from wiz.coordination.github_issues import GitHubIssues
from wiz.memory.rejection_journal import RejectionJournal
from wiz.orchestrator.state import CycleState

logger = logging.getLogger(__name__)


class RejectionCyclePipeline:
    """Analyzes rejection patterns and proposes CLAUDE.md improvements."""

    def __init__(self, config: WizConfig) -> None:
        self.config = config

    def _create_runner(self) -> SessionRunner:
        client = BridgeClient(self.config.global_.coding_agent_bridge_url)
        monitor = BridgeEventMonitor(self.config.global_.coding_agent_bridge_url)
        return SessionRunner(client, monitor)

    def run(self) -> CycleState:
        state = CycleState(repo="rejection-learner")
        start = time.time()
        learner_config = self.config.rejection_learner

        if not learner_config.enabled:
            logger.info("Rejection learner is disabled")
            state.add_phase("rejection_learn", True, {"skipped": "disabled"})
            state.total_elapsed = time.time() - start
            return state

        journal = RejectionJournal()
        since = datetime.now(timezone.utc) - timedelta(days=learner_config.lookback_days)
        entries = journal.read(since=since)

        if len(entries) < learner_config.min_rejections:
            logger.info(
                "Not enough rejections (%d < %d), skipping analysis",
                len(entries), learner_config.min_rejections,
            )
            state.add_phase(
                "rejection_learn", True,
                {"skipped": "below_threshold", "count": len(entries)},
            )
            state.total_elapsed = time.time() - start
            return state

        # Use first enabled repo for GitHub issue creation
        github_repo = None
        for repo in self.config.repos:
            if repo.enabled:
                github_repo = repo.github
                break

        if not github_repo:
            logger.warning("No enabled repos found for creating improvement issues")
            state.add_phase("rejection_learn", False, {"error": "no_enabled_repos"})
            state.total_elapsed = time.time() - start
            return state

        try:
            logger.info("=== rejection_learn (%d entries) ===", len(entries))
            phase_start = time.time()
            runner = self._create_runner()
            github = GitHubIssues(github_repo)

            agent = RejectionLearnerAgent(runner, learner_config, journal, github)
            result = agent.run(".", timeout=300)

            phase_elapsed = time.time() - phase_start
            state.add_phase("rejection_learn", True, result, phase_elapsed)
        except Exception as e:
            logger.error("Rejection learning failed: %s", e, exc_info=True)
            phase_elapsed = time.time() - phase_start
            state.add_phase("rejection_learn", False, {"error": str(e)}, phase_elapsed)

        state.total_elapsed = time.time() - start
        return state
