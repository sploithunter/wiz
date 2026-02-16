"""Tests for blog writer agent.

Includes regression test for issue #53: model config passthrough.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from wiz.agents.blog_writer import (
    PROPOSED_TOPIC_KEY,
    BlogWriterAgent,
    gather_github_activity,
    gather_session_log_context,
)
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import BlogContextConfig, BlogWriterConfig, RepoConfig
from wiz.memory.long_term import LongTermMemory


class TestBlogWriterAgent:
    def _make_agent(self, config=None, with_memory=False):
        runner = MagicMock(spec=SessionRunner)
        config = config or BlogWriterConfig()
        memory = MagicMock(spec=LongTermMemory) if with_memory else None
        if memory:
            memory.retrieve.return_value = [("blog-topic", "Previous post about X")]
        return BlogWriterAgent(runner, config, memory), runner, memory

    def test_topic_proposal_prompt(self):
        agent, _, _ = self._make_agent()
        prompt = agent.build_prompt(mode="propose")
        assert "Propose Blog Topics" in prompt

    def test_draft_generation_prompt(self):
        agent, _, _ = self._make_agent()
        prompt = agent.build_prompt(mode="write", topic="Building AI Agents")
        assert "Building AI Agents" in prompt
        assert "Write Blog Draft" in prompt

    def test_memory_dedup(self):
        agent, _, memory = self._make_agent(with_memory=True)
        prompt = agent.build_prompt(mode="propose")
        assert "Recent Topics" in prompt
        memory.retrieve.assert_called()

    def test_process_result_updates_memory(self):
        agent, _, memory = self._make_agent(with_memory=True)
        result = SessionResult(success=True, reason="completed")
        agent.process_result(result, topic="Test Topic", mode="write")
        memory.update_topic.assert_called_once()

    def test_process_result_failure(self):
        agent, _, _ = self._make_agent()
        result = SessionResult(success=False, reason="timeout")
        output = agent.process_result(result)
        assert output["success"] is False

    @patch("wiz.agents.blog_writer.save_all_image_prompts")
    def test_process_result_saves_image_prompts(self, mock_save):
        mock_save.return_value = [Path("/tmp/prompt.md")]

        agent, _, _ = self._make_agent()
        json_block = '```json\n{"draft_title": "My Article", "image_prompt": "A sunset"}\n```'
        result = SessionResult(
            success=True,
            reason="completed",
            events=[{"data": {"message": json_block}}],
        )
        output = agent.process_result(result, mode="write")
        assert output["image_prompts_saved"] == 1
        mock_save.assert_called_once()

    def test_process_result_no_image_prompt(self):
        agent, _, _ = self._make_agent()
        result = SessionResult(success=True, reason="completed", events=[])
        output = agent.process_result(result, mode="write")
        assert output["image_prompts_saved"] == 0

    def test_process_result_creates_google_doc(self):
        from wiz.integrations.google_docs import DocResult, GoogleDocsClient

        gdocs = MagicMock(spec=GoogleDocsClient)
        gdocs.enabled = True
        gdocs.create_document.return_value = DocResult(
            success=True, doc_id="d1", url="https://docs.google.com/document/d/d1/edit"
        )

        agent, _, _ = self._make_agent()
        agent.google_docs = gdocs
        result = SessionResult(
            success=True,
            reason="completed",
            events=[{"data": {"message": "Some blog content"}}],
        )
        output = agent.process_result(result, mode="write", topic="My Topic")
        assert output["doc_url"] == "https://docs.google.com/document/d/d1/edit"
        gdocs.create_document.assert_called_once()
        # Disk-based image prompts should be skipped when Google Docs is enabled
        assert output["image_prompts_saved"] == 0

    def test_process_result_no_google_doc_when_disabled(self):
        agent, _, _ = self._make_agent()
        result = SessionResult(success=True, reason="completed", events=[])
        output = agent.process_result(result, mode="write")
        assert output["doc_url"] is None


class TestBlogWriterRun:
    """Tests for the run() method with mode transition logic."""

    def _make_agent(self, config=None, with_memory=True):
        runner = MagicMock(spec=SessionRunner)
        config = config or BlogWriterConfig(require_approval=False)
        memory = MagicMock(spec=LongTermMemory) if with_memory else None
        if memory:
            memory.retrieve.return_value = []
        return BlogWriterAgent(runner, config, memory), runner, memory

    @patch("wiz.agents.blog_writer.save_all_image_prompts", return_value=[])
    def test_run_propose_mode_when_no_pending_topic(self, _mock_img):
        """First run with no pending topic → propose mode."""
        agent, runner, memory = self._make_agent()
        memory.retrieve.return_value = []  # no pending topic

        runner.run.return_value = SessionResult(
            success=True,
            reason="completed",
            events=[{"data": {"message": "Topic: How to build AI agents"}}],
        )

        result = agent.run("/tmp")
        assert result["mode"] == "propose"
        assert result["success"] is True
        # Should have stored the proposed topic
        memory.update_topic.assert_called()
        memory.save_index.assert_called()

    @patch("wiz.agents.blog_writer.save_all_image_prompts", return_value=[])
    def test_run_write_mode_when_pending_topic_exists(self, _mock_img):
        """Second run with pending topic → write mode."""
        agent, runner, memory = self._make_agent()
        # Simulate a pending topic in memory
        memory.retrieve.return_value = [
            (PROPOSED_TOPIC_KEY, "How to build AI agents")
        ]

        runner.run.return_value = SessionResult(
            success=True,
            reason="completed",
            events=[{"data": {"message": "# How to build AI agents\n\nGreat article..."}}],
        )

        result = agent.run("/tmp")
        assert result["mode"] == "write"
        assert result["success"] is True
        # Should have consumed the pending topic
        memory.delete_topic.assert_called_once_with(PROPOSED_TOPIC_KEY)
        memory.save_index.assert_called()

    @patch("wiz.agents.blog_writer.save_all_image_prompts", return_value=[])
    def test_run_write_failure_keeps_pending_topic(self, _mock_img):
        """If write fails, don't consume the pending topic."""
        agent, runner, memory = self._make_agent()
        memory.retrieve.return_value = [
            (PROPOSED_TOPIC_KEY, "How to build AI agents")
        ]

        runner.run.return_value = SessionResult(
            success=False,
            reason="timeout",
        )

        result = agent.run("/tmp")
        assert result["success"] is False
        # Should NOT have consumed the pending topic
        memory.delete_topic.assert_not_called()

    def test_run_skips_when_auto_propose_disabled_and_no_topic(self):
        """No pending topic + auto_propose_topics=False → skip."""
        config = BlogWriterConfig(auto_propose_topics=False)
        agent, runner, memory = self._make_agent(config)
        memory.retrieve.return_value = []

        result = agent.run("/tmp")
        assert result["skipped"] is True
        assert result["reason"] == "no_pending_topics"
        runner.run.assert_not_called()

    @patch("wiz.agents.blog_writer.save_all_image_prompts", return_value=[])
    def test_run_propose_stores_topic_from_events(self, _mock_img):
        """Propose mode stores topic text extracted from events."""
        agent, runner, memory = self._make_agent()
        memory.retrieve.return_value = []

        runner.run.return_value = SessionResult(
            success=True,
            reason="completed",
            events=[{"data": {"message": "Proposed: Building reliable AI pipelines"}}],
        )

        agent.run("/tmp")
        # Check update_topic was called with the proposed content
        calls = memory.update_topic.call_args_list
        stored_call = [c for c in calls if c[0][0] == PROPOSED_TOPIC_KEY]
        assert len(stored_call) == 1
        assert "Building reliable AI pipelines" in stored_call[0][0][2]

    @patch("wiz.agents.blog_writer.save_all_image_prompts", return_value=[])
    def test_run_propose_stores_topic_from_reason_fallback(self, _mock_img):
        """If no events, fall back to result.reason for topic text."""
        agent, runner, memory = self._make_agent()
        memory.retrieve.return_value = []

        runner.run.return_value = SessionResult(
            success=True,
            reason="Topic: Scaling agent architectures",
            events=[],
        )

        agent.run("/tmp")
        calls = memory.update_topic.call_args_list
        stored_call = [c for c in calls if c[0][0] == PROPOSED_TOPIC_KEY]
        assert len(stored_call) == 1
        assert "Scaling agent architectures" in stored_call[0][0][2]

    @patch("wiz.agents.blog_writer.save_all_image_prompts", return_value=[])
    def test_run_propose_failure_no_store(self, _mock_img):
        """If propose fails, don't store anything."""
        agent, runner, memory = self._make_agent()
        memory.retrieve.return_value = []

        runner.run.return_value = SessionResult(
            success=False,
            reason="timeout",
        )

        agent.run("/tmp")
        # update_topic should not be called with PROPOSED_TOPIC_KEY
        calls = memory.update_topic.call_args_list
        stored_call = [c for c in calls if c[0][0] == PROPOSED_TOPIC_KEY]
        assert len(stored_call) == 0

    @patch("wiz.agents.blog_writer.save_all_image_prompts", return_value=[])
    def test_run_write_mode_uses_correct_session_name(self, _mock_img):
        """Write mode uses 'wiz-blog-write' session name."""
        agent, runner, memory = self._make_agent()
        memory.retrieve.return_value = [
            (PROPOSED_TOPIC_KEY, "Test topic")
        ]
        runner.run.return_value = SessionResult(success=True, reason="done")

        agent.run("/tmp")
        call_kwargs = runner.run.call_args[1]
        assert call_kwargs["name"] == "wiz-blog-write"

    @patch("wiz.agents.blog_writer.save_all_image_prompts", return_value=[])
    def test_run_propose_mode_uses_correct_session_name(self, _mock_img):
        """Propose mode uses 'wiz-blog-propose' session name."""
        agent, runner, memory = self._make_agent()
        memory.retrieve.return_value = []
        runner.run.return_value = SessionResult(
            success=True, reason="done",
            events=[{"data": {"message": "topic idea"}}],
        )

        agent.run("/tmp")
        call_kwargs = runner.run.call_args[1]
        assert call_kwargs["name"] == "wiz-blog-propose"

    @patch("wiz.agents.blog_writer.save_all_image_prompts", return_value=[])
    def test_run_without_memory_defaults_to_propose(self, _mock_img):
        """Without memory, always runs in propose mode."""
        config = BlogWriterConfig(require_approval=False)
        agent, runner, _ = self._make_agent(config=config, with_memory=False)
        runner.run.return_value = SessionResult(success=True, reason="done")

        result = agent.run("/tmp")
        assert result["mode"] == "propose"

    @patch("wiz.agents.blog_writer.save_all_image_prompts", return_value=[])
    def test_run_write_mode_passes_topic_to_prompt(self, _mock_img):
        """Write mode includes the topic in the prompt."""
        agent, runner, memory = self._make_agent()
        memory.retrieve.return_value = [
            (PROPOSED_TOPIC_KEY, "Building AI agents with Python")
        ]
        runner.run.return_value = SessionResult(success=True, reason="done")

        agent.run("/tmp")
        call_kwargs = runner.run.call_args[1]
        assert "Building AI agents with Python" in call_kwargs["prompt"]


