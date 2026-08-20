import json
from datetime import datetime
from pathlib import Path

import yfinance as yf

from config import WATCHLIST


HERE = Path(__file__).resolve().parent
OUTPUT_PATH = HERE / "history" / "valuation_latest.json"


def _number(value):
    try:
        number = float(value)
        return number if number == number else None
    except (TypeError, ValueError):
        return None


def _score_lower(value, bands):
    if value is None or value <= 0:
        return None
    for maximum, points in bands:
        if value <= maximum:
            return points
    return 0


def _score_higher(value, bands):
    if value is None:
        return None
    for minimum, points in bands:
        if value >= minimum:
            return points
    return 0


def _normalized_score(parts):
    earned = sum(score for score, maximum in parts if score is not None)
    available = sum(maximum for score, maximum in parts if score is not None)
    if available == 0:
        return None, 0
    return round(earned / available * 100), available


def valuation_label(score):
    if score is None:
        return "INDISPONIBLE"
    if score >= 85:
        return "TRÈS ATTRACTIVE"
    if score >= 70:
        return "ATTRACTIVE"
    if score >= 50:
        return "RAISONNABLE"
    if score >= 30:
        return "CHÈRE"
    return "TRÈS CHÈRE"


def score_valuation(ticker, info, audit=None):
    audit = audit or {}
    source_price = _number(audit.get("price"))
    forward_eps = _number(info.get("forwardEps"))
    calculated_forward_pe = (
        source_price / forward_eps
        if source_price is not None
        and source_price > 0
        and forward_eps is not None
        and forward_eps > 0
        else None
    )
    reported_forward_pe = _number(info.get("forwardPE"))
    forward_pe = calculated_forward_pe or reported_forward_pe
    trailing_pe = _number(info.get("trailingPE"))
    revenue_growth = _number(info.get("revenueGrowth"))
    price_to_sales = _number(info.get("priceToSalesTrailing12Months"))
    enterprise_to_revenue = _number(info.get("enterpriseToRevenue"))
    free_cashflow = _number(info.get("freeCashflow"))
    market_cap = _number(info.get("marketCap"))
    trading_currency = info.get("currency")
    financial_currency = info.get("financialCurrency")
    currencies_match = (
        bool(trading_currency)
        and bool(financial_currency)
        and trading_currency == financial_currency
    )
    fcf_yield = (
        free_cashflow / market_cap
        if free_cashflow is not None and market_cap not in (None, 0)
        and currencies_match
        else None
    )
    profitable = forward_pe is not None and forward_pe > 0
    if profitable:
        pe_score = _score_lower(
            forward_pe,
            ((15, 50), (20, 43), (25, 35), (30, 27), (40, 16), (50, 8)),
        )
        trailing_pe_score = _score_lower(
            trailing_pe,
            ((15, 15), (20, 12), (25, 9), (30, 7), (40, 5), (50, 3), (70, 1)),
        )
        ps_score = _score_lower(
            price_to_sales,
            ((3, 20), (5, 16), (8, 12), (12, 8), (20, 4)),
        )
        fcf_yield_score = _score_higher(
            fcf_yield,
            ((0.08, 15), (0.05, 12), (0.03, 9), (0.01, 5), (0.0, 3)),
        )
        score, available = _normalized_score(
            (
                (pe_score, 50),
                (trailing_pe_score, 15),
                (ps_score, 20),
                (fcf_yield_score, 15),
            )
        )
        method = "PROFITABLE"
    else:
        ps_score = _score_lower(
            price_to_sales,
            ((2, 50), (4, 42), (7, 31), (10, 20), (15, 9)),
        )
        ev_sales_score = _score_lower(
            enterprise_to_revenue,
            ((2, 25), (4, 21), (7, 15), (10, 9), (15, 4)),
        )
        revenue_score = _score_higher(
            revenue_growth,
            ((0.40, 25), (0.25, 21), (0.15, 16), (0.08, 11), (0.0, 5)),
        )
        score, available = _normalized_score(
            ((ps_score, 50), (ev_sales_score, 25), (revenue_score, 25))
        )
        method = "LOW_OR_NO_EARNINGS"

    confidence = "HIGH" if available >= 80 else "MEDIUM" if available >= 50 else "LOW"
    return {
        "ticker": ticker,
        "score": score,
        "label": valuation_label(score),
        "confidence": confidence,
        "method": method,
        "metrics": {
            "forward_pe": forward_pe,
            "forward_pe_reported": reported_forward_pe,
            "forward_eps_ntm": forward_eps,
            "price_used": source_price,
            "price_date": audit.get("price_date"),
            "currency": trading_currency,
            "financial_currency": financial_currency,
            "source": "Yahoo Finance",
            "trailing_pe": trailing_pe,
            "revenue_growth": revenue_growth,
            "price_to_sales": price_to_sales,
            "enterprise_to_revenue": enterprise_to_revenue,
            "fcf_yield": fcf_yield,
            "fcf_yield_status": (
                "USED"
                if fcf_yield is not None
                else "NOT_USED_CURRENCY_MISMATCH_OR_UNAVAILABLE"
            ),
            "peg_status": "NOT_USED_LONG_TERM_GROWTH_UNAVAILABLE",
        },
    }


def build_valuations(tickers):
    items = []
    unavailable = []
    for ticker in tickers:
        try:
            company = yf.Ticker(ticker)
            info = company.info or {}
            history = company.history(period="5d", auto_adjust=False)
            audit = {}
            if not history.empty:
                audit = {
                    "price": float(history["Close"].iloc[-1]),
                    "price_date": history.index[-1].date().isoformat(),
                }
            items.append(score_valuation(ticker, info, audit))
        except Exception as error:
            unavailable.append({"ticker": ticker, "reason": str(error)})
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "method": "valuation_v2_no_peg",
        "items": items,
        "unavailable": unavailable,
    }


def main():
    output = build_valuations(WATCHLIST)
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
