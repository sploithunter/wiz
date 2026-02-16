"""Tests for rejection journal."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from wiz.memory.rejection_journal import RejectionJournal


class TestRejectionJournal:
    def test_record_creates_file(self, tmp_path: Path):
        journal = RejectionJournal(tmp_path / "rejections")
        journal.record("wiz", 42, "fix/42", "Missing tests", "bug-fixer")

        path = tmp_path / "rejections" / "wiz.jsonl"
        assert path.exists()
        entry = json.loads(path.read_text().strip())
        assert entry["repo"] == "wiz"
        assert entry["issue"] == 42
        assert entry["branch"] == "fix/42"
        assert entry["feedback"] == "Missing tests"
        assert entry["agent"] == "bug-fixer"
        assert "timestamp" in entry

    def test_record_appends(self, tmp_path: Path):
        journal = RejectionJournal(tmp_path / "rejections")
        journal.record("wiz", 1, "fix/1", "feedback 1")
        journal.record("wiz", 2, "fix/2", "feedback 2")

        path = tmp_path / "rejections" / "wiz.jsonl"
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 2

    def test_read_all(self, tmp_path: Path):
        journal = RejectionJournal(tmp_path / "rejections")
        journal.record("wiz", 1, "fix/1", "fb1")
        journal.record("wiz", 2, "fix/2", "fb2")

        entries = journal.read()
        assert len(entries) == 2

    def test_read_filtered_by_repo(self, tmp_path: Path):
        journal = RejectionJournal(tmp_path / "rejections")
        journal.record("wiz", 1, "fix/1", "fb1")
        journal.record("other", 2, "fix/2", "fb2")

        entries = journal.read(repo="wiz")
        assert len(entries) == 1
        assert entries[0]["repo"] == "wiz"

    def test_read_filtered_by_since(self, tmp_path: Path):
        journal = RejectionJournal(tmp_path / "rejections")
        # Write entries manually with controlled timestamps
        old_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        recent_time = datetime.now(timezone.utc).isoformat()

        path = tmp_path / "rejections"
        path.mkdir(parents=True)
        with open(path / "wiz.jsonl", "w") as f:
            f.write(json.dumps({"timestamp": old_time, "repo": "wiz", "issue": 1, "branch": "fix/1", "feedback": "old", "agent": "bug-fixer"}) + "\n")
            f.write(json.dumps({"timestamp": recent_time, "repo": "wiz", "issue": 2, "branch": "fix/2", "feedback": "recent", "agent": "bug-fixer"}) + "\n")

        since = datetime.now(timezone.utc) - timedelta(days=5)
        entries = journal.read(since=since)
        assert len(entries) == 1
        assert entries[0]["issue"] == 2

    def test_read_with_limit(self, tmp_path: Path):
        journal = RejectionJournal(tmp_path / "rejections")
        for i in range(10):
            journal.record("wiz", i, f"fix/{i}", f"feedback {i}")

        entries = journal.read(limit=3)
        assert len(entries) == 3

    def test_read_empty_journal(self, tmp_path: Path):
        journal = RejectionJournal(tmp_path / "rejections")
        entries = journal.read()
        assert entries == []

    def test_read_multiple_repos(self, tmp_path: Path):
        journal = RejectionJournal(tmp_path / "rejections")
        journal.record("wiz", 1, "fix/1", "fb1")
        journal.record("CIN", 2, "fix/2", "fb2")
        journal.record("wiz", 3, "fix/3", "fb3")

        # Read all repos
        entries = journal.read()
        assert len(entries) == 3

        # Read specific repo
        wiz_entries = journal.read(repo="wiz")
        assert len(wiz_entries) == 2

    def test_summary_empty(self, tmp_path: Path):
        journal = RejectionJournal(tmp_path / "rejections")
        assert journal.summary() == "No rejections recorded."

    def test_summary_with_entries(self, tmp_path: Path):
        journal = RejectionJournal(tmp_path / "rejections")
        journal.record("wiz", 42, "fix/42", "Missing edge case tests")
        journal.record("wiz", 55, "fix/55", "No error handling for null input")

        summary = journal.summary()
        assert "2 entries" in summary
        assert "wiz#42" in summary
        assert "wiz#55" in summary
        assert "Missing edge case tests" in summary

    def test_summary_truncates_long_feedback(self, tmp_path: Path):
        journal = RejectionJournal(tmp_path / "rejections")
        long_feedback = "x" * 300
        journal.record("wiz", 1, "fix/1", long_feedback)

        summary = journal.summary()
        # Should truncate to 200 + "..."
        assert "..." in summary

    def test_default_dir(self):
        journal = RejectionJournal()
        assert journal.base_dir == Path("memory/rejections")

    def test_read_sorted_most_recent_first(self, tmp_path: Path):
        journal = RejectionJournal(tmp_path / "rejections")
        # Record entries in order - they'll have increasing timestamps
        journal.record("wiz", 1, "fix/1", "first")
        journal.record("wiz", 2, "fix/2", "second")
        journal.record("wiz", 3, "fix/3", "third")

        entries = journal.read()
        # Most recent should be first
        assert entries[0]["issue"] == 3
        assert entries[-1]["issue"] == 1