class TestGetPendingTopic:
    def test_returns_none_without_memory(self):
        runner = MagicMock(spec=SessionRunner)
        agent = BlogWriterAgent(runner, BlogWriterConfig(), memory=None)
        assert agent._get_pending_topic() is None

    def test_returns_topic_when_found(self):
        runner = MagicMock(spec=SessionRunner)
        memory = MagicMock(spec=LongTermMemory)
        memory.retrieve.return_value = [
            (PROPOSED_TOPIC_KEY, "How to debug AI systems")
        ]
        agent = BlogWriterAgent(runner, BlogWriterConfig(), memory=memory)
        assert agent._get_pending_topic() == "How to debug AI systems"

    def test_returns_none_when_empty_content(self):
        runner = MagicMock(spec=SessionRunner)
        memory = MagicMock(spec=LongTermMemory)
        memory.retrieve.return_value = [(PROPOSED_TOPIC_KEY, "   ")]
        agent = BlogWriterAgent(runner, BlogWriterConfig(), memory=memory)
        assert agent._get_pending_topic() is None

    def test_returns_none_when_no_match(self):
        runner = MagicMock(spec=SessionRunner)
        memory = MagicMock(spec=LongTermMemory)
        memory.retrieve.return_value = [("other-key", "some content")]
        agent = BlogWriterAgent(runner, BlogWriterConfig(), memory=memory)
        assert agent._get_pending_topic() is None


