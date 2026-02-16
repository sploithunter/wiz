"""Tests for RejectionJournal with repo name sanitization."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from wiz.memory.rejection_journal import RejectionJournal


class TestRejectionJournalSanitize:
    """Test _sanitize_repo produces safe filenames."""

    @pytest.mark.parametrize(
        "repo, expected",
        [
            ("owner/repo", "owner_repo"),
            ("simple", "simple"),
            ("a/b/c", "a_b_c"),
            ("../etc/passwd", "etc_passwd"),
            ("owner\\repo", "owner_repo"),
            ("my--repo", "my--repo"),
            ("....", "unknown"),
            ("", "unknown"),
            ("/", "unknown"),
            ("owner/repo-name.v2", "owner_repo-name.v2"),
        ],
    )
    def test_sanitize_repo(self, repo: str, expected: str) -> None:
        assert RejectionJournal._sanitize_repo(repo) == expected


class TestRejectionJournalRecord:
    """Test record() writes entries without errors."""

    def test_record_with_slash_in_repo(self) -> None:
        """Regression test for issue #77: repo with '/' should not raise."""
        with TemporaryDirectory() as td:
            journal = RejectionJournal(Path(td))
            # This used to raise FileNotFoundError because 'owner/repo.jsonl'
            # tried to create a nested path.
            journal.record("owner/repo", 42, "fix/42", "bad review feedback")

            # Verify the file was created with sanitized name
            expected_path = Path(td) / "owner_repo.jsonl"
            assert expected_path.exists()

            entries = journal.read(repo="owner/repo")
            assert len(entries) == 1
            assert entries[0]["repo"] == "owner/repo"
            assert entries[0]["issue"] == 42
            assert entries[0]["branch"] == "fix/42"
            assert entries[0]["feedback"] == "bad review feedback"

    def test_record_with_path_traversal(self) -> None:
        """Repo names with '..' should not escape base_dir."""
        with TemporaryDirectory() as td:
            journal = RejectionJournal(Path(td))
            journal.record("../../etc/passwd", 1, "fix/1", "feedback")

            # File must be inside base_dir, not escaped
            created_files = list(Path(td).iterdir())
            assert len(created_files) == 1
            assert created_files[0].parent == Path(td)

    def test_record_simple_repo(self) -> None:
        """Simple repo names should work as before."""
        with TemporaryDirectory() as td:
            journal = RejectionJournal(Path(td))
            journal.record("myrepo", 10, "fix/10", "needs work")

            path = Path(td) / "myrepo.jsonl"
            assert path.exists()

            entries = journal.read(repo="myrepo")
            assert len(entries) == 1
            assert entries[0]["issue"] == 10

    def test_record_creates_base_dir(self) -> None:
        """record() should create base_dir if it doesn't exist."""
        with TemporaryDirectory() as td:
            nested = Path(td) / "sub" / "dir"
            journal = RejectionJournal(nested)
            journal.record("repo", 5, "fix/5", "feedback")

            assert nested.exists()
            assert (nested / "repo.jsonl").exists()

    def test_record_appends_multiple_entries(self) -> None:
        """Multiple records should append to the same file."""
        with TemporaryDirectory() as td:
            journal = RejectionJournal(Path(td))
            journal.record("owner/repo", 1, "fix/1", "first")
            journal.record("owner/repo", 2, "fix/2", "second")

            entries = journal.read(repo="owner/repo")
            assert len(entries) == 2


class TestRejectionJournalRead:
    """Test read() returns entries correctly."""

    def test_read_nonexistent_repo(self) -> None:
        """Reading a repo with no journal returns empty list."""
        with TemporaryDirectory() as td:
            journal = RejectionJournal(Path(td))
            assert journal.read(repo="nonexistent") == []

    def test_read_preserves_original_repo_name(self) -> None:
        """The stored entry should contain the original repo name."""
        with TemporaryDirectory() as td:
            journal = RejectionJournal(Path(td))
            journal.record("owner/repo", 42, "fix/42", "feedback")

            entries = journal.read(repo="owner/repo")
            assert entries[0]["repo"] == "owner/repo"

    def test_read_entry_has_timestamp(self) -> None:
        """Each entry should have a timestamp field."""
        with TemporaryDirectory() as td:
            journal = RejectionJournal(Path(td))
            journal.record("repo", 1, "fix/1", "feedback")

            entries = journal.read(repo="repo")
            assert "timestamp" in entries[0]

    def test_read_all_repos(self) -> None:
        """read() without repo returns entries from all repos."""
        with TemporaryDirectory() as td:
            journal = RejectionJournal(Path(td))
            journal.record("owner/repo-a", 1, "fix/1", "feedback-a")
            journal.record("owner/repo-b", 2, "fix/2", "feedback-b")

            entries = journal.read()
            assert len(entries) == 2
