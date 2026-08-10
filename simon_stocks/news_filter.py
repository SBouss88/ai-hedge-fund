import re
import yfinance as yf

from config import WATCHLIST
from news_config import COMPANY_TERMS, SECTOR_TERMS

NEWS_COUNT = 8


def classify(ticker, title, summary):
    raw = f"{title} {summary}"
    text = raw.lower()

    ticker_match = re.search(rf"\b{re.escape(ticker)}\b", raw, flags=re.IGNORECASE)
    company_match = any(term in text for term in COMPANY_TERMS.get(ticker, []))

    if ticker_match or company_match:
        return "DIRECT"

    if any(term in text for term in SECTOR_TERMS.get(ticker, [])):
        return "SECTOR"

    return "UNRELATED"


print("\nSIMON AI STOCK WATCHLIST - FILTERED NEWS\n")

for ticker in WATCHLIST:
    print(ticker)

    try:
        items = yf.Ticker(ticker).get_news(count=NEWS_COUNT, tab="news")
    except Exception as exc:
        print(f"  ERROR: {exc}\n")
        continue

    relevant = 0

    for item in items:
        content = item.get("content", {})
        title = content.get("title") or "No title"
        summary = content.get("summary") or content.get("description") or ""
        label = classify(ticker, title, summary)

        if label == "UNRELATED":
            continue

        relevant += 1
        print(f"  [{label}] {title}")

    if relevant == 0:
        print("  No relevant candidates found.")

    print()
