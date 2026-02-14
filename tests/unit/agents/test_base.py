"""Tests for base agent."""

from typing import Any
from unittest.mock import MagicMock

from wiz.agents.base import BaseAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult


class ConcreteAgent(BaseAgent):
    agent_type = "claude"
    agent_name = "test-agent"

    def build_prompt(self, **kwargs: Any) -> str:
        return f"Test prompt: {kwargs.get('task', 'default')}"

    def process_result(self, result: SessionResult, **kwargs: Any) -> dict[str, Any]:
        return {"processed": True, "success": result.success}


class TestBaseAgent:
    def test_template_method_calls(self):
        runner = MagicMock(spec=SessionRunner)
        runner.run.return_value = SessionResult(
            success=True, reason="completed", elapsed=5.0
        )

        agent = ConcreteAgent(runner)
        result = agent.run("/tmp", timeout=60, task="find bugs")

        runner.run.assert_called_once_with(
            name="wiz-test-agent",
            cwd="/tmp",
            prompt="Test prompt: find bugs",
            agent="claude",
            timeout=60,
        )
        assert result["processed"] is True
        assert result["success"] is True

    def test_agent_type_passed_to_runner(self):
        runner = MagicMock(spec=SessionRunner)
        runner.run.return_value = SessionResult(
            success=False, reason="timeout", elapsed=600.0
        )

        agent = ConcreteAgent(runner)
        agent.agent_type = "codex"
        agent.run("/tmp")

        assert runner.run.call_args[1]["agent"] == "codex"

    def test_failed_result_propagated(self):
        runner = MagicMock(spec=SessionRunner)
        runner.run.return_value = SessionResult(
            success=False, reason="bridge_unavailable"
        )

        agent = ConcreteAgent(runner)
        result = agent.run("/tmp")
        assert result["success"] is False
