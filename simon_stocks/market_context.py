import math
import re

import yfinance as yf


COMPANY_ALIASES = {
    "NVDA": ("nvidia",),
    "MSFT": ("microsoft",),
    "GOOGL": ("google", "alphabet", "deepmind"),
    "AVGO": ("broadcom", "vmware"),
    "AMD": ("amd", "advanced micro devices"),
    "ASML": ("asml",),
    "AMZN": ("amazon", "aws", "amazon web services"),
    "META": ("meta", "facebook"),
    "ORCL": ("oracle",),
    "PLTR": ("palantir",),
    "ARM": ("arm holdings", "arm ltd"),
    "TSM": ("tsmc", "taiwan semiconductor"),
    "MU": ("micron",),
    "SNDK": ("sandisk", "san disk"),
    "NBIS": ("nebius",),
    "SDGR": ("schrodinger", "schrödinger"),
    "RXRX": ("recursion pharmaceuticals", "recursion"),
    "ABSI": ("absci",),
}


def relevant_tickers(articles, limit=8):
    found = []
    for article in articles:
        explicit = str(article.get("ticker", "")).upper()
        if explicit in COMPANY_ALIASES and explicit not in found:
            found.append(explicit)

        text = " ".join(
            str(article.get(field, ""))
            for field in ("title", "summary", "company")
        ).lower()
        for ticker, aliases in COMPANY_ALIASES.items():
            if ticker in found:
                continue
            if any(re.search(rf"\b{re.escape(alias)}\b", text) for alias in aliases):
                found.append(ticker)

        if len(found) >= limit:
            break
    return found[:limit]


def _number(value, digits=2):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, digits) if math.isfinite(number) else None


def _rsi(close, periods=14):
    delta = close.diff()
    gains = delta.clip(lower=0).rolling(periods).mean()
    losses = (-delta.clip(upper=0)).rolling(periods).mean()
    value = 100 - 100 / (1 + gains / losses)
    return _number(value.iloc[-1], 1)


def _technical_regime(price, sma50, sma200, rsi14):
    if price is None or sma50 is None or sma200 is None:
        return "INSUFFICIENT DATA"
    if price < sma200:
        return "CAUTION"
    if price > sma50 > sma200 and rsi14 is not None and rsi14 >= 70:
        return "POSITIVE MOMENTUM — PRICE EXTENDED"
    if price > sma50 > sma200:
        return "POSITIVE MOMENTUM"
    if price > sma200 and price < sma50:
        return "WATCH — PULLBACK"
    return "MIXED"


def fetch_market_context(tickers):
    context = {}
    for ticker in dict.fromkeys(tickers):
        try:
            stock = yf.Ticker(ticker)
            history = stock.history(period="1y", auto_adjust=True)
            close = history["Close"].dropna()
            if close.empty:
                continue

            price = _number(close.iloc[-1])
            sma50 = _number(close.rolling(50).mean().iloc[-1])
            sma200 = _number(close.rolling(200).mean().iloc[-1])
            rsi14 = _rsi(close)
            try:
                info = stock.get_info()
            except Exception:
                info = {}

            context[ticker] = {
                "ticker": ticker,
                "price": price,
                "currency": info.get("currency") or "USD",
                "rsi14": rsi14,
                "vs_sma50_pct": (
                    _number((price / sma50 - 1) * 100, 1) if sma50 else None
                ),
                "vs_sma200_pct": (
                    _number((price / sma200 - 1) * 100, 1) if sma200 else None
                ),
                "technical_regime": _technical_regime(
                    price, sma50, sma200, rsi14
                ),
                "trailing_pe": _number(info.get("trailingPE"), 1),
                "forward_pe": _number(info.get("forwardPE"), 1),
                "price_to_sales": _number(
                    info.get("priceToSalesTrailing12Months"), 1
                ),
            }
        except Exception:
            continue
    return context
