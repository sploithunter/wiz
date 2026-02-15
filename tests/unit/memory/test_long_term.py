"""Tests for long-term memory."""

from pathlib import Path

from wiz.memory.long_term import LongTermMemory


class TestLongTermMemory:
    def test_index_parsing(self, tmp_path: Path):
        base = tmp_path / "long-term"
        base.mkdir()
        index = base / "index.md"
        index.write_text(
            "# Index\n\narchitecture: arch.md\ntesting: test.md\n"
        )
        mem = LongTermMemory(base)
        result = mem.load_index()
        assert result == {"architecture": "arch.md", "testing": "test.md"}

    def test_keyword_matching_exact(self, tmp_path: Path):
        base = tmp_path / "long-term"
        topics = base / "topics"
        topics.mkdir(parents=True)
        (base / "index.md").write_text("bridge: bridge.md\n")
        (topics / "bridge.md").write_text("Bridge patterns info")

        mem = LongTermMemory(base)
        mem.load_index()
        results = mem.retrieve(["bridge"])
        assert len(results) == 1
        assert results[0][0] == "bridge"
        assert results[0][1] == "Bridge patterns info"

    def test_keyword_matching_partial(self, tmp_path: Path):
        base = tmp_path / "long-term"
        topics = base / "topics"
        topics.mkdir(parents=True)
        (base / "index.md").write_text("bridge-patterns: bridge.md\n")
        (topics / "bridge.md").write_text("content")

        mem = LongTermMemory(base)
        mem.load_index()
        # "bridge" is contained in "bridge-patterns"
        results = mem.retrieve(["bridge"])
        assert len(results) == 1

    def test_topic_crud(self, tmp_path: Path):
        base = tmp_path / "long-term"
        mem = LongTermMemory(base)
        mem.load_index()

        # Create
        mem.update_topic("newkey", "new.md", "New content")
        mem.save_index()
        assert (base / "topics" / "new.md").read_text() == "New content"

        # Read
        results = mem.retrieve(["newkey"])
        assert len(results) == 1
        assert results[0][1] == "New content"

        # Update
        mem.update_topic("newkey", "new.md", "Updated content")
        results = mem.retrieve(["newkey"])
        assert results[0][1] == "Updated content"

        # Delete
        assert mem.delete_topic("newkey") is True
        assert not (base / "topics" / "new.md").exists()
        assert mem.delete_topic("nonexistent") is False

    def test_empty_index(self, tmp_path: Path):
        base = tmp_path / "long-term"
        mem = LongTermMemory(base)
        result = mem.load_index()
        assert result == {}

    def test_tilde_path_is_expanded(self, tmp_path: Path):
        """Regression test for issue #45: tilde paths must be expanded."""
        mem = LongTermMemory(Path("~/.wiz-long-term-test"))

        # base_dir should be expanded — no literal '~' component
        assert "~" not in str(mem.base_dir)
        assert str(mem.base_dir) == str(
            Path.home() / ".wiz-long-term-test"
        )

    def test_skip_comments_and_blanks(self, tmp_path: Path):
        base = tmp_path / "long-term"
        base.mkdir()
        (base / "index.md").write_text(
            "# Header\n\n# Comment\nkey: file.md\n\n"
        )
        mem = LongTermMemory(base)
        result = mem.load_index()
        assert result == {"key": "file.md"}
