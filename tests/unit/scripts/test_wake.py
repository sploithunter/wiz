"""Tests for scripts/wake.sh."""

import subprocess
import textwrap
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
WAKE_SCRIPT = SCRIPTS_DIR / "wake.sh"


def _extract_wiz_run_block() -> str:
    """Extract the ``wiz run`` pipeline block from wake.sh for verification."""
    lines = WAKE_SCRIPT.read_text().splitlines()
    # Find the wiz run line and its surrounding set +e / set -e
    for i, line in enumerate(lines):
        if "wiz run" in line and "tee" in line:
            return "\n".join(lines[max(0, i - 1) : i + 3])
    raise AssertionError("Could not find 'wiz run ... | tee' block in wake.sh")


class TestWakeScriptCleanup:
    """Regression tests for issue #74: wake.sh must run cleanup even when wiz fails."""

    def test_wiz_run_block_has_set_plus_e_guard(self):
        """The ``wiz run | tee`` pipeline must be wrapped in ``set +e`` / ``set -e``.

        Without this guard, ``set -euo pipefail`` causes the script to exit
        immediately when wiz returns non-zero, skipping PIPESTATUS capture,
        completion logging, and bridge cleanup.
        """
        block = _extract_wiz_run_block()
        assert "set +e" in block, (
            f"wake.sh is missing 'set +e' before the wiz run pipeline.\n"
            f"Extracted block:\n{block}"
        )
        assert "set -e" in block, (
            f"wake.sh is missing 'set -e' after PIPESTATUS capture.\n"
            f"Extracted block:\n{block}"
        )

    def test_pipefail_does_not_abort_before_cleanup(self, tmp_path: Path):
        """Simulate the exact wake.sh pattern: a failing command piped through
        tee under ``set -euo pipefail`` must not abort before capturing the
        exit code and running cleanup.

        This script mirrors the critical section of wake.sh. Before the fix,
        the script would exit at the pipeline line and never reach the cleanup
        marker.
        """
        test_script = tmp_path / "test_pipefail.sh"
        marker_file = tmp_path / "cleanup_ran"
        test_script.write_text(
            textwrap.dedent(f"""\
                #!/bin/bash
                set -euo pipefail
                LOG_FILE="{tmp_path}/test.log"
                touch "$LOG_FILE"

                set +e
                false 2>&1 | tee -a "$LOG_FILE"
                EXIT_CODE=${{PIPESTATUS[0]}}
                set -e

                echo "Cycle complete (exit code: $EXIT_CODE)"
                touch "{marker_file}"
                exit $EXIT_CODE
            """)
        )
        test_script.chmod(0o755)

        result = subprocess.run(
            ["bash", str(test_script)],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert marker_file.exists(), (
            "Cleanup did not run — script exited before reaching cleanup.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert result.returncode == 1
        assert "Cycle complete (exit code: 1)" in result.stdout

    def test_pipefail_without_guard_aborts_early(self, tmp_path: Path):
        """Demonstrate the bug: WITHOUT ``set +e``, a failing pipeline under
        ``set -euo pipefail`` aborts the script before cleanup runs.

        This proves the regression test above would fail without the fix.
        """
        test_script = tmp_path / "test_no_guard.sh"
        marker_file = tmp_path / "cleanup_ran"
        test_script.write_text(
            textwrap.dedent(f"""\
                #!/bin/bash
                set -euo pipefail
                LOG_FILE="{tmp_path}/test.log"
                touch "$LOG_FILE"

                # BUG: no set +e guard — script will exit here on failure
                false 2>&1 | tee -a "$LOG_FILE"
                EXIT_CODE=${{PIPESTATUS[0]}}

                echo "Cycle complete (exit code: $EXIT_CODE)"
                touch "{marker_file}"
                exit $EXIT_CODE
            """)
        )
        test_script.chmod(0o755)

        result = subprocess.run(
            ["bash", str(test_script)],
            capture_output=True,
            text=True,
            timeout=10,
        )

        # Without the guard, cleanup never runs
        assert not marker_file.exists(), (
            "Cleanup ran unexpectedly — the unguarded pipeline should abort."
        )
        assert result.returncode != 0

    def test_exit_code_preserved_through_guard(self, tmp_path: Path):
        """The ``set +e`` guard must preserve the original wiz exit code."""
        for code in (0, 1, 2, 42, 127):
            test_script = tmp_path / f"test_exit_{code}.sh"
            test_script.write_text(
                textwrap.dedent(f"""\
                    #!/bin/bash
                    set -euo pipefail
                    LOG_FILE="{tmp_path}/test_{code}.log"
                    touch "$LOG_FILE"

                    set +e
                    bash -c 'exit {code}' 2>&1 | tee -a "$LOG_FILE"
                    EXIT_CODE=${{PIPESTATUS[0]}}
                    set -e

                    exit $EXIT_CODE
                """)
            )
            test_script.chmod(0o755)

            result = subprocess.run(
                ["bash", str(test_script)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert result.returncode == code, (
                f"Expected exit code {code}, got {result.returncode}"
            )
