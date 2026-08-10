import json
import re

import yfinance as yf
from openai import OpenAI

from config import WATCHLIST
from news_config import COMPANY_TERMS, SECTOR_TERMS

NEWS_COUNT = 8
MODEL = "gpt-5.6-luna"


def keep(ticker, title, summary):
    raw = f"{title} {summary}"
    text = raw.lower()
    direct = re.search(rf"\b{re.escape(ticker)}\b", raw, re.I) or any(
        term in text for term in COMPANY_TERMS.get(ticker, [])
    )
    sector = any(term in text for term in SECTOR_TERMS.get(ticker, []))
    return bool(direct or sector)


client = OpenAI()
total_in = total_out = 0

print("\nSIMON AI STOCK WATCHLIST - AI NEWS\n")

for ticker in WATCHLIST:
    items = yf.Ticker(ticker).get_news(count=NEWS_COUNT, tab="news")
    news = []

    for item in items:
        c = item.get("content", {})
        title = c.get("title") or ""
        summary = c.get("summary") or c.get("description") or ""
        if keep(ticker, title, summary):
            news.append({
                "title": title,
                "summary": summary,
                "date": c.get("pubDate") or "",
            })

    print(ticker)

    if not news:
        print("  No relevant candidates.\n")
        continue

    prompt = f"""
Analyze ONLY these supplied news items for ticker {ticker}. Do not add outside facts.

For every article classify:
relevance = DIRECT / SECTOR / UNRELATED
impact on the investment thesis = POSITIVE / NEUTRAL / NEGATIVE
importance = LOW / MEDIUM / HIGH
reason = one short sentence

DIRECT means materially about the company or directly affecting it.
SECTOR means a plausibly relevant industry, competitor, supplier, customer, or macro event.
UNRELATED means no meaningful connection.
If direction is unclear, use NEUTRAL.

Return exactly one numbered line per article, in order:
1. DIRECT | POSITIVE | HIGH | short reason

Articles:
{json.dumps(news, ensure_ascii=False)}
"""

    response = client.responses.create(model=MODEL, input=prompt)

    for i, article in enumerate(news, 1):
        print(f"  {i}. {article['title']}")

    print("\nAI CLASSIFICATION")
    print(response.output_text)

    if response.usage:
        total_in += response.usage.input_tokens
        total_out += response.usage.output_tokens
        print(
            f"\nTokens: {response.usage.input_tokens} input / "
            f"{response.usage.output_tokens} output"
        )

    print()

print("TOTAL TOKEN USAGE")
print(f"Input: {total_in}")
print(f"Output: {total_out}")
