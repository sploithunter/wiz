"""launchd integration for scheduled execution."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from wiz.config.schema import ScheduleEntry

logger = logging.getLogger(__name__)

DAY_MAP = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3,
    "thu": 4, "fri": 5, "sat": 6,
}

PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{script}</string>
        <string>{cycle_type}</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
{intervals}
    </array>
    <key>StandardOutPath</key>
    <string>{log_dir}/{label}.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/{label}.stderr.log</string>
    <key>WorkingDirectory</key>
    <string>{working_dir}</string>
</dict>
</plist>
"""

INTERVAL_TEMPLATE = """\
        <dict>
            <key>Weekday</key>
            <integer>{weekday}</integer>
            <key>Hour</key>
            <integer>{hour}</integer>
            <key>Minute</key>
            <integer>{minute}</integer>
        </dict>"""


class LaunchdScheduler:
    """Generate and manage launchd plists from config."""

    def __init__(
        self,
        wiz_dir: Path,
        plist_dir: Path | None = None,
        log_dir: Path | None = None,
    ) -> None:
        self.wiz_dir = Path(wiz_dir)
        self.plist_dir = plist_dir or self.wiz_dir / "launchd"
        self.log_dir = log_dir or self.wiz_dir / "logs"
        self.script = self.wiz_dir / "scripts" / "wake.sh"

    def generate_plist(
        self, label: str, cycle_type: str, schedule: ScheduleEntry
    ) -> str:
        """Generate plist XML content."""
        intervals = []
        for time_str in schedule.times:
            hour, minute = self._parse_time(time_str)
            for day in schedule.days:
                weekday = DAY_MAP.get(day.lower())
                if weekday is not None:
                    intervals.append(
                        INTERVAL_TEMPLATE.format(
                            weekday=weekday, hour=hour, minute=minute
                        )
                    )

        return PLIST_TEMPLATE.format(
            label=label,
            script=self.script,
            cycle_type=cycle_type,
            intervals="\n".join(intervals),
            log_dir=self.log_dir,
            working_dir=self.wiz_dir,
        )

    def _parse_time(self, time_str: str) -> tuple[int, int]:
        parts = time_str.split(":")
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0

    def install(self, label: str, plist_content: str) -> bool:
        """Write plist and load via launchctl."""
        self.plist_dir.mkdir(parents=True, exist_ok=True)
        plist_path = self.plist_dir / f"{label}.plist"
        plist_path.write_text(plist_content)

        try:
            subprocess.run(
                ["launchctl", "load", str(plist_path)],
                check=True,
                capture_output=True,
                timeout=10,
            )
            logger.info("Installed schedule: %s", label)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.error("Failed to install %s: %s", label, e)
            return False

    def uninstall(self, label: str) -> bool:
        """Unload and remove plist."""
        plist_path = self.plist_dir / f"{label}.plist"
        if not plist_path.exists():
            return True

        try:
            subprocess.run(
                ["launchctl", "unload", str(plist_path)],
                check=False,
                capture_output=True,
                timeout=10,
            )
            plist_path.unlink()
            logger.info("Uninstalled schedule: %s", label)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.error("Failed to uninstall %s: %s", label, e)
            return False

    def status(self) -> list[dict[str, str]]:
        """List installed wiz schedules."""
        results = []
        if not self.plist_dir.exists():
            return results
        for plist in self.plist_dir.glob("com.wiz.*.plist"):
            label = plist.stem
            results.append({"label": label, "path": str(plist)})
        return results
