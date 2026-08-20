import json
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

from config import WATCHLIST


HISTORY_PATH = (
    Path(__file__).resolve().parent / "history" / "earnings_calendar_latest.json"
)


def _iso_date(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return datetime.fromisoformat(str(value)).date().isoformat()
    except (TypeError, ValueError):
        return None


def fetch_earnings_calendar(tickers):
    singapore_zone = ZoneInfo("Asia/Singapore")
    us_zone = ZoneInfo("America/New_York")
    today = datetime.now(singapore_zone).date()
    items = {}
    for ticker in tickers:
        try:
            company = yf.Ticker(ticker)
            calendar = company.get_calendar() or {}
            info = company.info or {}
            raw_dates = calendar.get("Earnings Date") or []
            if not isinstance(raw_dates, (list, tuple)):
                raw_dates = [raw_dates]
            dates = sorted(
                parsed
                for parsed in (_iso_date(value) for value in raw_dates)
                if parsed
            )
            future_dates = [value for value in dates if date.fromisoformat(value) >= today]
            if not future_dates:
                items[ticker] = {
                    "status": "UNAVAILABLE",
                    "source": "Yahoo Finance",
                }
                continue

            next_date = future_dates[0]
            timestamp = info.get("earningsTimestampStart") or info.get(
                "earningsTimestamp"
            )
            us_datetime = None
            singapore_datetime = None
            try:
                utc_datetime = datetime.fromtimestamp(float(timestamp), timezone.utc)
                us_datetime = utc_datetime.astimezone(us_zone)
                singapore_datetime = utc_datetime.astimezone(singapore_zone)
                if singapore_datetime.date() >= today:
                    next_date = singapore_datetime.date().isoformat()
            except (TypeError, ValueError, OSError):
                pass
            days_until = (date.fromisoformat(next_date) - today).days
            items[ticker] = {
                "date": next_date,
                "date_end": future_dates[-1] if len(future_dates) > 1 else None,
                "date_us": (
                    us_datetime.date().isoformat() if us_datetime else future_dates[0]
                ),
                "date_singapore": (
                    singapore_datetime.date().isoformat()
                    if singapore_datetime
                    else next_date
                ),
                "time_us": us_datetime.strftime("%H:%M") if us_datetime else None,
                "time_singapore": (
                    singapore_datetime.strftime("%H:%M")
                    if singapore_datetime
                    else None
                ),
                "event_timestamp_utc": (
                    utc_datetime.isoformat() if us_datetime else None
                ),
                "days_until": days_until,
                "status": "INDICATIVE",
                "source": "Yahoo Finance",
                "url": f"https://finance.yahoo.com/quote/{ticker}/",
            }
        except Exception:
            items[ticker] = {
                "status": "UNAVAILABLE",
                "source": "Yahoo Finance",
            }
    return items


def main():
    output = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "items": fetch_earnings_calendar(WATCHLIST),
    }
    HISTORY_PATH.parent.mkdir(exist_ok=True)
    HISTORY_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
