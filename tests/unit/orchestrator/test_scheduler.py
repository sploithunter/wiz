"""Tests for launchd scheduler."""

from pathlib import Path

import pytest

from wiz.config.schema import ScheduleEntry
from wiz.orchestrator.scheduler import LaunchdScheduler


class TestLaunchdScheduler:
    def test_plist_xml_valid(self, tmp_path: Path):
        scheduler = LaunchdScheduler(tmp_path)
        entry = ScheduleEntry(
            enabled=True,
            times=["07:00"],
            days=["mon", "wed", "fri"],
        )
        plist = scheduler.generate_plist("com.wiz.dev-cycle", "dev-cycle", entry)
        assert "<?xml" in plist
        assert "com.wiz.dev-cycle" in plist
        assert "dev-cycle" in plist
        assert "<integer>7</integer>" in plist  # Hour
        assert "<integer>0</integer>" in plist  # Minute

    def test_time_parsing(self, tmp_path: Path):
        scheduler = LaunchdScheduler(tmp_path)
        assert scheduler._parse_time("07:00") == (7, 0)
        assert scheduler._parse_time("14:30") == (14, 30)
        assert scheduler._parse_time("9") == (9, 0)

    def test_day_filtering(self, tmp_path: Path):
        scheduler = LaunchdScheduler(tmp_path)
        entry = ScheduleEntry(
            enabled=True,
            times=["09:00"],
            days=["mon"],
        )
        plist = scheduler.generate_plist("test", "dev-cycle", entry)
        # Monday = 1
        assert "<integer>1</integer>" in plist
        # Should NOT have other days
        count = plist.count("<key>Weekday</key>")
        assert count == 1

    def test_multiple_times_and_days(self, tmp_path: Path):
        scheduler = LaunchdScheduler(tmp_path)
        entry = ScheduleEntry(
            enabled=True,
            times=["07:00", "19:00"],
            days=["mon", "fri"],
        )
        plist = scheduler.generate_plist("test", "dev-cycle", entry)
        # 2 times * 2 days = 4 intervals
        count = plist.count("<key>Weekday</key>")
        assert count == 4

    def test_status_empty(self, tmp_path: Path):
        scheduler = LaunchdScheduler(tmp_path)
        assert scheduler.status() == []

    def test_invalid_time_format_raises(self, tmp_path: Path):
        scheduler = LaunchdScheduler(tmp_path)
        entry = ScheduleEntry(times=["not-a-time"], days=["mon"])
        with pytest.raises(ValueError, match="hour is not a number"):
            scheduler.generate_plist("test", "dev-cycle", entry)

    def test_invalid_time_hour_out_of_range(self, tmp_path: Path):
        scheduler = LaunchdScheduler(tmp_path)
        entry = ScheduleEntry(times=["25:00"], days=["mon"])
        with pytest.raises(ValueError, match="hour must be 0-23"):
            scheduler.generate_plist("test", "dev-cycle", entry)

    def test_invalid_time_minute_out_of_range(self, tmp_path: Path):
        scheduler = LaunchdScheduler(tmp_path)
        entry = ScheduleEntry(times=["09:60"], days=["mon"])
        with pytest.raises(ValueError, match="minute must be 0-59"):
            scheduler.generate_plist("test", "dev-cycle", entry)

    def test_invalid_time_too_many_colons(self, tmp_path: Path):
        scheduler = LaunchdScheduler(tmp_path)
        entry = ScheduleEntry(times=["09:00:00"], days=["mon"])
        with pytest.raises(ValueError, match="expected 'HH:MM' or 'H'"):
            scheduler.generate_plist("test", "dev-cycle", entry)

    def test_invalid_day_name_raises(self, tmp_path: Path):
        scheduler = LaunchdScheduler(tmp_path)
        entry = ScheduleEntry(times=["09:00"], days=["Monday"])
        with pytest.raises(ValueError, match="Invalid day name 'Monday'"):
            scheduler.generate_plist("test", "dev-cycle", entry)

    def test_invalid_day_among_valid_days_raises(self, tmp_path: Path):
        scheduler = LaunchdScheduler(tmp_path)
        entry = ScheduleEntry(times=["09:00"], days=["mon", "funday"])
        with pytest.raises(ValueError, match="Invalid day name 'funday'"):
            scheduler.generate_plist("test", "dev-cycle", entry)

    def test_status_with_plists(self, tmp_path: Path):
        plist_dir = tmp_path / "launchd"
        plist_dir.mkdir()
        (plist_dir / "com.wiz.dev-cycle.plist").write_text("<plist/>")
        (plist_dir / "com.wiz.content-cycle.plist").write_text("<plist/>")

        scheduler = LaunchdScheduler(tmp_path, plist_dir=plist_dir)
        result = scheduler.status()
        assert len(result) == 2
        labels = {s["label"] for s in result}
        assert "com.wiz.dev-cycle" in labels
