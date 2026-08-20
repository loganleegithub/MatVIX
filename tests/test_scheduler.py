from __future__ import annotations

import plistlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from matvix.daily_update import DailyUpdateResult, DailyUpdateStatus, read_update_status
from matvix.scheduler import (
    LaunchdPlistSpec,
    PollPolicy,
    recommended_launch_agent_path,
    render_launchd_plist,
    run_bounded_polling,
    target_session_for_now,
    write_launchd_plist,
)

NY = ZoneInfo("America/New_York")


class AdvancingClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


def _result(status: DailyUpdateStatus, now: datetime, target: pd.Timestamp) -> DailyUpdateResult:
    return DailyUpdateResult(
        status=status,
        updated_at=now.astimezone(UTC).isoformat(),
        target_session=target.date().isoformat(),
        latest_complete_session=(
            target.date().isoformat() if status != DailyUpdateStatus.SOURCES_PENDING else None
        ),
        last_good_session=None,
        sources={"VX_SETTLE": {"status": "FRESH"}},
        message=status.value,
    )


def test_target_session_uses_new_york_calendar_across_dst_and_weekend() -> None:
    spring_monday = datetime(2026, 3, 9, 13, 20, tzinfo=UTC)
    winter_monday = datetime(2026, 11, 9, 14, 20, tzinfo=UTC)

    assert target_session_for_now(spring_monday).date().isoformat() == "2026-03-06"
    assert target_session_for_now(winter_monday).date().isoformat() == "2026-11-06"


def test_bounded_polling_retries_pending_sources_then_stops_on_publication(
    tmp_path: Path,
) -> None:
    clock = AdvancingClock(datetime(2026, 3, 9, 9, 20, tzinfo=NY))
    calls = 0

    def attempt(target: pd.Timestamp, now: datetime) -> DailyUpdateResult:
        nonlocal calls
        calls += 1
        status = DailyUpdateStatus.SOURCES_PENDING if calls == 1 else DailyUpdateStatus.PUBLISHED
        return _result(status, now, target)

    result = run_bounded_polling(
        tmp_path,
        attempt,
        policy=PollPolicy(interval=timedelta(minutes=5), max_wait=timedelta(hours=2)),
        now_fn=clock,
        sleep_fn=clock.sleep,
    )

    assert result.status == DailyUpdateStatus.PUBLISHED
    assert calls == 2
    assert clock.current == datetime(2026, 3, 9, 9, 25, tzinfo=NY)
    status = read_update_status(tmp_path)
    assert status is not None and status["status"] == "PUBLISHED"


def test_bounded_polling_exhausts_without_overwriting_last_good(tmp_path: Path) -> None:
    clock = AdvancingClock(datetime(2026, 3, 9, 9, 20, tzinfo=NY))
    calls = 0

    def pending(target: pd.Timestamp, now: datetime) -> DailyUpdateResult:
        nonlocal calls
        calls += 1
        return _result(DailyUpdateStatus.SOURCES_PENDING, now, target)

    result = run_bounded_polling(
        tmp_path,
        pending,
        policy=PollPolicy(interval=timedelta(minutes=5), max_wait=timedelta(minutes=10)),
        now_fn=clock,
        sleep_fn=clock.sleep,
    )

    assert result.status == DailyUpdateStatus.WINDOW_EXHAUSTED
    assert calls == 2
    status = read_update_status(tmp_path)
    assert status is not None and status["status"] == "WINDOW_EXHAUSTED"


def test_polling_before_prefetch_window_performs_no_source_attempt(tmp_path: Path) -> None:
    clock = AdvancingClock(datetime(2026, 3, 9, 2, 0, tzinfo=NY))

    def forbidden(_: pd.Timestamp, __: datetime) -> DailyUpdateResult:
        raise AssertionError("source attempt must be bounded to the prefetch/poll window")

    result = run_bounded_polling(tmp_path, forbidden, now_fn=clock, sleep_fn=clock.sleep)

    assert result.status == DailyUpdateStatus.NOT_DUE
    assert (
        result.next_check_at == datetime(2026, 3, 9, 8, 50, tzinfo=NY).astimezone(UTC).isoformat()
    )


def test_launchd_plist_is_installable_and_delegates_timezone_gate_to_python(
    tmp_path: Path,
) -> None:
    project = tmp_path.resolve()
    spec = LaunchdPlistSpec(
        label="com.matvix.daily-update",
        program_arguments=(
            str(project / ".venv/bin/python"),
            "-m",
            "matvix",
            "daily-update",
            "--project-dir",
            str(project),
        ),
        working_directory=project,
        standard_out_path=project / "outputs/runtime/launchd.stdout.log",
        standard_error_path=project / "outputs/runtime/launchd.stderr.log",
    )

    content = render_launchd_plist(spec)
    parsed = plistlib.loads(content.encode("utf-8"))

    assert parsed["Label"] == spec.label
    assert parsed["ProgramArguments"] == list(spec.program_arguments)
    assert parsed["StartInterval"] == 900
    assert parsed["RunAtLoad"] is False and parsed["KeepAlive"] is False
    assert "StartCalendarInterval" not in parsed
    assert parsed["EnvironmentVariables"]["MATVIX_PROJECT_DIR"] == str(project)

    target = write_launchd_plist(spec, project / "agent.plist")
    assert plistlib.loads(target.read_bytes()) == parsed
    assert target.stat().st_mode & 0o777 == 0o644
    assert recommended_launch_agent_path(spec.label, home=project) == (
        project / "Library/LaunchAgents/com.matvix.daily-update.plist"
    )
