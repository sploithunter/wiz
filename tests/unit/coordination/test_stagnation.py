"""Tests for stagnation detection."""

from wiz.coordination.stagnation import StagnationDetector


class TestStagnationDetector:
    def test_counter_increment(self):
        det = StagnationDetector(limit=3)
        assert det.check(files_changed=False) is False
        assert det.count == 1

    def test_reset_on_change(self):
        det = StagnationDetector(limit=3)
        det.check(files_changed=False)
        det.check(files_changed=False)
        assert det.count == 2
        det.check(files_changed=True)
        assert det.count == 0

    def test_trigger_at_limit(self):
        det = StagnationDetector(limit=3)
        det.check(files_changed=False)
        det.check(files_changed=False)
        assert det.check(files_changed=False) is True
        assert det.is_stagnant is True

    def test_no_trigger_before_limit(self):
        det = StagnationDetector(limit=3)
        det.check(files_changed=False)
        det.check(files_changed=False)
        assert det.is_stagnant is False

    def test_manual_reset(self):
        det = StagnationDetector(limit=2)
        det.check(files_changed=False)
        det.check(files_changed=False)
        det.reset()
        assert det.count == 0
        assert det.is_stagnant is False

    def test_changes_prevent_stagnation(self):
        det = StagnationDetector(limit=3)
        for _ in range(10):
            assert det.check(files_changed=True) is False
        assert det.count == 0
