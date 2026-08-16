import os
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import requests

from news_config import COMPANY_TERMS, SECTOR_TERMS


RUNDOWN_RSS_URL = "https://news.google.com/rss/search"
QUARTR_API_URL = "https://api.quartr.com/public/v3"
TIMEOUT = 12
RUNDOWN_TUTORIAL_MARKERS = (
    "tutorial",
    "workflow",
)
RUNDOWN_TUTORIAL_PREFIXES = (
    "how to ",
    "build ",
    "create ",
    "automate ",
    "generate ",
    "use ",
    "compare ",
)
AI_MARKET_TICKERS = (
    "NVDA",
    "MSFT",
    "GOOGL",
    "META",
    "AMZN",
    "AVGO",
    "AMD",
    "ORCL",
    "PLTR",
    "ARM",
    "TSM",
    "MU",
    "SNDK",
    "NBIS",
)


@lru_cache(maxsize=None)
def keychain_secret(service):
    value = os.getenv(service)
    if value:
        return value.strip()

    result = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-a",
            os.getenv("USER", ""),
            "-s",
            service,
            "-w",
        ],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _request_json(url, *, headers, params):
    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def _is_rundown_tutorial(title):
    title_lower = title.lower()
    return (
        title_lower.startswith(RUNDOWN_TUTORIAL_PREFIXES)
        or any(marker in title_lower for marker in RUNDOWN_TUTORIAL_MARKERS)
    )


