from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

from ai_market_news import (
    article_fingerprint,
    merge_display_items,
    merge_seen_headlines,
    previous_display_items,
    previous_event_history,
    previous_seen_headlines,
    previous_seen_fingerprints,
    quarterly_article_item,
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


def test_quarterly_result_is_reprocessed_only_when_public_content_changes():
    initial = {
        "title": "NVIDIA Announces Financial Results",
        "summary": "Official company quarterly-results publication.",
        "event_type": "QUARTERLY_RESULTS",
    }
    enriched = {
        **initial,
        "summary": "Revenue and guidance are now included in the public summary.",
    }
    seen_headlines = [initial["title"]]
    seen_fingerprints = [article_fingerprint(initial)]

    assert unseen_articles(
        [initial], seen_headlines, seen_fingerprints
    ) == []
    assert unseen_articles(
        [enriched], seen_headlines, seen_fingerprints
    ) == [enriched]


def test_seen_content_fingerprints_are_loaded_from_previous_briefing():
    assert previous_seen_fingerprints(
        {"seen_article_fingerprints": ["abc", "abc", "def"]}
    ) == ["abc", "def"]


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


def display_item(event, published_at, headline=None):
    return {
        "event": event,
        "source_headlines": [headline or event],
        "published_at": published_at,
    }


def test_selected_result_remains_visible_for_strictly_five_days():
    today = datetime(2026, 8, 27, tzinfo=timezone.utc).date()
    payload = {
        "display_items": [
            display_item(
                "NVIDIA quarterly results",
                "2026-08-23",
            )
        ]
    }

    assert len(previous_display_items(payload, today=today)) == 1


def test_selected_result_expires_on_day_five():
    today = datetime(2026, 8, 27, tzinfo=timezone.utc).date()
    payload = {
        "display_items": [
            display_item(
                "NVIDIA quarterly results",
                "2026-08-22",
            )
        ]
    }

    assert previous_display_items(payload, today=today) == []


def test_legacy_quarterly_result_is_recovered_from_recent_events():
    today = datetime(2026, 8, 27, tzinfo=timezone.utc).date()
    payload = {
        "items": [],
        "recent_events": [
            display_item(
                "Publication des résultats financiers de NVIDIA",
                "2026-08-25",
                "NVIDIA 2nd Quarter FY27 Financial Results",
            )
        ],
    }

    recovered = previous_display_items(payload, today=today)

    assert len(recovered) == 1
    assert recovered[0]["related_tickers"] == ["NVDA"]
    assert recovered[0]["recovered_from_history"] is True


def test_enriched_result_replaces_placeholder_instead_of_duplicating_it():
    today = datetime(2026, 8, 27, tzinfo=timezone.utc).date()
    placeholder = display_item(
        "NVIDIA quarterly results",
        "2026-08-25",
        "NVIDIA 2nd Quarter FY27 Financial Results",
    )
    placeholder["recovered_from_history"] = True
    enriched = dict(placeholder)
    enriched["confidence"] = "HIGH"
    enriched.pop("recovered_from_history")

    merged = merge_display_items([placeholder], [enriched], today=today)

    assert len(merged) == 1
    assert merged[0]["confidence"] == "HIGH"


def test_new_official_quarterly_release_replaces_old_ticker_placeholder():
    today = datetime(2026, 8, 28, tzinfo=timezone.utc).date()
    old = display_item(
        "Publication des résultats financiers de NVIDIA",
        "2026-08-25",
        "NVIDIA 2nd Quarter FY27 Financial Results",
    )
    old["related_tickers"] = ["NVDA"]
    new = quarterly_article_item(
        {
            "title": "NVIDIA Announces Financial Results for Second Quarter Fiscal 2027",
            "summary": "Official company quarterly-results publication.",
            "event_type": "QUARTERLY_RESULTS",
            "ticker": "NVDA",
            "source": "Company IR",
            "date": "Thu, 27 Aug 2026 20:00:00 GMT",
            "url": "https://example.com/nvidia-results",
        }
    )

    merged = merge_display_items([old], [new], today=today)

    assert len(merged) == 1
    # 20:00 UTC is already the following calendar day in Singapore.
    assert merged[0]["published_at"] == "2026-08-28"
    assert merged[0]["source_headlines"] == [
        "NVIDIA Announces Financial Results for Second Quarter Fiscal 2027"
    ]
