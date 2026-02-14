"""Tests for loop tracker."""

from pathlib import Path

from wiz.coordination.loop_tracker import LoopTracker
from wiz.coordination.strikes import StrikeTracker


class TestLoopTracker:
    def test_cycle_counting(self, tmp_path: Path):
        strikes = StrikeTracker(tmp_path / "strikes.json")
        tracker = LoopTracker(strikes, max_cycles=3)
        assert tracker.record_cycle(1, "rejected") == 1
        assert tracker.record_cycle(1, "rejected again") == 2
        assert tracker.get_cycle_count(1) == 2

    def test_max_reached_detection(self, tmp_path: Path):
        strikes = StrikeTracker(tmp_path / "strikes.json")
        tracker = LoopTracker(strikes, max_cycles=2)
        tracker.record_cycle(1, "a")
        assert tracker.is_max_reached(1) is False
        tracker.record_cycle(1, "b")
        assert tracker.is_max_reached(1) is True

    def test_different_issues_independent(self, tmp_path: Path):
        strikes = StrikeTracker(tmp_path / "strikes.json")
        tracker = LoopTracker(strikes, max_cycles=2)
        tracker.record_cycle(1, "a")
        tracker.record_cycle(1, "b")
        assert tracker.is_max_reached(1) is True
        assert tracker.is_max_reached(2) is False
