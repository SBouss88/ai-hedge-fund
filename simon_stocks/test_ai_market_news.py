from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

from ai_market_news import (
    merge_seen_headlines,
    previous_event_history,
    previous_seen_headlines,
    unseen_articles,
)
from external_news import is_recent_news


def test_news_must_be_strictly_less_than_five_days_old():
    now = datetime.now(timezone.utc)
    four_days_old = {"date": format_datetime(now - timedelta(days=4))}
    five_days_old = {"date": format_datetime(now - timedelta(days=5))}

    assert is_recent_news(four_days_old) is True
    assert is_recent_news(five_days_old) is False


def test_only_headlines_previously_selected_are_filtered():
    previous = {
        "seen_headlines": ["Already selected"],
        "items": [{"source_headlines": ["Selected in legacy output"]}],
    }
    seen = previous_seen_headlines(previous)
    articles = [
        {"title": "Already selected"},
        {"title": "Selected in legacy output"},
        {"title": "Still eligible"},
    ]

    assert unseen_articles(articles, seen) == [{"title": "Still eligible"}]


def test_seen_headline_memory_is_deduplicated_and_bounded():
    assert merge_seen_headlines(["A", "B"], ["B", "C"], limit=3) == [
        "A",
        "B",
        "C",
    ]
    assert merge_seen_headlines(["A", "B", "C"], ["D"], limit=3) == [
        "B",
        "C",
        "D",
    ]


def test_previous_events_are_preserved_for_semantic_comparison():
    payload = {
        "recent_events": [
            {"event": "Existing event", "source_headlines": ["Old title"]}
        ],
        "items": [
            {"event": "New event", "source_headlines": ["New title"]}
        ],
    }

    assert [item["event"] for item in previous_event_history(payload)] == [
        "Existing event",
        "New event",
    ]
