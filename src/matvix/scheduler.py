from __future__ import annotations

import math
import os
import plistlib
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from matvix.calendar import NY, decision_as_of, previous_session
from matvix.daily_update import (
    DailyUpdateResult,
    DailyUpdateStatus,
    last_good_session,
    read_update_status,
    write_update_status,
)
from matvix.pipeline import ProjectPaths


@dataclass(frozen=True)
class PollPolicy:
    interval: timedelta = timedelta(minutes=5)
    max_wait: timedelta = timedelta(hours=3)
    prefetch_lead: timedelta = timedelta(minutes=30)

    def __post_init__(self) -> None:
        if self.interval.total_seconds() <= 0:
            raise ValueError("poll interval must be positive")
        if self.max_wait.total_seconds() <= 0:
            raise ValueError("poll max_wait must be positive")
        if self.prefetch_lead.total_seconds() < 0:
            raise ValueError("prefetch_lead cannot be negative")


@dataclass(frozen=True)
class LaunchdPlistSpec:
    label: str
    program_arguments: tuple[str, ...]
    working_directory: Path
    standard_out_path: Path
    standard_error_path: Path
    start_interval_seconds: int = 15 * 60

    def __post_init__(self) -> None:
        if not self.label or any(character.isspace() for character in self.label):
            raise ValueError("launchd label must be non-empty and contain no whitespace")
        if not self.program_arguments:
            raise ValueError("launchd ProgramArguments cannot be empty")
        if not Path(self.program_arguments[0]).is_absolute():
            raise ValueError("launchd executable must be an absolute path")
        if not self.working_directory.is_absolute():
            raise ValueError("launchd working directory must be absolute")
        if not self.standard_out_path.is_absolute() or not self.standard_error_path.is_absolute():
            raise ValueError("launchd log paths must be absolute")
        if self.start_interval_seconds < 60:
            raise ValueError("launchd StartInterval must be at least 60 seconds")


UpdateAttempt = Callable[[pd.Timestamp, datetime], DailyUpdateResult]
NowFunction = Callable[[], datetime]
SleepFunction = Callable[[float], None]


def target_session_for_now(now: datetime) -> pd.Timestamp:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local = now.astimezone(NY)
    return previous_session(local.date()).normalize()


def _empty_result(
    *,
    project_dir: str | Path,
    status: DailyUpdateStatus,
    now: datetime,
    target: pd.Timestamp,
    message: str,
    next_check_at: datetime | None = None,
) -> DailyUpdateResult:
    return DailyUpdateResult(
        status=status,
        updated_at=now.astimezone(UTC).isoformat(),
        target_session=target.date().isoformat(),
        latest_complete_session=None,
        last_good_session=last_good_session(ProjectPaths(Path(project_dir).resolve())),
        sources={},
        message=message,
        next_check_at=next_check_at.astimezone(UTC).isoformat() if next_check_at else None,
    )


def _already_finished(project_dir: str | Path, target: pd.Timestamp) -> DailyUpdateResult | None:
    payload = read_update_status(project_dir)
    if payload is None or payload.get("target_session") != target.date().isoformat():
        return None
    if payload.get("status") not in {
        DailyUpdateStatus.PUBLISHED.value,
        DailyUpdateStatus.ALREADY_CURRENT.value,
    }:
        return None
    sources = payload.get("sources")
    return DailyUpdateResult(
        status=DailyUpdateStatus.ALREADY_CURRENT,
        updated_at=str(payload.get("updated_at")),
        target_session=target.date().isoformat(),
        latest_complete_session=(
            str(payload["latest_complete_session"])
            if payload.get("latest_complete_session")
            else None
        ),
        last_good_session=(
            str(payload["last_good_session"]) if payload.get("last_good_session") else None
        ),
        sources=(
            {str(key): dict(value) for key, value in sources.items()}
            if isinstance(sources, dict)
            else {}
        ),
        message=f"daily session {target.date()} already completed",
        snapshot_path=str(payload["snapshot_path"]) if payload.get("snapshot_path") else None,
    )


def _window_exhausted(
    project_dir: str | Path,
    now: datetime,
    target: pd.Timestamp,
    prior: DailyUpdateResult | None,
) -> DailyUpdateResult:
    result = DailyUpdateResult(
        status=DailyUpdateStatus.WINDOW_EXHAUSTED,
        updated_at=now.astimezone(UTC).isoformat(),
        target_session=target.date().isoformat(),
        latest_complete_session=prior.latest_complete_session if prior else None,
        last_good_session=(
            prior.last_good_session
            if prior
            else last_good_session(ProjectPaths(Path(project_dir).resolve()))
        ),
        sources=prior.sources if prior else {},
        message=f"bounded source polling window exhausted for {target.date()}; last-good preserved",
    )
    write_update_status(project_dir, result)
    return result