class TestGatherSessionLogContext:
    def test_returns_empty_for_missing_dir(self, tmp_path):
        result = gather_session_log_context(tmp_path / "nonexistent")
        assert result == ""

    def test_returns_empty_for_empty_dir(self, tmp_path):
        log_dir = tmp_path / "sessions"
        log_dir.mkdir()
        result = gather_session_log_context(log_dir)
        assert result == ""

    def test_reads_session_logs(self, tmp_path):
        log_dir = tmp_path / "sessions"
        log_dir.mkdir()
        log1 = log_dir / "session_20260101_120000_dev.log"
        log1.write_text("[2026-01-01 12:00:00] Session started: dev\n[2026-01-01 12:05:00] Fixed bug #42\n")

        result = gather_session_log_context(log_dir)
        assert "session_20260101_120000_dev.log" in result
        assert "Fixed bug #42" in result

    def test_limits_number_of_files(self, tmp_path):
        log_dir = tmp_path / "sessions"
        log_dir.mkdir()
        for i in range(10):
            f = log_dir / f"session_20260101_{i:06d}.log"
            f.write_text(f"[2026-01-01] Session {i}\n")

        result = gather_session_log_context(log_dir, max_files=3)
        # Should only include 3 most recent files
        assert result.count("###") == 3


class TestGatherGitHubActivity:
    @patch("wiz.agents.blog_writer.subprocess.run")
    def test_fetches_issues_for_enabled_repos(self, mock_run):
        import json
        mock_run.return_value = MagicMock(
            stdout=json.dumps([
                {"number": 1, "title": "Add feature", "state": "OPEN", "updatedAt": "2026-01-01", "labels": []},
            ]),
            returncode=0,
        )

        repos = [RepoConfig(name="wiz", path="/tmp/wiz", github="sploithunter/wiz")]
        result = gather_github_activity(repos, exclude_repos=[], limit=5)
        assert "sploithunter/wiz" in result
        assert "Add feature" in result

    @patch("wiz.agents.blog_writer.subprocess.run")
    def test_excludes_repos_by_github_name(self, mock_run):
        repos = [RepoConfig(name="wiz", path="/tmp/wiz", github="sploithunter/wiz")]
        result = gather_github_activity(repos, exclude_repos=["sploithunter/wiz"], limit=5)
        assert result == ""
        mock_run.assert_not_called()

    @patch("wiz.agents.blog_writer.subprocess.run")
    def test_excludes_repos_by_short_name(self, mock_run):
        repos = [RepoConfig(name="wiz", path="/tmp/wiz", github="sploithunter/wiz")]
        result = gather_github_activity(repos, exclude_repos=["wiz"], limit=5)
        assert result == ""
        mock_run.assert_not_called()

    @patch("wiz.agents.blog_writer.subprocess.run")
    def test_excludes_repos_by_substring(self, mock_run):
        repos = [
            RepoConfig(name="genesis-api", path="/tmp/g1", github="sploithunter/genesis-api"),
            RepoConfig(name="genesis-core", path="/tmp/g2", github="sploithunter/genesis-core"),
            RepoConfig(name="wiz", path="/tmp/wiz", github="sploithunter/wiz"),
        ]
        mock_run.return_value = MagicMock(
            stdout='[{"number": 1, "title": "Test", "state": "OPEN", "updatedAt": "2026-01-01", "labels": []}]',
            returncode=0,
        )
        result = gather_github_activity(repos, exclude_repos=["genesis"], limit=5)
        # Only wiz should be included, both genesis repos excluded
        assert "genesis" not in result.lower()
        assert "wiz" in result

    @patch("wiz.agents.blog_writer.subprocess.run")
    def test_skips_disabled_repos(self, mock_run):
        repos = [RepoConfig(name="wiz", path="/tmp/wiz", github="sploithunter/wiz", enabled=False)]
        result = gather_github_activity(repos, exclude_repos=[], limit=5)
        assert result == ""
        mock_run.assert_not_called()

    @patch("wiz.agents.blog_writer.subprocess.run")
    def test_handles_gh_failure_gracefully(self, mock_run):
        import subprocess as sp
        mock_run.side_effect = sp.CalledProcessError(1, "gh")

        repos = [RepoConfig(name="wiz", path="/tmp/wiz", github="sploithunter/wiz")]
        result = gather_github_activity(repos, exclude_repos=[], limit=5)
        assert result == ""


