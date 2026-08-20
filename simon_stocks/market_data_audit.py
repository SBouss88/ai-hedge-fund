import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yfinance as yf

from config import WATCHLIST


HERE = Path(__file__).resolve().parent
HISTORY_DIR = HERE / "history"
OUTPUT_PATH = HISTORY_DIR / "market_data_audit_latest.json"
RANKINGS_PATH = HISTORY_DIR / "quick_rankings_latest.json"
EXPECTED_CURRENCY = {ticker: "USD" for ticker in WATCHLIST}


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_analysis_prices():
    if not RANKINGS_PATH.exists():
        return {}
    try:
        payload = json.loads(RANKINGS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {
        item["ticker"]: item.get("price")
        for item in payload.get("items", [])
        if item.get("ticker")
    }


def audit_ticker(ticker, analysis_price):
    company = yf.Ticker(ticker)
    info = company.info or {}
    history = company.history(period="2y", auto_adjust=False, actions=True)
    if history.empty:
        raise ValueError("historique Yahoo Finance indisponible")

    raw_close = _number(history["Close"].iloc[-1])
    adjusted_close = _number(history["Adj Close"].iloc[-1])
    price_date = history.index[-1].date().isoformat()
    currency = info.get("currency")
    exchange = info.get("fullExchangeName") or info.get("exchange")
    returned_symbol = str(info.get("symbol") or ticker).upper()
    quote_type = info.get("quoteType")
    warnings = []

    if returned_symbol != ticker.upper():
        warnings.append(f"symbole retourné {returned_symbol}")
    if currency != EXPECTED_CURRENCY[ticker]:
        warnings.append(
            f"devise {currency or 'inconnue'} au lieu de {EXPECTED_CURRENCY[ticker]}"
        )
    if not exchange:
        warnings.append("place de cotation indisponible")
    if quote_type and quote_type != "EQUITY":
        warnings.append(f"type d’instrument {quote_type}")

    reference_price = _number(analysis_price)
    discrepancy = None
    if raw_close and reference_price:
        discrepancy = abs(reference_price / raw_close - 1) * 100
        if discrepancy > 2:
            warnings.append(f"écart cours analyse/source {discrepancy:.1f}%")
    else:
        warnings.append("comparaison du cours impossible")

    adjustment_gap = None
    if raw_close and adjusted_close:
        adjustment_gap = abs(adjusted_close / raw_close - 1) * 100
        if adjustment_gap > 2:
            warnings.append(f"écart cours brut/ajusté {adjustment_gap:.1f}%")

    splits = []
    if "Stock Splits" in history:
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=730)
        for timestamp, ratio in history["Stock Splits"].items():
            ratio = _number(ratio)
            if ratio and ratio != 0 and timestamp.date() >= cutoff:
                splits.append({"date": timestamp.date().isoformat(), "ratio": ratio})

    notes = ["cours technique calculé avec auto_adjust=True"]
    if raw_close and raw_close >= 500:
        notes.append("prix nominal élevé confirmé par la source")
    if splits:
        notes.append("split détecté et historique ajusté")

    return {
        "ticker": ticker,
        "status": "REVIEW" if warnings else "VERIFIED",
        "returned_symbol": returned_symbol,
        "exchange": exchange,
        "currency": currency,
        "quote_type": quote_type,
        "price_date": price_date,
        "raw_close": raw_close,
        "adjusted_close": adjusted_close,
        "analysis_price": reference_price,
        "analysis_price_gap_pct": discrepancy,
        "adjustment_gap_pct": adjustment_gap,
        "splits_2y": splits,
        "warnings": warnings,
        "notes": notes,
        "source": "Yahoo Finance",
    }


def build_audit(tickers):
    prices = load_analysis_prices()
    items = []
    unavailable = []
    for ticker in tickers:
        try:
            items.append(audit_ticker(ticker, prices.get(ticker)))
        except Exception as error:
            unavailable.append({"ticker": ticker, "reason": str(error)})
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "method": "market_data_audit_v1",
        "items": items,
        "unavailable": unavailable,
    }


def main():
    output = build_audit(WATCHLIST)
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
