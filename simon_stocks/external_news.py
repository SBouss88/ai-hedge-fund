import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache

import requests

from news_config import COMPANY_TERMS, SECTOR_TERMS


RUNDOWN_RSS_URL = "https://news.google.com/rss/search"
QUARTR_API_URL = "https://api.quartr.com/public/v3"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"
TIMEOUT = 12
NEWS_MAX_AGE_DAYS = 5
SEC_HEADERS = {
    "User-Agent": (
        "Simon-AI-Stocks personal-research "
        "https://github.com/SBouss88/ai-hedge-fund"
    ),
    "Accept-Encoding": "gzip, deflate",
}
SEC_MATERIAL_FORMS = {"8-K", "10-Q", "10-K", "6-K", "20-F", "40-F"}
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
EARNINGS_MARKERS = (
    "quarter results",
    "quarterly results",
    "financial results",
    "earnings results",
    "earnings release",
    "reports first quarter",
    "reports second quarter",
    "reports third quarter",
    "reports fourth quarter",
)
NON_MATERIAL_IR_MARKERS = (
    "technical sessions",
    "labs and certs",
    "register now",
    "registration opens",
    "event agenda",
    "conference schedule",
    "webinar",
)
AI_MARKET_TICKERS = (
    "NVDA",
    "MSFT",
    "GOOGL",
    "META",
    "AMZN",
    "AVGO",
    "AMD",
    "ASML",
    "ORCL",
    "PLTR",
    "ARM",
    "TSM",
    "MU",
    "SNDK",
    "NBIS",
    "SDGR",
    "RXRX",
    "ABSI",
)
COMPANY_IR_DOMAINS = {
    "NVDA": "investor.nvidia.com",
    "MSFT": "microsoft.com",
    "GOOGL": "abc.xyz",
    "META": "investor.atmeta.com",
    "AMZN": "ir.aboutamazon.com",
    "AVGO": "investors.broadcom.com",
    "AMD": "ir.amd.com",
    "ASML": "asml.com",
    "ORCL": "investor.oracle.com",
    "PLTR": "investors.palantir.com",
    "ARM": "investors.arm.com",
    "TSM": "investor.tsmc.com",
    "MU": "investors.micron.com",
    "SNDK": "investor.sandisk.com",
    "NBIS": "group.nebius.com",
    "SDGR": "ir.schrodinger.com",
    "RXRX": "ir.recursion.com",
    "ABSI": "investors.absci.com",
}
COMPANY_IR_QUERY_SITES = {
    "MSFT": "microsoft.com/en-us/Investor",
    "GOOGL": "abc.xyz/investor",
    "ASML": "asml.com/en/investors",
}


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


@lru_cache(maxsize=1)
def _sec_company_map():
    payload = _request_json(
        SEC_TICKERS_URL,
        headers=SEC_HEADERS,
        params={},
    )
    return {
        company["ticker"].upper(): {
            "cik": str(company["cik_str"]).zfill(10),
            "name": company["title"],
        }
        for company in payload.values()
        if company.get("ticker") and company.get("cik_str")
    }


def _sec_recent_filings(ticker, *, days=21, limit=2):
    company = _sec_company_map().get(ticker.upper())
    if not company:
        return []

    payload = _request_json(
        f"{SEC_SUBMISSIONS_URL}/CIK{company['cik']}.json",
        headers=SEC_HEADERS,
        params={},
    )
    recent = payload.get("filings", {}).get("recent", {})
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date()
    filings = []

    for index, form in enumerate(recent.get("form", [])):
        if form not in SEC_MATERIAL_FORMS:
            continue

        filing_date = recent.get("filingDate", [])[index]
        try:
            if datetime.fromisoformat(filing_date).date() < cutoff:
                continue
        except (TypeError, ValueError):
            continue

        accession = recent.get("accessionNumber", [])[index]
        document = recent.get("primaryDocument", [])[index]
        description = recent.get("primaryDocDescription", [])[index] or form
        items = recent.get("items", [])[index]
        report_date = recent.get("reportDate", [])[index]
        filing_url = (
            f"{SEC_ARCHIVES_URL}/{int(company['cik'])}/"
            f"{accession.replace('-', '')}/{document}"
        )
        details = [f"Official {form} filed on {filing_date}"]
        if report_date:
            details.append(f"reporting period {report_date}")
        if items:
            details.append(f"reported items: {items}")

        filings.append({
            "title": f"{ticker.upper()} — {form}: {description}",
            "summary": "; ".join(details) + ".",
            "date": filing_date,
            "company": company["name"],
            "ticker": ticker.upper(),
            "source": "SEC/EDGAR",
            "source_type": "FIRST_PARTY",
            "event_type": (
                "QUARTERLY_RESULTS" if form == "10-Q" else "REGULATORY_FILING"
            ),
            "url": filing_url,
        })
        if len(filings) >= limit:
            break

    return filings


def fetch_sec_market_news(limit=12):
    news = []
    successful_requests = 0
    try:
        _sec_company_map()
    except requests.RequestException:
        return [], "UNAVAILABLE"

    for ticker in AI_MARKET_TICKERS:
        try:
            filings = _sec_recent_filings(ticker)
            successful_requests += 1
        except (requests.RequestException, KeyError, IndexError, TypeError):
            filings = []
        news.extend(filings)
        # SEC fair-access guidance caps automated traffic at 10 requests/second.
        time.sleep(0.12)

    news.sort(key=_date_sort_key, reverse=True)
    status = "OK" if successful_requests else "UNAVAILABLE"
    return news[:limit], status


