"""Cycle state tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PhaseResult:
    phase: str
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    elapsed: float = 0.0


@dataclass
class CycleState:
    """Tracks what happened in each phase for reporting."""

    repo: str
    phases: list[PhaseResult] = field(default_factory=list)
    total_elapsed: float = 0.0
    timed_out: bool = False

    def add_phase(
        self, phase: str, success: bool,
        data: dict[str, Any] = None, elapsed: float = 0.0,
    ) -> None:
        self.phases.append(PhaseResult(
            phase=phase,
            success=success,
            data=data or {},
            elapsed=elapsed,
        ))

    @property
    def bugs_found(self) -> int:
        for p in self.phases:
            if p.phase == "bug_hunt":
                return p.data.get("bugs_found", 0)
        return 0

    @property
    def issues_fixed(self) -> int:
        for p in self.phases:
            if p.phase == "bug_fix":
                return p.data.get("issues_processed", 0)
        return 0

    @property
    def reviews_completed(self) -> int:
        for p in self.phases:
            if p.phase == "review":
                return p.data.get("reviews", 0)
        return 0

    def summary(self) -> str:
        lines = [f"Repo: {self.repo}"]
        for p in self.phases:
            status = "OK" if p.success else "FAIL"
            lines.append(f"  {p.phase}: {status} ({p.elapsed:.1f}s)")
        if self.timed_out:
            lines.append("  TIMED OUT")
        lines.append(f"  Total: {self.total_elapsed:.1f}s")
        return "\n".join(lines)
