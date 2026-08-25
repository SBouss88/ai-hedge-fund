import json
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

import yfinance as yf

from config import WATCHLIST


HERE = Path(__file__).resolve().parent
OUTPUT_PATH = HERE / "history" / "valuation_latest.json"

PEER_GROUPS = {
    "NVDA": "AI_SEMICONDUCTORS",
    "AMD": "AI_SEMICONDUCTORS",
    "AVGO": "AI_SEMICONDUCTORS",
    "MU": "AI_SEMICONDUCTORS",
    "SNDK": "AI_SEMICONDUCTORS",
    "TSM": "AI_SEMICONDUCTORS",
    "ASML": "AI_SEMICONDUCTORS",
    "MSFT": "AI_PLATFORMS",
    "GOOGL": "AI_PLATFORMS",
    "AMZN": "AI_PLATFORMS",
    "NBIS": "AI_CLOUD_CHALLENGER",
    "SDGR": "AI_BIOTECH",
    "RXRX": "AI_BIOTECH",
    "ABSI": "AI_BIOTECH",
}
CYCLICAL_MEMORY_TICKERS = {"MU", "SNDK"}


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
    return 10


def _score_higher(value, bands):
    if value is None:
        return None
    for minimum, points in bands:
        if value >= minimum:
            return points
    return 10


def _ratio_score(value, reference):
    if value is None or reference is None or value <= 0 or reference <= 0:
        return None, None
    ratio = value / reference
    score = _score_lower(
        ratio,
        ((0.65, 100), (0.80, 90), (0.95, 75), (1.10, 60), (1.30, 45), (1.60, 25)),
    )
    return score, ratio


def _normalized_growth(info, profitable):
    earnings_growth = _number(info.get("earningsGrowth"))
    revenue_growth = _number(info.get("revenueGrowth"))
    candidates = []
    if profitable and earnings_growth is not None and 0.03 <= earnings_growth <= 0.60:
        candidates.append(("earningsGrowth", earnings_growth))
    if revenue_growth is not None and 0.03 <= revenue_growth <= 0.50:
        candidates.append(("revenueGrowth", revenue_growth))
    if not candidates:
        return None, None
    source, value = candidates[0]
    if len(candidates) == 2:
        source = "earningsGrowth + revenueGrowth"
        value = sum(candidate[1] for candidate in candidates) / 2
    return value, source


def _growth_adjusted_score(profitable, primary_multiple, growth):
    if primary_multiple is None or growth is None or growth <= 0:
        return None, None
    ratio = primary_multiple / (growth * 100)
    bands = (
        ((0.70, 100), (1.00, 85), (1.40, 70), (1.90, 55), (2.60, 35), (3.50, 20))
        if profitable
        else ((0.10, 100), (0.20, 85), (0.35, 70), (0.55, 50), (0.80, 30))
    )
    return _score_lower(ratio, bands), ratio


def _cashflow_score(fcf_yield):
    return _score_higher(
        fcf_yield,
        ((0.08, 100), (0.05, 85), (0.03, 70), (0.01, 45), (0.0, 25)),
    )


def _component(score, weight, detail, available=True):
    return {
        "score": round(score) if score is not None else None,
        "weight": weight,
        "available": bool(available and score is not None),
        "detail": detail,
    }


def _weighted_score(components):
    available = [item for item in components.values() if item.get("available")]
    coverage = sum(item["weight"] for item in available)
    if not coverage:
        return None, 0
    earned = sum(item["score"] * item["weight"] for item in available)
    return round(earned / coverage), coverage


def valuation_label(score):
    if score is None:
        return "INDISPONIBLE"
    if score >= 85:
        return "TRÈS ATTRACTIVE"
    if score >= 70:
        return "ATTRACTIVE"
    if score >= 55:
        return "RAISONNABLE"
    if score >= 40:
        return "UN PEU EXIGEANTE"
    return "PRIME ÉLEVÉE"