def fetch_sec_news(ticker, limit=2):
    try:
        return _sec_recent_filings(ticker, days=45, limit=limit), "OK"
    except (requests.RequestException, KeyError, IndexError, TypeError):
        return [], "UNAVAILABLE"


def _is_rundown_tutorial(title):
    title_lower = title.lower()
    return (
        title_lower.startswith(RUNDOWN_TUTORIAL_PREFIXES)
        or any(marker in title_lower for marker in RUNDOWN_TUTORIAL_MARKERS)
    )


def classify_news_event(title):
    normalized = re.sub(r"\s+", " ", title.lower()).strip()
    return (
        "QUARTERLY_RESULTS"
        if (
            any(marker in normalized for marker in EARNINGS_MARKERS)
            or ("quarter" in normalized and "result" in normalized)
        )
        else "CORPORATE_NEWS"
    )


def _is_non_material_ir_item(title):
    normalized = title.lower()
    return any(marker in normalized for marker in NON_MATERIAL_IR_MARKERS)


def _google_news_items(query):
    response = requests.get(
        RUNDOWN_RSS_URL,
        params={
            "q": query,
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        },
        headers={"User-Agent": "Simon-AI-Stocks/1.0"},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return ET.fromstring(response.content).findall("./channel/item")


def _date_sort_key(item):
    raw = item.get("date", "")
    try:
        return parsedate_to_datetime(raw).timestamp()
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(raw).timestamp()
        except (TypeError, ValueError):
            return 0


def is_recent_news(item, max_age_days=NEWS_MAX_AGE_DAYS):
    timestamp = _date_sort_key(item)
    if not timestamp:
        return False
    published = datetime.fromtimestamp(timestamp, tz=timezone.utc).date()
    today = datetime.now(timezone.utc).date()
    age_days = (today - published).days
    return 0 <= age_days <= max_age_days


def fetch_company_ir_news(ticker, limit=3):
    domain = COMPANY_IR_DOMAINS.get(ticker.upper())
    if not domain:
        return [], "NOT CONFIGURED"

    try:
        query_site = COMPANY_IR_QUERY_SITES.get(ticker.upper(), domain)
        items = _google_news_items(f"site:{query_site} when:45d")
    except (requests.RequestException, ET.ParseError):
        return [], "UNAVAILABLE"

    news = []
    for item in items:
        source = item.find("source")
        source_url = source.get("url", "").lower() if source is not None else ""
        if domain not in source_url:
            continue
        title = (item.findtext("title") or "").strip()
        title = re.sub(r"\s+-\s+[^-]+$", "", title)
        if not title or _is_non_material_ir_item(title):
            continue
        news.append({
            "title": title,
            "summary": "Official company Investor Relations headline.",
            "date": (item.findtext("pubDate") or "").strip(),
            "company": ticker.upper(),
            "ticker": ticker.upper(),
            "source": "Company IR",
            "source_type": "FIRST_PARTY",
            "event_type": classify_news_event(title),
            "url": (item.findtext("link") or "").strip(),
        })
        if len(news) >= limit:
            break
    return news, "OK"


def fetch_company_ir_market_news(limit=12):
    news = []
    unavailable = 0
    for ticker in AI_MARKET_TICKERS:
        items, status = fetch_company_ir_news(ticker, limit=2)
        news.extend(items)
        unavailable += status == "UNAVAILABLE"

    news.sort(key=_date_sort_key, reverse=True)
    status = "UNAVAILABLE" if unavailable == len(AI_MARKET_TICKERS) else "OK"
    return news[:limit], status


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
            "event_type": classify_news_event(title),
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
            "event_type": classify_news_event(title),
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
            "event_type": classify_news_event(title),
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
        title = event.get("title") or "Official company event"
        news.append({
            "title": title,
            "summary": summary or "Official company event listed by Quartr.",
            "date": event.get("date") or event.get("updatedAt") or "",
            "company": company,
            "source": "Quartr",
            "source_type": "FIRST_PARTY",
            "event_type": classify_news_event(title),
            "url": event.get("backlinkUrl") or "",
        })

    return news, "OK"


def fetch_ai_market_news():
    rundown, rundown_status = fetch_rundown_market_news()
    quartr, quartr_status = fetch_quartr_market_news()
    sec, sec_status = fetch_sec_market_news()
    company_ir, company_ir_status = fetch_company_ir_market_news()
    news = sec + company_ir + quartr + rundown
    return [item for item in news if is_recent_news(item)], {
        "SEC/EDGAR": sec_status,
        "Company IR": company_ir_status,
        "The Rundown AI": rundown_status,
        "Quartr": quartr_status,
    }


def fetch_external_news(ticker):
    rundown, rundown_status = fetch_rundown_news(ticker)
    quartr, quartr_status = fetch_quartr_news(ticker)
    sec, sec_status = fetch_sec_news(ticker)
    company_ir, company_ir_status = fetch_company_ir_news(ticker)
    news = sec + company_ir + quartr + rundown
    return [item for item in news if is_recent_news(item)], {
        "SEC/EDGAR": sec_status,
        "Company IR": company_ir_status,
        "The Rundown AI": rundown_status,
        "Quartr": quartr_status,
    }
