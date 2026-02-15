"""Python types mirroring coding-agent-bridge API.md."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentType(str, Enum):
    CLAUDE = "claude"
    CODEX = "codex"
    CURSOR = "cursor"


class SessionStatus(str, Enum):
    IDLE = "idle"
    WORKING = "working"
    WAITING = "waiting"
    OFFLINE = "offline"


class EventType(str, Enum):
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    STOP = "stop"
    SUBAGENT_STOP = "subagent_stop"
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    USER_PROMPT_SUBMIT = "user_prompt_submit"
    NOTIFICATION = "notification"
    ASSISTANT_MESSAGE = "assistant_message"


@dataclass
class Session:
    id: str
    name: str
    agent: str
    status: str
    cwd: str
    created_at: int = 0
    last_activity: int = 0
    tmux_session: str | None = None
    agent_session_id: str | None = None
    current_tool: str | None = None
    transcript_path: str | None = None


@dataclass
class AgentEvent:
    id: str
    timestamp: int
    type: str
    session_id: str
    agent: str
    cwd: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionResult:
    success: bool
    reason: str
    elapsed: float = 0.0
    events: list[dict[str, Any]] = field(default_factory=list)
    output: str = ""
