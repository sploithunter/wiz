"""Tests for reviewer agent."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from wiz.agents.reviewer import ReviewerAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import ReviewerConfig
from wiz.coordination.distributed_lock import DistributedLockManager
from wiz.coordination.github_issues import GitHubIssues
from wiz.coordination.github_prs import GitHubPRs
from wiz.coordination.loop_tracker import LoopTracker
from wiz.coordination.strikes import StrikeTracker
from wiz.notifications.telegram import TelegramNotifier


class TestReviewerAgent:
    def _make_agent(self, tmp_path: Path, config: ReviewerConfig | None = None, self_improve: bool = False):
        runner = MagicMock(spec=SessionRunner)
        config = config or ReviewerConfig()
        github = MagicMock(spec=GitHubIssues)
        prs = MagicMock(spec=GitHubPRs)
        strikes = StrikeTracker(tmp_path / "strikes.json")
        loop_tracker = LoopTracker(strikes, max_cycles=config.max_review_cycles)
        notifier = MagicMock(spec=TelegramNotifier)
        return ReviewerAgent(
            runner, config, github, prs, loop_tracker, notifier,
            repo_name="test/repo", self_improve=self_improve,
        ), runner, github, prs, notifier

    def test_approval_path(self, tmp_path: Path):
        """Approved fix -> PR created, issue closed."""
        agent, runner, github, prs, notifier = self._make_agent(tmp_path)
        # Return result with APPROVED in events
        runner.run.return_value = SessionResult(
            success=True,
            reason="completed",
            events=[{"data": {"type": "stop", "response": "APPROVED"}}],
        )
        prs.create_pr.return_value = "https://github.com/test/repo/pull/1"

        issues = [{"number": 1, "title": "[P2] Bug", "body": "details"}]
        result = agent.run("/tmp", issues=issues)

        assert result["results"][0]["action"] == "approved"
        prs.create_pr.assert_called_once()
        github.close_issue.assert_called_once_with(1)

    @patch.object(ReviewerAgent, "_get_branch_files", return_value=["src/fix.py"])
    def test_pr_creation_failure_does_not_close_issue(self, mock_files, tmp_path: Path):
        """When PR creation fails (returns None), issue must NOT be closed."""
        agent, runner, github, prs, notifier = self._make_agent(tmp_path)
        runner.run.return_value = SessionResult(
            success=True,
            reason="completed",
            events=[{"data": {"type": "stop", "response": "APPROVED"}}],
        )
        prs.create_pr.return_value = None  # PR creation failed

        issues = [{"number": 123, "title": "[P2] bug", "body": "x"}]
        result = agent.run("/tmp", issues=issues)

        # Issue must NOT be closed
        github.close_issue.assert_not_called()
        # A comment should be added explaining the failure
        github.add_comment.assert_called_once()
        assert "PR creation failed" in github.add_comment.call_args[0][1]
        # Result should indicate PR failure
        assert result["results"][0]["action"] == "pr_failed"
        assert result["results"][0]["pr"] is None

    def test_rejection_path(self, tmp_path: Path):
        """Rejected fix -> labels updated, comment added."""
        agent, runner, github, prs, notifier = self._make_agent(tmp_path)
        runner.run.return_value = SessionResult(
            success=True,
            reason="completed",
            events=[{"data": {"type": "stop", "response": "REJECTED: needs work"}}],
        )

        issues = [{"number": 1, "title": "[P2] Bug", "body": "details"}]
        result = agent.run("/tmp", issues=issues)

        assert result["results"][0]["action"] == "rejected"
        github.update_labels.assert_called_once_with(
            1, add=["needs-fix"], remove=["needs-review"]
        )
        github.add_comment.assert_called_once()

    def test_escalation_path(self, tmp_path: Path):
        """After max cycles -> escalated to human, Telegram fired."""
        config = ReviewerConfig(max_review_cycles=2)
        agent, runner, github, prs, notifier = self._make_agent(tmp_path, config)

        # Pre-record strikes to bring to threshold
        runner.run.return_value = SessionResult(
            success=True,
            reason="completed",
            events=[{"data": {"type": "stop", "response": "REJECTED"}}],
        )

        issues = [{"number": 1, "title": "[P2] Bug", "body": "x"}]

        # First rejection
        agent.run("/tmp", issues=issues)
        # Second rejection -> escalation
        result = agent.run("/tmp", issues=issues)

        assert result["results"][0]["action"] == "escalated"
        notifier.notify_escalation.assert_called()
        # Verify escalation labels
        label_calls = github.update_labels.call_args_list
        last_call = label_calls[-1]
        add_labels = last_call[1].get(
            "add", last_call[0][1] if len(last_call[0]) > 1 else [],
        )
        assert "escalated-to-human" in add_labels

    def test_already_escalated_skips_review(self, tmp_path: Path):
        """If max cycles already reached, skip review entirely."""
        config = ReviewerConfig(max_review_cycles=1)
        agent, runner, github, prs, notifier = self._make_agent(tmp_path, config)

        # Pre-fill strikes
        agent.loop_tracker.record_cycle(1, "prior rejection")

        issues = [{"number": 1, "title": "[P2] Bug"}]
        result = agent.run("/tmp", issues=issues)

        assert result["results"][0]["action"] == "escalated"
        runner.run.assert_not_called()  # No review session needed

    def test_max_reviews_per_run(self, tmp_path: Path):
        config = ReviewerConfig(max_reviews_per_run=2)
        agent, runner, github, prs, notifier = self._make_agent(tmp_path, config)
        runner.run.return_value = SessionResult(
            success=True, reason="completed", events=[]
        )
        prs.create_pr.return_value = "url"

        issues = [
            {"number": i, "title": f"Bug {i}", "body": "x"}
            for i in range(5)
        ]
        result = agent.run("/tmp", issues=issues)
        assert result["reviews"] == 2

    def test_distributed_lock_skipped_when_none(self, tmp_path: Path):
        """No distributed_locks means no distributed locking."""
        agent, runner, github, prs, notifier = self._make_agent(tmp_path)
        assert agent.distributed_locks is None
        runner.run.return_value = SessionResult(
            success=True, reason="completed",
            events=[{"data": {"type": "stop", "response": "APPROVED"}}],
        )
        prs.create_pr.return_value = "url"
        issues = [{"number": 1, "title": "Bug", "body": "x"}]
        result = agent.run("/tmp", issues=issues)
        assert result["results"][0]["action"] == "approved"

    def test_distributed_lock_released_after_review(self, tmp_path: Path):
        agent, runner, github, prs, notifier = self._make_agent(tmp_path)
        dlocks = MagicMock(spec=DistributedLockManager)
        agent.distributed_locks = dlocks
        dlocks.is_claimed.return_value = False
        dlocks.acquire.return_value = True
        runner.run.return_value = SessionResult(
            success=True, reason="completed",
            events=[{"data": {"type": "stop", "response": "APPROVED"}}],
        )
        prs.create_pr.return_value = "url"
        issues = [{"number": 7, "title": "Bug", "body": "x"}]
        agent.run("/tmp", issues=issues)
        dlocks.release.assert_called_once_with(7)


class TestCheckApproval:
    """Tests for improved approval parsing."""

    def _make_agent(self, tmp_path):
        runner = MagicMock(spec=SessionRunner)
        config = ReviewerConfig()
        github = MagicMock(spec=GitHubIssues)
        prs = MagicMock(spec=GitHubPRs)
        strikes = StrikeTracker(tmp_path / "strikes.json")
        loop_tracker = LoopTracker(strikes, max_cycles=3)
        notifier = MagicMock(spec=TelegramNotifier)
        return ReviewerAgent(runner, config, github, prs, loop_tracker, notifier)

    def test_json_verdict_approved(self, tmp_path):
        agent = self._make_agent(tmp_path)
        result = SessionResult(
            success=True, reason="done",
            events=[{"data": {"message": '```json\n{"verdict": "approved", "reason": "looks good"}\n```'}}],
        )
        assert agent._check_approval(result) is True

    def test_json_verdict_rejected(self, tmp_path):
        agent = self._make_agent(tmp_path)
        result = SessionResult(
            success=True, reason="done",
            events=[{"data": {"message": '```json\n{"verdict": "rejected", "reason": "needs tests"}\n```'}}],
        )
        assert agent._check_approval(result) is False

    def test_keyword_approved_in_response(self, tmp_path):
        agent = self._make_agent(tmp_path)
        result = SessionResult(
            success=True, reason="done",
            events=[{"data": {"response": "After thorough review: APPROVED"}}],
        )
        assert agent._check_approval(result) is True

    def test_keyword_rejected_in_response(self, tmp_path):
        agent = self._make_agent(tmp_path)
        result = SessionResult(
            success=True, reason="done",
            events=[{"data": {"response": "REJECTED - needs more work"}}],
        )
        assert agent._check_approval(result) is False

    def test_keyword_in_text_field(self, tmp_path):
        agent = self._make_agent(tmp_path)
        result = SessionResult(
            success=True, reason="done",
            events=[{"text": "Review complete: APPROVED"}],
        )
        assert agent._check_approval(result) is True

    def test_keyword_in_reason_fallback(self, tmp_path):
        agent = self._make_agent(tmp_path)
        result = SessionResult(
            success=True, reason="APPROVED after review",
            events=[],
        )
        assert agent._check_approval(result) is True

    def test_json_verdict_takes_priority_over_keywords(self, tmp_path):
        """JSON verdict should win even if keywords say otherwise."""
        agent = self._make_agent(tmp_path)
        result = SessionResult(
            success=True, reason="done",
            events=[{"data": {"message": 'The fix was APPROVED but ```json\n{"verdict": "rejected"}\n```'}}],
        )
        assert agent._check_approval(result) is False

    def test_fallback_to_result_success(self, tmp_path):
        agent = self._make_agent(tmp_path)
        result = SessionResult(success=True, reason="done", events=[])
        assert agent._check_approval(result) is True

    def test_fallback_to_result_failure(self, tmp_path):
        agent = self._make_agent(tmp_path)
        result = SessionResult(success=False, reason="timeout", events=[])
        assert agent._check_approval(result) is False


class TestParseJsonVerdict:
    def test_approved(self):
        assert ReviewerAgent._parse_json_verdict('```json\n{"verdict": "approved"}\n```') is True

    def test_rejected(self):
        assert ReviewerAgent._parse_json_verdict('```json\n{"verdict": "rejected"}\n```') is False

    def test_pass_variant(self):
        assert ReviewerAgent._parse_json_verdict('```json\n{"verdict": "pass"}\n```') is True

    def test_fail_variant(self):
        assert ReviewerAgent._parse_json_verdict('```json\n{"verdict": "fail"}\n```') is False

    def test_no_json(self):
        assert ReviewerAgent._parse_json_verdict("plain text with no JSON") is None

    def test_json_without_verdict(self):
        assert ReviewerAgent._parse_json_verdict('```json\n{"status": "ok"}\n```') is None

    def test_invalid_json(self):
        assert ReviewerAgent._parse_json_verdict('```json\n{bad json}\n```') is None


class TestKeywordVerdict:
    def test_approved(self):
        assert ReviewerAgent._keyword_verdict("The fix is APPROVED") is True

    def test_rejected(self):
        assert ReviewerAgent._keyword_verdict("REJECTED: needs work") is False

    def test_rejected_takes_priority(self):
        assert ReviewerAgent._keyword_verdict("APPROVED but then REJECTED") is False

    def test_no_keywords(self):
        assert ReviewerAgent._keyword_verdict("The fix looks reasonable") is None

    def test_empty(self):
        assert ReviewerAgent._keyword_verdict("") is None


class TestEmptyBranchGuard:
    """Test that empty branches are rejected before PR creation."""

    def _make_agent(self, tmp_path):
        runner = MagicMock(spec=SessionRunner)
        config = ReviewerConfig()
        github = MagicMock(spec=GitHubIssues)
        prs = MagicMock(spec=GitHubPRs)
        strikes = StrikeTracker(tmp_path / "strikes.json")
        loop_tracker = LoopTracker(strikes, max_cycles=3)
        notifier = MagicMock(spec=TelegramNotifier)
        return ReviewerAgent(
            runner, config, github, prs, loop_tracker, notifier,
            repo_name="test/repo",
        ), runner, github, prs

    @patch.object(ReviewerAgent, "_get_branch_files", return_value=[])
    def test_empty_branch_rejected(self, mock_files, tmp_path):
        agent, runner, github, prs = self._make_agent(tmp_path)
        runner.run.return_value = SessionResult(
            success=True, reason="completed",
            events=[{"data": {"response": "APPROVED"}}],
        )
        issues = [{"number": 5, "title": "Bug", "body": "x"}]
        result = agent.run("/tmp", issues=issues)

        assert result["results"][0]["action"] == "rejected"
        assert result["results"][0]["reason"] == "empty-branch"
        prs.create_pr.assert_not_called()
        github.close_issue.assert_not_called()
        github.update_labels.assert_called_with(
            5, add=["needs-fix"], remove=["needs-review"]
        )

    @patch.object(ReviewerAgent, "_get_branch_files", return_value=["src/fix.py"])
    def test_non_empty_branch_proceeds(self, mock_files, tmp_path):
        agent, runner, github, prs = self._make_agent(tmp_path)
        runner.run.return_value = SessionResult(
            success=True, reason="completed",
            events=[{"data": {"response": "APPROVED"}}],
        )
        prs.create_pr.return_value = "https://github.com/test/pull/1"
        issues = [{"number": 5, "title": "Bug", "body": "x"}]
        result = agent.run("/tmp", issues=issues)

        assert result["results"][0]["action"] == "approved"
        prs.create_pr.assert_called_once()


class TestOutputFieldApproval:
    """Test that codex stdout (result.output) is used for verdict parsing."""

    def _make_agent(self, tmp_path):
        runner = MagicMock(spec=SessionRunner)
        config = ReviewerConfig()
        github = MagicMock(spec=GitHubIssues)
        prs = MagicMock(spec=GitHubPRs)
        strikes = StrikeTracker(tmp_path / "strikes.json")
        loop_tracker = LoopTracker(strikes, max_cycles=3)
        notifier = MagicMock(spec=TelegramNotifier)
        return ReviewerAgent(runner, config, github, prs, loop_tracker, notifier)

    def test_output_field_approved(self, tmp_path):
        agent = self._make_agent(tmp_path)
        result = SessionResult(
            success=True, reason="completed", events=[],
            output="Review complete. APPROVED - fix looks correct.",
        )
        assert agent._check_approval(result) is True

    def test_output_field_rejected(self, tmp_path):
        agent = self._make_agent(tmp_path)
        result = SessionResult(
            success=True, reason="completed", events=[],
            output="REJECTED - no test coverage for edge cases.",
        )
        assert agent._check_approval(result) is False

    def test_output_field_json_verdict(self, tmp_path):
        agent = self._make_agent(tmp_path)
        result = SessionResult(
            success=True, reason="completed", events=[],
            output='```json\n{"verdict": "rejected", "reason": "missing tests"}\n```',
        )
        assert agent._check_approval(result) is False


class TestAutoMerge:
    """Test auto-merge after PR creation."""

    def _make_agent(self, tmp_path, auto_merge=True):
        runner = MagicMock(spec=SessionRunner)
        config = ReviewerConfig(auto_merge=auto_merge)
        github = MagicMock(spec=GitHubIssues)
        prs = MagicMock(spec=GitHubPRs)
        strikes = StrikeTracker(tmp_path / "strikes.json")
        loop_tracker = LoopTracker(strikes, max_cycles=3)
        notifier = MagicMock(spec=TelegramNotifier)
        return ReviewerAgent(
            runner, config, github, prs, loop_tracker, notifier,
            repo_name="test/repo",
        ), runner, github, prs

    @patch.object(ReviewerAgent, "_get_branch_files", return_value=["src/fix.py"])
    def test_auto_merge_after_pr_creation(self, mock_files, tmp_path):
        agent, runner, github, prs = self._make_agent(tmp_path, auto_merge=True)
        runner.run.return_value = SessionResult(
            success=True, reason="completed",
            events=[{"data": {"response": "APPROVED"}}],
        )
        prs.create_pr.return_value = "https://github.com/test/repo/pull/42"
        prs.merge_pr.return_value = True

        issues = [{"number": 5, "title": "Bug", "body": "x"}]
        result = agent.run("/tmp", issues=issues)

        assert result["results"][0]["merged"] is True
        prs.merge_pr.assert_called_once_with(42)
        github.close_issue.assert_called_once_with(5)

    @patch.object(ReviewerAgent, "_get_branch_files", return_value=["src/fix.py"])
    def test_auto_merge_disabled(self, mock_files, tmp_path):
        agent, runner, github, prs = self._make_agent(tmp_path, auto_merge=False)
        runner.run.return_value = SessionResult(
            success=True, reason="completed",
            events=[{"data": {"response": "APPROVED"}}],
        )
        prs.create_pr.return_value = "https://github.com/test/repo/pull/42"

        issues = [{"number": 5, "title": "Bug", "body": "x"}]
        result = agent.run("/tmp", issues=issues)

        assert result["results"][0]["merged"] is False
        prs.merge_pr.assert_not_called()
        github.close_issue.assert_called_once_with(5)

    @patch.object(ReviewerAgent, "_get_branch_files", return_value=["src/fix.py"])
    def test_merge_failure_still_closes_issue(self, mock_files, tmp_path):
        agent, runner, github, prs = self._make_agent(tmp_path, auto_merge=True)
        runner.run.return_value = SessionResult(
            success=True, reason="completed",
            events=[{"data": {"response": "APPROVED"}}],
        )
        prs.create_pr.return_value = "https://github.com/test/repo/pull/42"
        prs.merge_pr.return_value = False  # Merge failed

        issues = [{"number": 5, "title": "Bug", "body": "x"}]
        result = agent.run("/tmp", issues=issues)

        assert result["results"][0]["merged"] is False
        github.close_issue.assert_called_once_with(5)


class TestExtractPrNumber:
    def test_standard_url(self):
        assert ReviewerAgent._extract_pr_number("https://github.com/test/repo/pull/42") == 42

    def test_no_match(self):
        assert ReviewerAgent._extract_pr_number("https://github.com/test/repo") is None

    def test_url_with_trailing(self):
        assert ReviewerAgent._extract_pr_number("https://github.com/test/repo/pull/123/files") == 123


class TestSelfImprovementGuard:
    def _make_agent(self, tmp_path, self_improve=True):
        runner = MagicMock(spec=SessionRunner)
        config = ReviewerConfig()
        github = MagicMock(spec=GitHubIssues)
        prs = MagicMock(spec=GitHubPRs)
        strikes = StrikeTracker(tmp_path / "strikes.json")
        loop_tracker = LoopTracker(strikes, max_cycles=3)
        notifier = MagicMock(spec=TelegramNotifier)
        return ReviewerAgent(
            runner, config, github, prs, loop_tracker, notifier,
            repo_name="test/repo", self_improve=self_improve,
        ), runner, github, prs, notifier

    @patch.object(ReviewerAgent, "_get_branch_files")
    def test_protected_files_trigger_human_review(self, mock_files, tmp_path):
        agent, runner, github, prs, notifier = self._make_agent(tmp_path, self_improve=True)
        runner.run.return_value = SessionResult(
            success=True, reason="done",
            events=[{"data": {"response": "APPROVED"}}],
        )
        prs.create_pr.return_value = "https://github.com/test/repo/pull/1"
        mock_files.return_value = ["src/wiz/config/schema.py", "src/wiz/agents/foo.py"]

        issues = [{"number": 1, "title": "Bug fix", "body": "x"}]
        result = agent.run("/tmp", issues=issues)

        assert result["results"][0]["needs_human_review"] is True
        github.update_labels.assert_any_call(1, add=["requires-human-review"])
        notifier.notify_escalation.assert_called_once()
        # Issue should NOT be closed when human review needed
        github.close_issue.assert_not_called()

    @patch.object(ReviewerAgent, "_get_branch_files")
    def test_no_protected_files_auto_closes(self, mock_files, tmp_path):
        agent, runner, github, prs, notifier = self._make_agent(tmp_path, self_improve=True)
        runner.run.return_value = SessionResult(
            success=True, reason="done",
            events=[{"data": {"response": "APPROVED"}}],
        )
        prs.create_pr.return_value = "https://github.com/test/repo/pull/1"
        mock_files.return_value = ["src/wiz/agents/foo.py", "tests/test_foo.py"]

        issues = [{"number": 1, "title": "Bug fix", "body": "x"}]
        result = agent.run("/tmp", issues=issues)

        assert result["results"][0]["needs_human_review"] is False
        github.close_issue.assert_called_once_with(1)
        notifier.notify_escalation.assert_not_called()

    def test_guard_not_created_when_self_improve_false(self, tmp_path):
        agent, _, _, _, _ = self._make_agent(tmp_path, self_improve=False)
        assert agent.guard is None

    def test_guard_created_when_self_improve_true(self, tmp_path):
        agent, _, _, _, _ = self._make_agent(tmp_path, self_improve=True)
        assert agent.guard is not None


class TestReviewerModelPassthrough:
    """Regression test for issue #53: model config must reach runner.run."""

    def test_model_passed_to_runner(self, tmp_path):
        config = ReviewerConfig(model="custom-model")
        runner = MagicMock(spec=SessionRunner)
        github = MagicMock(spec=GitHubIssues)
        prs = MagicMock(spec=GitHubPRs)
        strikes = StrikeTracker(tmp_path / "strikes.json")
        loop_tracker = LoopTracker(strikes, max_cycles=3)
        notifier = MagicMock(spec=TelegramNotifier)
        agent = ReviewerAgent(runner, config, github, prs, loop_tracker, notifier)

        runner.run.return_value = SessionResult(
            success=True, reason="completed",
            events=[{"data": {"response": "APPROVED"}}],
        )
        prs.create_pr.return_value = "https://github.com/test/repo/pull/1"

        issues = [{"number": 1, "title": "Bug", "body": "x"}]
        agent.run("/tmp", issues=issues)

        assert runner.run.call_args[1]["model"] == "custom-model"
