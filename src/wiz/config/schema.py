"""Pydantic v2 models for Wiz configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GlobalConfig(BaseModel):
    coding_agent_bridge_url: str = "http://127.0.0.1:4003"
    bridge_data_dir: str = "~/.coding-agent-bridge"
    log_level: str = "info"
    timezone: str = "America/New_York"


class RepoConfig(BaseModel):
    name: str
    path: str
    github: str
    enabled: bool = True
    self_improve: bool = False


class BugHunterConfig(BaseModel):
    model: str = "codex"
    max_issues_per_run: int = 10
    min_severity: str = "P4"
    require_poc: bool = True
    session_timeout: int = 600
    flags: list[str] = Field(default_factory=list)


class BugFixerConfig(BaseModel):
    model: str = "claude"
    max_fixes_per_run: int = 5
    stagnation_limit: int = 3
    session_timeout: int = 600
    flags: list[str] = Field(default_factory=list)


class ReviewerConfig(BaseModel):
    model: str = "codex"
    max_reviews_per_run: int = 10
    max_review_cycles: int = 3
    session_timeout: int = 300
    flags: list[str] = Field(default_factory=list)


class FeatureProposerConfig(BaseModel):
    model: str = "claude"
    features_per_run: int = 1
    auto_propose_features: bool = True
    require_approval: bool = True
    session_timeout: int = 900
    flags: list[str] = Field(default_factory=list)


class BlogWriterConfig(BaseModel):
    model: str = "claude"
    auto_propose_topics: bool = True
    require_approval: bool = True
    output_dir: str = "~/Documents/blog-drafts"
    session_timeout: int = 600
    flags: list[str] = Field(default_factory=list)


class SocialManagerConfig(BaseModel):
    model: str = "claude"
    social_posts_per_week: int = 3
    platforms: list[str] = Field(default_factory=lambda: ["x"])
    require_approval: bool = True
    session_timeout: int = 300
    flags: list[str] = Field(default_factory=list)


class AgentsConfig(BaseModel):
    bug_hunter: BugHunterConfig = Field(default_factory=BugHunterConfig)
    bug_fixer: BugFixerConfig = Field(default_factory=BugFixerConfig)
    reviewer: ReviewerConfig = Field(default_factory=ReviewerConfig)
    feature_proposer: FeatureProposerConfig = Field(default_factory=FeatureProposerConfig)
    blog_writer: BlogWriterConfig = Field(default_factory=BlogWriterConfig)
    social_manager: SocialManagerConfig = Field(default_factory=SocialManagerConfig)


class DevCycleConfig(BaseModel):
    cycle_timeout: int = 3600
    phases: list[str] = Field(default_factory=lambda: ["bug_hunt", "bug_fix", "review"])
    parallel_fixes: bool = False


class ScheduleEntry(BaseModel):
    enabled: bool = True
    times: list[str] = Field(default_factory=lambda: ["07:00"])
    days: list[str] = Field(
        default_factory=lambda: ["mon", "tue", "wed", "thu", "fri"]
    )


class ScheduleConfig(BaseModel):
    dev_cycle: ScheduleEntry = Field(default_factory=ScheduleEntry)
    bug_hunt: ScheduleEntry | None = None
    bug_fix: ScheduleEntry | None = None
    review: ScheduleEntry | None = None
    feature_cycle: ScheduleEntry = Field(
        default_factory=lambda: ScheduleEntry(times=["09:00"], days=["mon", "wed", "fri"])
    )
    content_cycle: ScheduleEntry = Field(
        default_factory=lambda: ScheduleEntry(times=["10:00"], days=["tue", "thu"])
    )


class WorktreeConfig(BaseModel):
    base_dir: str = ".worktrees"
    stale_days: int = 7
    auto_cleanup_merged: bool = True


class LockingConfig(BaseModel):
    ttl: int = 600
    lock_dir: str = ".wiz/locks"


class EscalationConfig(BaseModel):
    max_issue_strikes: int = 3
    max_file_strikes: int = 3
    strike_file: str = ".wiz/strikes.json"


class MemoryConfig(BaseModel):
    short_term_max_lines: int = 50
    session_log_retention_days: int = 30
    long_term_dir: str = "memory/long-term"


class TestingConfig(BaseModel):
    run_full_suite_before_pr: bool = True
    require_new_tests_for_fixes: bool = True
    require_new_tests_for_features: bool = True
    no_known_bugs_for_completion: bool = True


class TelegramConfig(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""


class WizConfig(BaseModel):
    """Root configuration model for Wiz."""

    global_: GlobalConfig = Field(default_factory=GlobalConfig, alias="global")
    repos: list[RepoConfig] = Field(default_factory=list)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    dev_cycle: DevCycleConfig = Field(default_factory=DevCycleConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    worktrees: WorktreeConfig = Field(default_factory=WorktreeConfig)
    locking: LockingConfig = Field(default_factory=LockingConfig)
    escalation: EscalationConfig = Field(default_factory=EscalationConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    testing: TestingConfig = Field(default_factory=TestingConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)

    model_config = {"populate_by_name": True}
