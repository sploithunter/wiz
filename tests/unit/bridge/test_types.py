"""Tests for bridge types."""

from wiz.bridge.types import (
    AgentEvent,
    AgentType,
    EventType,
    Session,
    SessionResult,
    SessionStatus,
)


class TestEnums:
    def test_agent_types(self):
        assert AgentType.CLAUDE.value == "claude"
        assert AgentType.CODEX.value == "codex"
        assert AgentType.CURSOR.value == "cursor"

    def test_session_status(self):
        assert SessionStatus.IDLE.value == "idle"
        assert SessionStatus.WORKING.value == "working"
        assert SessionStatus.OFFLINE.value == "offline"

    def test_event_types(self):
        assert EventType.STOP.value == "stop"
        assert EventType.SESSION_END.value == "session_end"
        assert EventType.PRE_TOOL_USE.value == "pre_tool_use"


class TestDataclasses:
    def test_session_construction(self):
        s = Session(
            id="abc",
            name="test",
            agent="claude",
            status="idle",
            cwd="/tmp",
        )
        assert s.id == "abc"
        assert s.tmux_session is None

    def test_agent_event(self):
        e = AgentEvent(
            id="evt-1",
            timestamp=1000,
            type="stop",
            session_id="sess-1",
            agent="claude",
            cwd="/tmp",
        )
        assert e.data == {}

    def test_session_result(self):
        r = SessionResult(success=True, reason="completed", elapsed=5.0)
        assert r.events == []
        assert r.elapsed == 5.0
