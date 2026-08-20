from __future__ import annotations

import calendar as pycal
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

NY = ZoneInfo("America/New_York")
CHICAGO = ZoneInfo("America/Chicago")
UTC = ZoneInfo("UTC")
_XNYS = xcals.get_calendar("XNYS", start="1989-01-01", end="2045-12-31")


def _ts(value: date | str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize(None).normalize()


def is_session(value: date | str | pd.Timestamp) -> bool:
    return bool(_XNYS.is_session(_ts(value)))


def sessions_in_range(start: date | str, end: date | str) -> pd.DatetimeIndex:
    return _XNYS.sessions_in_range(_ts(start), _ts(end)).tz_localize(None)


def next_session(value: date | str | pd.Timestamp) -> pd.Timestamp:
    ts = _ts(value)
    if _XNYS.is_session(ts):
        return _XNYS.next_session(ts).tz_localize(None)
    return _XNYS.date_to_session(ts, direction="next").tz_localize(None)


def previous_session(value: date | str | pd.Timestamp) -> pd.Timestamp:
    ts = _ts(value)
    if _XNYS.is_session(ts):
        return _XNYS.previous_session(ts).tz_localize(None)
    return _XNYS.date_to_session(ts, direction="previous").tz_localize(None)


def add_sessions(value: date | str | pd.Timestamp, count: int) -> pd.Timestamp:
    ts = _ts(value)
    session = ts if _XNYS.is_session(ts) else _XNYS.date_to_session(ts, direction="previous")
    if count == 0:
        return pd.Timestamp(session).tz_localize(None)
    return pd.Timestamp(_XNYS.session_offset(session, count)).tz_localize(None)


def decision_as_of(session_date: date | str | pd.Timestamp) -> datetime:
    next_day = next_session(session_date).date()
    return datetime.combine(next_day, time(9, 20), tzinfo=NY)


def observed_at_eod(session_date: date | str | pd.Timestamp) -> datetime:
    return datetime.combine(_ts(session_date).date(), time(16, 15), tzinfo=NY)


def third_friday(year: int, month: int) -> date:
    cal = pycal.monthcalendar(year, month)
    fridays = [week[pycal.FRIDAY] for week in cal if week[pycal.FRIDAY] != 0]
    return date(year, month, fridays[2])


def vix_final_settlement_date(year: int, month: int) -> date:
    """Return the standard monthly VX final settlement date.

    Rule: 30 calendar days before the third Friday of the following month. If that
    Friday is not an exchange session, use the preceding exchange session before
    subtracting 30 days. If the resulting Wednesday is not a session, use the
    preceding session. This is sufficient for the public CFE contract calendar and
    is tested around Good Friday and ordinary rolls.
    """

    if month == 12:
        fy, fm = year + 1, 1
    else:
        fy, fm = year, month + 1
    friday = third_friday(fy, fm)
    if not is_session(friday):
        friday = previous_session(friday).date()
    candidate = friday - timedelta(days=30)
    if not is_session(candidate):
        candidate = previous_session(candidate).date()
    return candidate


def final_settlement_timestamp(year: int, month: int) -> datetime:
    day = vix_final_settlement_date(year, month)
    return datetime.combine(day, time(8, 0), tzinfo=CHICAGO)


def settlement_selection_cutoff(session_date: date | str | pd.Timestamp) -> datetime:
    return datetime.combine(_ts(session_date).date(), time(15, 0), tzinfo=CHICAGO)
