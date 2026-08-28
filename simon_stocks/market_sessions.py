"""Helpers ensuring that daily analyses only use completed US sessions."""

from datetime import datetime, time
from zoneinfo import ZoneInfo


NEW_YORK = ZoneInfo("America/New_York")
# Yahoo's daily candle can still be settling immediately after the bell.
REGULAR_SESSION_FINAL_AT = time(16, 15)


def filter_closed_daily_bars(frame, now=None):
    """Remove today's partial US daily candle while the session is unfinished."""
    if frame is None or frame.empty:
        return frame

    current = now or datetime.now(tz=NEW_YORK)
    if current.tzinfo is None:
        current = current.replace(tzinfo=NEW_YORK)
    else:
        current = current.astimezone(NEW_YORK)

    latest_date = frame.index[-1].date()
    session_is_still_open = (
        latest_date >= current.date()
        and current.time().replace(tzinfo=None) < REGULAR_SESSION_FINAL_AT
    )
    return frame.iloc[:-1].copy() if session_is_still_open else frame