def historical_pe_context(company, info, price_history):
    """Build approximate historical P/E observations in listing units."""
    trailing_eps = _number(info.get("trailingEps"))
    if trailing_eps is None or trailing_eps <= 0 or price_history is None:
        return []
    try:
        annual_eps = company.income_stmt.loc["Diluted EPS"].dropna()
    except (AttributeError, KeyError, TypeError):
        return []
    annual_eps = [(period, _number(value)) for period, value in annual_eps.items()]
    annual_eps = [(period, value) for period, value in annual_eps if value and value > 0]
    if len(annual_eps) < 2:
        return []
    annual_eps.sort(key=lambda item: item[0], reverse=True)
    same_currency = (
        info.get("currency")
        and info.get("financialCurrency")
        and info.get("currency") == info.get("financialCurrency")
    )
    scale = 1.0 if same_currency else trailing_eps / annual_eps[0][1]
    if not 0.001 <= scale <= 100:
        return []
    samples = []
    for period, eps in annual_eps:
        target = period + timedelta(days=60)
        try:
            target_date = target.date()
            earliest_date = (target - timedelta(days=10)).date()
            eligible = price_history.loc[
                [
                    earliest_date <= market_date <= target_date
                    for market_date in price_history.index.date
                ]
            ]
            price = _number(eligible["Close"].iloc[-1])
        except (KeyError, IndexError, TypeError):
            continue
        normalized_eps = eps * scale
        if price and normalized_eps > 0:
            pe = price / normalized_eps
            if 1 <= pe <= 250:
                samples.append(
                    {
                        "fiscal_date": period.date().isoformat(),
                        "price_date_offset_days": 60,
                        "pe": round(pe, 2),
                    }
                )
    return samples


def collect_metrics(ticker, info, audit=None, historical_pe_samples=None, fx_rate=None):
    audit = audit or {}
    source_price = _number(audit.get("price"))
    forward_eps = _number(info.get("forwardEps"))
    calculated_forward_pe = (
        source_price / forward_eps
        if source_price and source_price > 0 and forward_eps and forward_eps > 0
        else None
    )
    reported_forward_pe = _number(info.get("forwardPE"))
    forward_pe = calculated_forward_pe or reported_forward_pe
    trailing_pe = _number(info.get("trailingPE"))
    price_to_sales = _number(info.get("priceToSalesTrailing12Months"))
    enterprise_to_revenue = _number(info.get("enterpriseToRevenue"))
    free_cashflow = _number(info.get("freeCashflow"))
    market_cap = _number(info.get("marketCap"))
    trading_currency = info.get("currency")
    financial_currency = info.get("financialCurrency")
    fcf_converted = free_cashflow
    if (
        free_cashflow is not None
        and trading_currency
        and financial_currency
        and trading_currency != financial_currency
    ):
        fcf_converted = free_cashflow * fx_rate if fx_rate else None
    fcf_yield = (
        fcf_converted / market_cap
        if fcf_converted is not None and market_cap not in (None, 0)
        else None
    )
    profitable = forward_pe is not None and forward_pe > 0
    primary_multiple = forward_pe if profitable else price_to_sales
    growth, growth_source = _normalized_growth(info, profitable)
    growth_score, growth_ratio = _growth_adjusted_score(profitable, primary_multiple, growth)
    historical_pe_samples = historical_pe_samples or []
    historical_median = (
        median(sample["pe"] for sample in historical_pe_samples)
        if historical_pe_samples
        else None
    )
    history_score, history_ratio = _ratio_score(forward_pe, historical_median)
    components = {
        "own_history": _component(
            history_score,
            40,
            (
                f"P/E forward {forward_pe:.1f}x / médiane historique {historical_median:.1f}x"
                if history_score is not None
                else "historique comparable insuffisant"
            ),
            len(historical_pe_samples) >= 2,
        ),
        "peers": _component(None, 25, "comparaison aux pairs en attente", False),
        "growth_adjusted": _component(
            growth_score,
            25,
            (
                f"multiple/croissance {growth_ratio:.2f} avec croissance normalisée {growth * 100:.1f}%"
                if growth_score is not None
                else "croissance normalisée indisponible"
            ),
            growth_score is not None,
        ),
        "cash_flow": _component(
            _cashflow_score(fcf_yield),
            10,
            (
                f"rendement FCF {fcf_yield * 100:.1f}%"
                if fcf_yield is not None
                else "rendement FCF indisponible ou devise non normalisée"
            ),
            fcf_yield is not None,
        ),
    }
    return {
        "ticker": ticker,
        "peer_group": PEER_GROUPS.get(ticker, "OTHER"),
        "method": "PROFITABLE" if profitable else "LOW_OR_NO_EARNINGS",
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
            "revenue_growth": _number(info.get("revenueGrowth")),
            "earnings_growth": _number(info.get("earningsGrowth")),
            "growth_rate_used": growth,
            "growth_source": growth_source,
            "price_to_sales": price_to_sales,
            "enterprise_to_revenue": enterprise_to_revenue,
            "fcf_yield": fcf_yield,
            "fcf_fx_rate": fx_rate,
            "historical_pe_median": historical_median,
            "historical_pe_ratio": history_ratio,
            "historical_pe_samples": historical_pe_samples,
            "peer_multiple": primary_multiple,
            "peer_multiple_name": "forward_pe" if profitable else "price_to_sales",
            "peg_status": "NOT_USED",
        },
        "components": components,
    }


