import json
import re
from typing import Literal

import yfinance as yf
from openai import OpenAI
from pydantic import BaseModel

from config import WATCHLIST
from news_config import COMPANY_TERMS, SECTOR_TERMS

NEWS_COUNT = 8
MODEL = "gpt-5.6-luna"


class NewsEvent(BaseModel):
    event: str
    impact: Literal["POSITIVE", "NEUTRAL", "NEGATIVE"]
    importance: Literal["LOW", "MEDIUM", "HIGH"]
    why: str


class NewsSummary(BaseModel):
    events: list[NewsEvent]
    overall: Literal["POSITIVE", "NEUTRAL", "NEGATIVE", "MIXED"]
    confidence: Literal["LOW", "MEDIUM", "HIGH"]


def keep(ticker, title, summary):
    raw = f"{title} {summary}"
    text = raw.lower()
    direct = re.search(rf"\b{re.escape(ticker)}\b", raw, re.I) or any(
        term in text for term in COMPANY_TERMS.get(ticker, [])
    )
    sector = any(term in text for term in SECTOR_TERMS.get(ticker, []))
    return bool(direct or sector)


client = OpenAI()
total_in = 0
total_out = 0

print("\nSIMON AI STOCK WATCHLIST - STRUCTURED NEWS\n")

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
        print("  No relevant news found.\n")
        continue

    prompt = f"""
Consolidate financial news for ticker {ticker}.
Use ONLY the supplied titles and summaries. Do not add outside facts.

Several articles may describe the same underlying event.
Merge duplicates so repeated coverage does not amplify the signal.

Return 1 to 4 distinct events, ordered by investment importance.

For each event:
- event: short description
- impact: likely effect on the investment thesis for {ticker}
- importance: materiality for the investment thesis
- why: one short sentence

Be conservative.
If direction is unclear, use NEUTRAL for the event.
The overall field may be MIXED when meaningful positive and negative evidence coexist.
Confidence reflects how clearly the supplied articles support the overall assessment.

Articles:
{json.dumps(news, ensure_ascii=False)}
"""

    response = client.responses.parse(
        model=MODEL,
        input=prompt,
        text_format=NewsSummary,
    )

    result = response.output_parsed

    if result is None:
        print("  Could not parse structured response.\n")
        continue

    for event in result.events:
        print(f"EVENT: {event.event}")
        print(f"IMPACT: {event.impact}")
        print(f"IMPORTANCE: {event.importance}")
        print(f"WHY: {event.why}\n")

    print(f"OVERALL: {result.overall}")
    print(f"CONFIDENCE: {result.confidence}")

    if response.usage:
        total_in += response.usage.input_tokens
        total_out += response.usage.output_tokens
        print(
            f"Tokens: {response.usage.input_tokens} input / "
            f"{response.usage.output_tokens} output"
        )

    print()

print("TOTAL TOKEN USAGE")
print(f"Input: {total_in}")
print(f"Output: {total_out}")
