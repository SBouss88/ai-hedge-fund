import yfinance as yf
from config import WATCHLIST

NEWS_COUNT = 5

print("\nSIMON AI STOCK WATCHLIST - NEWS CANDIDATES\n")

for ticker in WATCHLIST:
    print(ticker)

    try:
        items = yf.Ticker(ticker).get_news(count=NEWS_COUNT, tab="news")
    except Exception as exc:
        print(f"  ERROR: {exc}\n")
        continue

    if not items:
        print("  No news found.\n")
        continue

    for item in items:
        content = item.get("content", {})
        title = content.get("title") or "No title"
        summary = content.get("summary") or content.get("description") or ""
        pub_date = content.get("pubDate") or "Unknown date"

        provider = content.get("provider") or {}
        source = provider.get("displayName") if isinstance(provider, dict) else str(provider)
        source = source or "Unknown source"

        print(f"  - {pub_date} | {source}")
        print(f"    {title}")
        if summary:
            print(f"    Summary: {summary[:220]}")

    print()
