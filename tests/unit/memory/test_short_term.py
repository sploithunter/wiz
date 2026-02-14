"""Tests for short-term memory."""

from pathlib import Path

from wiz.memory.short_term import ShortTermMemory


class TestShortTermMemory:
    def test_load_save_roundtrip(self, tmp_path: Path):
        path = tmp_path / "short-term.md"
        mem = ShortTermMemory(path, max_lines=50)
        mem.append("Line 1")
        mem.append("Line 2")
        mem.save()

        mem2 = ShortTermMemory(path, max_lines=50)
        lines = mem2.load()
        assert lines == ["Line 1", "Line 2"]

    def test_line_limit_truncation(self, tmp_path: Path):
        path = tmp_path / "short-term.md"
        mem = ShortTermMemory(path, max_lines=5)
        for i in range(10):
            mem.append(f"Line {i}")
        assert len(mem.lines) == 5
        # Should keep the most recent lines
        assert mem.lines[0] == "Line 5"
        assert mem.lines[-1] == "Line 9"

    def test_append_with_eviction(self, tmp_path: Path):
        path = tmp_path / "short-term.md"
        mem = ShortTermMemory(path, max_lines=3)
        mem.append("old1")
        mem.append("old2")
        mem.append("old3")
        mem.append("new1")
        assert len(mem.lines) == 3
        assert "old1" not in mem.lines
        assert "new1" in mem.lines

    def test_multiline_append(self, tmp_path: Path):
        path = tmp_path / "short-term.md"
        mem = ShortTermMemory(path, max_lines=50)
        mem.append("Line A\nLine B\nLine C")
        assert len(mem.lines) == 3

    def test_load_nonexistent(self, tmp_path: Path):
        path = tmp_path / "nonexistent.md"
        mem = ShortTermMemory(path)
        lines = mem.load()
        assert lines == []

    def test_content_property(self, tmp_path: Path):
        path = tmp_path / "short-term.md"
        mem = ShortTermMemory(path)
        mem.append("Hello")
        mem.append("World")
        assert mem.content == "Hello\nWorld"
