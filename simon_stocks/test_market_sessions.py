from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from market_sessions import filter_closed_daily_bars


NY = ZoneInfo("America/New_York")


def daily_frame(*dates):
    return pd.DataFrame(
        {"Close": range(len(dates))},
        index=pd.to_datetime(dates).tz_localize(NY),
    )


def test_current_daily_bar_is_removed_during_us_session():
    frame = daily_frame("2026-08-26", "2026-08-27")
    result = filter_closed_daily_bars(
        frame,
        now=datetime(2026, 8, 27, 10, 35, tzinfo=NY),
    )
    assert [item.date().isoformat() for item in result.index] == ["2026-08-26"]


def test_current_daily_bar_is_kept_after_settlement_buffer():
    frame = daily_frame("2026-08-26", "2026-08-27")
    result = filter_closed_daily_bars(
        frame,
        now=datetime(2026, 8, 27, 16, 16, tzinfo=NY),
    )
    assert len(result) == 2


def test_previous_daily_bar_is_always_kept():
    frame = daily_frame("2026-08-25", "2026-08-26")
    result = filter_closed_daily_bars(
        frame,
        now=datetime(2026, 8, 27, 10, 35, tzinfo=NY),
    )
    assert len(result) == 2
