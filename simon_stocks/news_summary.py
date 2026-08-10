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
total_in = 0
total_out = 0

print("\nSIMON AI STOCK WATCHLIST - CONSOLIDATED NEWS\n")

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
You are consolidating financial news for ticker {ticker}.
Use ONLY the supplied titles and summaries. Do not add outside facts.

Several articles may describe the same underlying event.
Merge duplicates into ONE event so repeated coverage does not amplify the signal.

Return 1 to 4 DISTINCT events, ordered by investment importance.
For each event use exactly:
- EVENT: short description
  IMPACT: POSITIVE / NEUTRAL / NEGATIVE
  IMPORTANCE: LOW / MEDIUM / HIGH
  WHY: one short sentence

Then finish with exactly:
OVERALL: POSITIVE / NEUTRAL / NEGATIVE / MIXED
CONFIDENCE: LOW / MEDIUM / HIGH

Be conservative. If evidence conflicts, use MIXED. If direction is unclear, use NEUTRAL.

Articles:
{json.dumps(news, ensure_ascii=False)}
"""

    response = client.responses.create(model=MODEL, input=prompt)
    print(response.output_text)

    if response.usage:
        total_in += response.usage.input_tokens
        total_out += response.usage.output_tokens
        print(f"Tokens: {response.usage.input_tokens} input / {response.usage.output_tokens} output")

    print()

print("TOTAL TOKEN USAGE")
print(f"Input: {total_in}")
print(f"Output: {total_out}")
