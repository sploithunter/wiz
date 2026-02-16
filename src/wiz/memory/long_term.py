"""Long-term memory: keyword-indexed topic files."""

from __future__ import annotations

import re
from pathlib import Path


class LongTermMemory:
    """Manages long-term memory via an index.md keyword->file map and topic files."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir).expanduser()
        self.index_path = self.base_dir / "index.md"
        self.topics_dir = self.base_dir / "topics"
        self._index: dict[str, str] = {}

    def load_index(self) -> dict[str, str]:
        """Parse index.md into keyword->filename map.

        Expected format per line: `keyword: filename.md`
        """
        self._index = {}
        if not self.index_path.exists():
            return {}

        for line in self.index_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r"^(.+?):\s*(.+)$", line)
            if match:
                keyword = match.group(1).strip().lower()
                filename = match.group(2).strip()
                self._index[keyword] = filename

        return dict(self._index)

    def save_index(self) -> None:
        """Write index back to index.md."""
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Long-Term Memory Index", ""]
        for keyword, filename in sorted(self._index.items()):
            lines.append(f"{keyword}: {filename}")
        self.index_path.write_text("\n".join(lines) + "\n")

    def retrieve(self, keywords: list[str]) -> list[tuple[str, str]]:
        """Find topics matching any of the given keywords (exact or partial).

        Returns list of (keyword, content) tuples.
        """
        results = []
        for query in keywords:
            query_lower = query.lower()
            for index_keyword, filename in self._index.items():
                if query_lower in index_keyword or index_keyword in query_lower:
                    topic_path = self.topics_dir / filename
                    if topic_path.exists():
                        content = topic_path.read_text()
                        results.append((index_keyword, content))
        return results

    def update_topic(self, keyword: str, filename: str, content: str) -> None:
        """Create or update a topic file and add to index."""
        self.topics_dir.mkdir(parents=True, exist_ok=True)
        topic_path = self.topics_dir / filename
        topic_path.write_text(content)
        self._index[keyword.lower()] = filename

    def delete_topic(self, keyword: str) -> bool:
        """Remove a topic from index, delete its file, and persist the index."""
        keyword_lower = keyword.lower()
        if keyword_lower not in self._index:
            return False
        filename = self._index.pop(keyword_lower)
        topic_path = self.topics_dir / filename
        if topic_path.exists():
            topic_path.unlink()
        self.save_index()
        return True
