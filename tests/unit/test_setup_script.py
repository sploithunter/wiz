"""Tests for scripts/setup.sh correctness."""

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_SCRIPT = REPO_ROOT / "scripts" / "setup.sh"


class TestSetupScript:
    def test_no_reference_to_missing_yaml_example(self):
        """Regression test for #104: setup.sh referenced config/wiz.yaml.example which doesn't exist."""
        content = SETUP_SCRIPT.read_text()
        assert "wiz.yaml.example" not in content, (
            "setup.sh still references config/wiz.yaml.example, which does not exist in the repo"
        )

    def test_config_files_referenced_exist(self):
        """Verify that config file paths referenced in setup.sh actually exist in the repo."""
        content = SETUP_SCRIPT.read_text()
        # Find references to files under config/ (e.g. config/wiz.yaml, config/wiz.yaml.example)
        config_refs = re.findall(r"config/([a-zA-Z0-9_./-]+\.(?:yaml|yml|json|toml)(?:\.[a-zA-Z]+)?)", content)
        config_dir = REPO_ROOT / "config"
        for ref in config_refs:
            ref_path = config_dir / ref
            # Only assert existence for literal file references (not variable-expanded ones)
            assert ref_path.exists(), (
                f"setup.sh references config/{ref} but the file does not exist"
            )
