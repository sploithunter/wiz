"""Tests for strike tracker."""

from pathlib import Path

from wiz.coordination.strikes import StrikeTracker


class TestStrikeTracker:
    def test_json_persistence(self, tmp_path: Path):
        sf = tmp_path / ".wiz" / "strikes.json"
        tracker = StrikeTracker(sf)
        tracker.record_issue_strike(1, "bad fix")
        tracker.record_issue_strike(1, "still bad")

        # Reload from disk
        tracker2 = StrikeTracker(sf)
        assert tracker2.get_issue_strikes(1) == 2

    def test_per_issue_counting(self, tmp_path: Path):
        tracker = StrikeTracker(tmp_path / "strikes.json")
        assert tracker.record_issue_strike(1, "reason") == 1
        assert tracker.record_issue_strike(1, "reason2") == 2
        assert tracker.record_issue_strike(2, "reason") == 1
        assert tracker.get_issue_strikes(1) == 2
        assert tracker.get_issue_strikes(2) == 1

    def test_per_file_flagging(self, tmp_path: Path):
        tracker = StrikeTracker(tmp_path / "strikes.json")
        tracker.record_file_failure("src/main.py", 1)
        tracker.record_file_failure("src/main.py", 2)
        tracker.record_file_failure("src/main.py", 3)
        assert "src/main.py" in tracker.get_flagged_files(max_strikes=3)

    def test_threshold_detection(self, tmp_path: Path):
        tracker = StrikeTracker(tmp_path / "strikes.json")
        tracker.record_issue_strike(1, "a")
        tracker.record_issue_strike(1, "b")
        assert tracker.is_escalated(1, max_strikes=3) is False
        tracker.record_issue_strike(1, "c")
        assert tracker.is_escalated(1, max_strikes=3) is True

    def test_no_strikes(self, tmp_path: Path):
        tracker = StrikeTracker(tmp_path / "strikes.json")
        assert tracker.get_issue_strikes(999) == 0
        assert tracker.is_escalated(999) is False

    def test_flagged_files_empty(self, tmp_path: Path):
        tracker = StrikeTracker(tmp_path / "strikes.json")
        assert tracker.get_flagged_files() == []

    def test_file_failure_tracks_issues(self, tmp_path: Path):
        tracker = StrikeTracker(tmp_path / "strikes.json")
        tracker.record_file_failure("src/a.py", 1)
        tracker.record_file_failure("src/a.py", 1)  # Duplicate issue
        tracker.record_file_failure("src/a.py", 2)
        # Should have count=3 but only 2 unique issues
        data = tracker._data["files"]["src/a.py"]
        assert data["count"] == 3
        assert len(data["issues"]) == 2