def fetch_rundown_news(ticker, limit=4):
    terms = [ticker, *COMPANY_TERMS.get(ticker, [])]
    query_terms = " OR ".join(
        f'"{term}"' if " " in term else term
        for term in dict.fromkeys(terms)
    )

    try:
        response = requests.get(
            RUNDOWN_RSS_URL,
            params={
                "q": f"site:therundown.ai ({query_terms}) when:30d",
                "hl": "en-US",
                "gl": "US",
                "ceid": "US:en",
            },
            headers={"User-Agent": "Simon-AI-Stocks/1.0"},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except (requests.RequestException, ET.ParseError):
        return [], "UNAVAILABLE"

    news = []
    relevance_terms = [
        term.lower()
        for term in [
            ticker,
            *COMPANY_TERMS.get(ticker, []),
            *SECTOR_TERMS.get(ticker, []),
        ]
    ]
    for item in root.findall("./channel/item"):
        source = item.find("source")
        source_url = source.get("url", "") if source is not None else ""
        if "therundown.ai" not in source_url:
            continue

        title = (item.findtext("title") or "").strip()
        title = re.sub(r"\s+-\s+The Rundown(?: AI| Tech)?$", "", title)
        title_lower = title.lower()
        if (
            not title
            or not any(term in title_lower for term in relevance_terms)
            or _is_rundown_tutorial(title)
        ):
            continue

        news.append({
            "title": title,
            "summary": "Editorial AI news headline selected for this company query.",
            "date": (item.findtext("pubDate") or "").strip(),
            "source": "The Rundown AI",
            "source_type": "EDITORIAL",
            "url": (item.findtext("link") or "").strip(),
        })
        if len(news) >= limit:
            break

    return news, "OK"


def fetch_rundown_market_news(limit=6):
    try:
        response = requests.get(
            RUNDOWN_RSS_URL,
            params={
                "q": "site:therundown.ai when:14d",
                "hl": "en-US",
                "gl": "US",
                "ceid": "US:en",
            },
            headers={"User-Agent": "Simon-AI-Stocks/1.0"},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except (requests.RequestException, ET.ParseError):
        return [], "UNAVAILABLE"

    news = []
    seen = set()
    for item in root.findall("./channel/item"):
        source = item.find("source")
        source_url = source.get("url", "") if source is not None else ""
        if "therundown.ai" not in source_url:
            continue

        title = (item.findtext("title") or "").strip()
        title = re.sub(r"\s+-\s+The Rundown(?: AI| Tech)?$", "", title)
        normalized = re.sub(r"\W+", " ", title.lower()).strip()
        if (
            not normalized
            or normalized in seen
            or _is_rundown_tutorial(title)
        ):
            continue
        seen.add(normalized)

        news.append({
            "title": title,
            "summary": "Editorial AI headline. Do not infer unstated details.",
            "date": (item.findtext("pubDate") or "").strip(),
            "source": "The Rundown AI",
            "source_type": "EDITORIAL",
            "url": (item.findtext("link") or "").strip(),
        })
        if len(news) >= limit:
            break

    return news, "OK"


def fetch_quartr_news(ticker, limit=3):
    api_key = keychain_secret("QUARTR_API_KEY")
    if not api_key:
        return [], "NOT CONFIGURED"

    headers = {
        "x-api-key": api_key,
        "User-Agent": "Simon-AI-Stocks/1.0",
    }
    start_date = (
        datetime.now(timezone.utc) - timedelta(days=120)
    ).isoformat(timespec="seconds")

    try:
        payload = _request_json(
            f"{QUARTR_API_URL}/events",
            headers=headers,
            params={
                "tickers": ticker,
                "limit": limit,
                "direction": "desc",
                "sortBy": "date",
                "startDate": start_date,
            },
        )
    except requests.RequestException:
        return [], "UNAVAILABLE"

    news = []
    for event in payload.get("data", []):
        event_id = event.get("id")
        title = event.get("title") or "Official company event"
        summary = ""

        if event_id is not None:
            try:
                summary_payload = _request_json(
                    f"{QUARTR_API_URL}/events/{event_id}/summary",
                    headers=headers,
                    params={"length": "short", "plain": "true"},
                )
                summary = summary_payload.get("data", {}).get("summary", "")
            except requests.RequestException:
                pass

        news.append({
            "title": title,
            "summary": summary or "Official company event listed by Quartr.",
            "date": event.get("date") or event.get("updatedAt") or "",
            "source": "Quartr",
            "source_type": "FIRST_PARTY",
            "url": event.get("backlinkUrl") or "",
        })

    return news, "OK"


def fetch_quartr_market_news(limit=10):
    api_key = keychain_secret("QUARTR_API_KEY")
    if not api_key:
        return [], "NOT CONFIGURED"

    headers = {
        "x-api-key": api_key,
        "User-Agent": "Simon-AI-Stocks/1.0",
    }
    tickers = ",".join(AI_MARKET_TICKERS)
    start_date = (
        datetime.now(timezone.utc) - timedelta(days=45)
    ).isoformat(timespec="seconds")

    try:
        companies_payload = _request_json(
            f"{QUARTR_API_URL}/companies",
            headers=headers,
            params={"tickers": tickers, "limit": 100},
        )
        ticker_by_company = {}
        for company in companies_payload.get("data", []):
            company_tickers = company.get("tickers") or []
            symbol = next(
                (
                    item.get("ticker")
                    for item in company_tickers
                    if item.get("ticker") in AI_MARKET_TICKERS
                ),
                company.get("displayName") or company.get("name") or "",
            )
            ticker_by_company[company.get("id")] = symbol

        events_payload = _request_json(
            f"{QUARTR_API_URL}/events",
            headers=headers,
            params={
                "tickers": tickers,
                "limit": limit,
                "direction": "desc",
                "sortBy": "date",
                "startDate": start_date,
            },
        )
    except requests.RequestException:
        return [], "UNAVAILABLE"

    news = []
    for event in events_payload.get("data", []):
        event_id = event.get("id")
        summary = ""
        if event_id is not None:
            try:
                summary_payload = _request_json(
                    f"{QUARTR_API_URL}/events/{event_id}/summary",
                    headers=headers,
                    params={"length": "short", "plain": "true"},
                )
                summary = summary_payload.get("data", {}).get("summary", "")
            except requests.RequestException:
                pass

        company = ticker_by_company.get(event.get("companyId"), "")
        news.append({
            "title": event.get("title") or "Official company event",
            "summary": summary or "Official company event listed by Quartr.",
            "date": event.get("date") or event.get("updatedAt") or "",
            "company": company,
            "source": "Quartr",
            "source_type": "FIRST_PARTY",
            "url": event.get("backlinkUrl") or "",
        })

    return news, "OK"


def fetch_ai_market_news():
    rundown, rundown_status = fetch_rundown_market_news()
    quartr, quartr_status = fetch_quartr_market_news()
    return quartr + rundown, {
        "The Rundown AI": rundown_status,
        "Quartr": quartr_status,
    }


def fetch_external_news(ticker):
    rundown, rundown_status = fetch_rundown_news(ticker)
    quartr, quartr_status = fetch_quartr_news(ticker)
    return quartr + rundown, {
        "The Rundown AI": rundown_status,
        "Quartr": quartr_status,
    }