def finalize_score(item, peer_items):
    metrics = item["metrics"]
    peer_values = [
        peer["metrics"].get("peer_multiple")
        for peer in peer_items
        if peer.get("ticker") != item.get("ticker")
        and peer.get("peer_group") == item.get("peer_group")
        and peer.get("method") == item.get("method")
        and peer["metrics"].get("peer_multiple") is not None
    ]
    peer_dispersion_ok = (
        len(peer_values) >= 2
        and min(peer_values) > 0
        and max(peer_values) / min(peer_values) <= 8
    )
    peer_median = median(peer_values) if peer_dispersion_ok else None
    peer_score, peer_ratio = _ratio_score(metrics.get("peer_multiple"), peer_median)
    item["components"]["peers"] = _component(
        peer_score,
        25,
        (
            f"multiple {metrics.get('peer_multiple'):.1f}x / médiane des pairs {peer_median:.1f}x"
            if peer_score is not None
            else "pairs insuffisants ou trop dispersés"
        ),
        peer_score is not None,
    )
    metrics["peer_median"] = peer_median
    metrics["peer_ratio"] = peer_ratio
    metrics["peer_count"] = len(peer_values)
    score, coverage = _weighted_score(item["components"])
    risk_flags = []
    growth = metrics.get("growth_rate_used")
    if item["method"] == "PROFITABLE":
        if metrics.get("forward_pe") and metrics["forward_pe"] >= 60 and (
            growth is None or growth < 0.30
        ):
            score = min(score, 39) if score is not None else score
            risk_flags.append("P/E forward extrême sans croissance suffisante")
    elif metrics.get("price_to_sales") and metrics["price_to_sales"] >= 25 and (
        growth is None or growth < 0.40
    ):
        score = min(score, 35) if score is not None else score
        risk_flags.append("P/S extrême sans croissance suffisante")
    if item.get("ticker") in CYCLICAL_MEMORY_TICKERS and growth is None:
        score = min(score, 69) if score is not None else score
        risk_flags.append(
            "multiple cyclique de la mémoire non interprétable sans croissance normalisée"
        )
    if coverage < 25:
        score = None
        risk_flags.append("couverture insuffisante pour conclure")
    item["score"] = score
    item["label"] = valuation_label(score)
    item["coverage_pct"] = coverage
    item["confidence"] = "HIGH" if coverage >= 80 else "MEDIUM" if coverage >= 55 else "LOW"
    item["risk_flags"] = risk_flags
    return item


def score_valuation(
    ticker,
    info,
    audit=None,
    historical_pe_samples=None,
    fx_rate=None,
    peer_items=None,
):
    item = collect_metrics(
        ticker,
        info,
        audit,
        historical_pe_samples=historical_pe_samples,
        fx_rate=fx_rate,
    )
    return finalize_score(item, peer_items or [item])


def _fx_rate(financial_currency, trading_currency, cache):
    if not financial_currency or not trading_currency:
        return None
    if financial_currency == trading_currency:
        return 1.0
    pair = f"{financial_currency}{trading_currency}=X"
    if pair not in cache:
        try:
            frame = yf.Ticker(pair).history(period="5d", auto_adjust=False)
            cache[pair] = _number(frame["Close"].dropna().iloc[-1]) if not frame.empty else None
        except Exception:
            cache[pair] = None
    return cache[pair]


def build_valuations(tickers):
    raw_items = []
    unavailable = []
    fx_cache = {}
    for ticker in tickers:
        try:
            company = yf.Ticker(ticker)
            info = company.info or {}
            history = company.history(period="5y", auto_adjust=True)
            audit = {}
            if not history.empty:
                audit = {
                    "price": float(history["Close"].dropna().iloc[-1]),
                    "price_date": history.index[-1].date().isoformat(),
                }
            historical_samples = historical_pe_context(company, info, history)
            fx_rate = _fx_rate(
                info.get("financialCurrency"), info.get("currency"), fx_cache
            )
            raw_items.append(
                collect_metrics(
                    ticker,
                    info,
                    audit,
                    historical_pe_samples=historical_samples,
                    fx_rate=fx_rate,
                )
            )
        except Exception as error:
            unavailable.append({"ticker": ticker, "reason": str(error)})
    items = [finalize_score(item, raw_items) for item in raw_items]
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "method": "valuation_v3_relative",
        "methodology": {
            "own_history_weight": 40,
            "peer_comparison_weight": 25,
            "growth_adjusted_weight": 25,
            "cash_flow_weight": 10,
            "note": "Le score est normalisé sur les critères disponibles. La couverture indique la part du modèle effectivement calculée.",
        },
        "items": items,
        "unavailable": unavailable,
    }


def main():
    output = build_valuations(WATCHLIST)
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