def run_bounded_polling(
    project_dir: str | Path,
    attempt: UpdateAttempt,
    *,
    policy: PollPolicy | None = None,
    now_fn: NowFunction | None = None,
    sleep_fn: SleepFunction = time.sleep,
) -> DailyUpdateResult:
    """Poll only around the New York publication window and stop after a fixed bound."""

    policy = policy or PollPolicy()
    clock = now_fn or (lambda: datetime.now(UTC))
    initial = clock()
    if initial.tzinfo is None:
        raise ValueError("now_fn must return timezone-aware datetimes")
    target = target_session_for_now(initial)
    finished = _already_finished(project_dir, target)
    if finished is not None:
        return finished

    window_start = decision_as_of(target)
    window_end = window_start + policy.max_wait
    local_now = initial.astimezone(NY)
    if local_now < window_start - policy.prefetch_lead:
        result = _empty_result(
            project_dir=project_dir,
            status=DailyUpdateStatus.NOT_DUE,
            now=initial,
            target=target,
            message=f"outside prefetch window for {target.date()}",
            next_check_at=window_start - policy.prefetch_lead,
        )
        write_update_status(project_dir, result)
        return result
    if local_now < window_start:
        result = attempt(target, initial)
        if result.status != DailyUpdateStatus.NOT_DUE:
            result = replace(
                result,
                status=DailyUpdateStatus.NOT_DUE,
                message=f"sources prefetched; formal publication waits until {window_start.isoformat()}",
            )
        result = replace(result, next_check_at=window_start.astimezone(UTC).isoformat())
        write_update_status(project_dir, result)
        return result
    if local_now > window_end:
        return _window_exhausted(project_dir, initial, target, None)

    interval_seconds = policy.interval.total_seconds()
    maximum_attempts = math.ceil(policy.max_wait.total_seconds() / interval_seconds) + 1
    prior: DailyUpdateResult | None = None
    for _ in range(maximum_attempts):
        current = clock()
        if current.tzinfo is None:
            raise ValueError("now_fn must return timezone-aware datetimes")
        if current.astimezone(NY) > window_end:
            return _window_exhausted(project_dir, current, target, prior)
        try:
            result = attempt(target, current)
        except Exception as exc:
            result = _empty_result(
                project_dir=project_dir,
                status=DailyUpdateStatus.FAILED,
                now=current,
                target=target,
                message=f"daily update attempt raised {type(exc).__name__}: {exc}",
            )
            write_update_status(project_dir, result)
            return result
        prior = result
        if result.status in {
            DailyUpdateStatus.PUBLISHED,
            DailyUpdateStatus.ALREADY_CURRENT,
            DailyUpdateStatus.FAILED,
        }:
            write_update_status(project_dir, result)
            return result
        if result.status != DailyUpdateStatus.SOURCES_PENDING:
            write_update_status(project_dir, result)
            return result
        next_check = min(
            current.astimezone(NY) + policy.interval,
            window_end,
        )
        if next_check >= window_end:
            return _window_exhausted(project_dir, current, target, result)
        pending = replace(result, next_check_at=next_check.astimezone(UTC).isoformat())
        write_update_status(project_dir, pending)
        sleep_fn(interval_seconds)
    return _window_exhausted(project_dir, clock(), target, prior)


def render_launchd_plist(spec: LaunchdPlistSpec) -> str:
    """Render an installable LaunchAgent plist; the Python gate owns New York time/DST."""

    payload: dict[str, Any] = {
        "Label": spec.label,
        "ProgramArguments": list(spec.program_arguments),
        "WorkingDirectory": str(spec.working_directory),
        "EnvironmentVariables": {
            "MATVIX_PROJECT_DIR": str(spec.working_directory),
            "PYTHONUNBUFFERED": "1",
        },
        "StartInterval": spec.start_interval_seconds,
        "RunAtLoad": False,
        "KeepAlive": False,
        "ProcessType": "Background",
        "ThrottleInterval": 60,
        "StandardOutPath": str(spec.standard_out_path),
        "StandardErrorPath": str(spec.standard_error_path),
    }
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=False).decode("utf-8")


def write_launchd_plist(spec: LaunchdPlistSpec, destination: str | Path) -> Path:
    """Atomically write a plist for later explicit `launchctl bootstrap`; does not install it."""

    target = Path(destination).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    content = render_launchd_plist(spec).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(content)
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def recommended_launch_agent_path(label: str, *, home: str | Path) -> Path:
    if not label or any(character.isspace() for character in label):
        raise ValueError("launchd label must be non-empty and contain no whitespace")
    return Path(home).expanduser().resolve() / "Library" / "LaunchAgents" / f"{label}.plist"