class TestBlogWriterActivityContext:
    def test_prompt_includes_session_log_context(self, tmp_path):
        # Create a session log
        log_dir = tmp_path / "memory" / "sessions"
        log_dir.mkdir(parents=True)
        (log_dir / "session_20260101_120000.log").write_text(
            "[2026-01-01 12:00:00] Fixed critical auth bug\n"
        )

        config = BlogWriterConfig(
            context_sources=BlogContextConfig(session_logs=True, github_activity=False),
        )
        runner = MagicMock(spec=SessionRunner)
        agent = BlogWriterAgent(runner, config)

        # Patch the session log dir to point to our tmp dir
        with patch("wiz.agents.blog_writer.gather_session_log_context") as mock_logs:
            mock_logs.return_value = "Fixed critical auth bug"
            prompt = agent.build_prompt(mode="propose")
            assert "Fixed critical auth bug" in prompt

    def test_prompt_includes_github_activity(self):
        config = BlogWriterConfig(
            context_sources=BlogContextConfig(session_logs=False, github_activity=True),
        )
        repos = [RepoConfig(name="wiz", path="/tmp", github="sploithunter/wiz")]
        runner = MagicMock(spec=SessionRunner)
        agent = BlogWriterAgent(runner, config, repos=repos)

        with patch("wiz.agents.blog_writer.gather_github_activity") as mock_gh:
            mock_gh.return_value = "### sploithunter/wiz — Recent Issues\n- #42 (OPEN) New feature"
            prompt = agent.build_prompt(mode="propose")
            assert "Recent GitHub Activity" in prompt
            assert "New feature" in prompt

    def test_prompt_excludes_disabled_sources(self):
        config = BlogWriterConfig(
            context_sources=BlogContextConfig(session_logs=False, github_activity=False),
        )
        runner = MagicMock(spec=SessionRunner)
        agent = BlogWriterAgent(runner, config)

        with patch("wiz.agents.blog_writer.gather_session_log_context") as mock_logs, \
             patch("wiz.agents.blog_writer.gather_github_activity") as mock_gh:
            prompt = agent.build_prompt(mode="propose")
            mock_logs.assert_not_called()
            mock_gh.assert_not_called()
            assert "Recent Wiz Session Activity" not in prompt
            assert "Recent GitHub Activity" not in prompt

    def test_repos_stored_on_agent(self):
        repos = [RepoConfig(name="wiz", path="/tmp", github="sploithunter/wiz")]
        runner = MagicMock(spec=SessionRunner)
        agent = BlogWriterAgent(runner, BlogWriterConfig(), repos=repos)
        assert agent.repos == repos

    def test_repos_defaults_to_empty(self):
        runner = MagicMock(spec=SessionRunner)
        agent = BlogWriterAgent(runner, BlogWriterConfig())
        assert agent.repos == []


