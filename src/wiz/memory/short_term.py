"""Short-term memory: load/save markdown with line limit and eviction."""

from __future__ import annotations

from pathlib import Path


class ShortTermMemory:
    """Manages short-term memory as a line-limited markdown file."""

    def __init__(self, path: Path, max_lines: int = 50) -> None:
        self.path = Path(path)
        self.max_lines = max_lines
        self._lines: list[str] = []

    def load(self) -> list[str]:
        """Load memory from file. Returns lines."""
        if self.path.exists():
            self._lines = self.path.read_text().splitlines()
        else:
            self._lines = []
        return list(self._lines)

    def save(self) -> None:
        """Save current memory to file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(self._lines) + "\n" if self._lines else "")

    def append(self, text: str) -> None:
        """Append text, evicting oldest lines if over limit."""
        new_lines = text.splitlines()
        self._lines.extend(new_lines)
        # Evict oldest lines if over limit
        if len(self._lines) > self.max_lines:
            self._lines = self._lines[-self.max_lines :]

    @property
    def lines(self) -> list[str]:
        return list(self._lines)

    @property
    def content(self) -> str:
        return "\n".join(self._lines)
