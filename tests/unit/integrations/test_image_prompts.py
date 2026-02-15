"""Tests for image prompt saving."""

from pathlib import Path

from wiz.integrations.image_prompts import (
    _slugify,
    extract_image_prompts,
    save_all_image_prompts,
    save_image_prompt,
)


class TestSlugify:
    def test_basic(self):
        assert _slugify("Hello World") == "hello-world"

    def test_special_chars(self):
        assert _slugify("Self-Optimizing Agents!") == "self-optimizing-agents"

    def test_truncates_long(self):
        slug = _slugify("a" * 100)
        assert len(slug) <= 60

    def test_collapses_whitespace(self):
        assert _slugify("too   many   spaces") == "too-many-spaces"


class TestExtractImagePrompts:
    def test_extracts_from_drafts(self):
        drafts = [
            {
                "draft_title": "Test Post",
                "posts": [{"text": "hello"}],
                "image_prompt": "A futuristic robot writing code",
            },
        ]
        result = extract_image_prompts(drafts)
        assert len(result) == 1
        assert result[0]["title"] == "Test Post"
        assert "robot" in result[0]["prompt"]

    def test_skips_empty_prompts(self):
        drafts = [
            {"draft_title": "No Image", "posts": [{"text": "hi"}]},
            {"draft_title": "Has Image", "image_prompt": "A cat"},
        ]
        result = extract_image_prompts(drafts)
        assert len(result) == 1
        assert result[0]["title"] == "Has Image"

    def test_skips_whitespace_only(self):
        drafts = [{"draft_title": "Blank", "image_prompt": "   "}]
        result = extract_image_prompts(drafts)
        assert len(result) == 0

    def test_uses_untitled_fallback(self):
        drafts = [{"image_prompt": "A landscape"}]
        result = extract_image_prompts(drafts)
        assert result[0]["title"] == "untitled"


class TestSaveImagePrompt:
    def test_saves_file(self, tmp_path):
        path = save_image_prompt(
            title="Test Draft",
            prompt_text="A glowing network diagram",
            source="social",
            output_dir=str(tmp_path),
        )
        assert path is not None
        assert path.exists()
        content = path.read_text()
        assert "Test Draft" in content
        assert "glowing network" in content
        assert "social" in content

    def test_creates_directory(self, tmp_path):
        nested = tmp_path / "deep" / "nested"
        path = save_image_prompt(
            title="Test",
            prompt_text="prompt",
            output_dir=str(nested),
        )
        assert path is not None
        assert nested.exists()

    def test_filename_format(self, tmp_path):
        path = save_image_prompt(
            title="My Great Post",
            prompt_text="prompt",
            output_dir=str(tmp_path),
        )
        assert path is not None
        assert "my-great-post" in path.name
        assert path.suffix == ".md"


class TestSaveAllImagePrompts:
    def test_saves_multiple(self, tmp_path):
        drafts = [
            {"draft_title": "Post A", "image_prompt": "Prompt A"},
            {"draft_title": "Post B", "image_prompt": "Prompt B"},
            {"draft_title": "No Prompt", "posts": [{"text": "hi"}]},
        ]
        paths = save_all_image_prompts(drafts, source="social", output_dir=str(tmp_path))
        assert len(paths) == 2
        files = list(tmp_path.glob("*.md"))
        assert len(files) == 2

    def test_empty_drafts(self, tmp_path):
        paths = save_all_image_prompts([], output_dir=str(tmp_path))
        assert paths == []