class TestBlogWriterModelPassthrough:
    """Regression test for issue #53: model config must reach runner.run."""

    @patch("wiz.agents.blog_writer.save_all_image_prompts", return_value=[])
    def test_model_passed_in_write_mode(self, _mock_img):
        config = BlogWriterConfig(model="custom-model", require_approval=False)
        runner = MagicMock(spec=SessionRunner)
        memory = MagicMock(spec=LongTermMemory)
        memory.retrieve.return_value = [(PROPOSED_TOPIC_KEY, "Test topic")]
        agent = BlogWriterAgent(runner, config, memory=memory)

        runner.run.return_value = SessionResult(success=True, reason="done")
        agent.run("/tmp")

        assert runner.run.call_args[1]["model"] == "custom-model"

    @patch("wiz.agents.blog_writer.save_all_image_prompts", return_value=[])
    def test_model_passed_in_propose_mode(self, _mock_img):
        config = BlogWriterConfig(model="custom-model", require_approval=False)
        runner = MagicMock(spec=SessionRunner)
        memory = MagicMock(spec=LongTermMemory)
        memory.retrieve.return_value = []
        agent = BlogWriterAgent(runner, config, memory=memory)

        runner.run.return_value = SessionResult(
            success=True, reason="done",
            events=[{"data": {"message": "topic idea"}}],
        )
        agent.run("/tmp")

        assert runner.run.call_args[1]["model"] == "custom-model"
