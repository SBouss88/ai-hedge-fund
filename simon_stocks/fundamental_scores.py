import yfinance as yf
from config import WATCHLIST


def score_pe(value):
    if value is None or value <= 0:
        return None
    if value <= 15:
        return 5.0
    if value <= 25:
        return 4.0
    if value <= 35:
        return 3.0
    if value <= 45:
        return 2.0
    if value <= 60:
        return 1.0
    return 0.0


def score_margin(value):
    if value is None:
        return None
    if value >= 0.30:
        return 5.0
    if value >= 0.20:
        return 4.0
    if value >= 0.10:
        return 3.0
    if value >= 0.05:
        return 2.0
    if value >= 0:
        return 1.0
    return 0.0


def score_roe(value):
    if value is None:
        return None
    if value >= 0.30:
        return 5.0
    if value >= 0.20:
        return 4.0
    if value >= 0.10:
        return 3.0
    if value >= 0.05:
        return 2.0
    if value >= 0:
        return 1.0
    return 0.0


def score_debt(value):
    if value is None:
        return None
    if value <= 30:
        return 5.0
    if value <= 60:
        return 4.0
    if value <= 100:
        return 3.0
    if value <= 150:
        return 2.0
    return 1.0


def score_growth(value):
    if value is None:
        return None
    if value >= 0.30:
        return 5.0
    if value >= 0.15:
        return 4.0
    if value >= 0.05:
        return 3.0
    if value >= 0:
        return 2.0
    return 1.0


def average(values):
    valid = [v for v in values if v is not None]
    return sum(valid) / len(valid) if valid else None


print("\nSIMON AI STOCK WATCHLIST - FUNDAMENTAL SCORES\n")

for ticker in WATCHLIST:
    info = yf.Ticker(ticker).info

    trailing_pe = info.get("trailingPE")
    forward_pe = info.get("forwardPE")
    profit_margin = info.get("profitMargins")
    revenue_growth = info.get("revenueGrowth")
    earnings_growth = info.get("earningsGrowth")
    roe = info.get("returnOnEquity")
    debt_to_equity = info.get("debtToEquity")
    free_cashflow = info.get("freeCashflow")
    total_revenue = info.get("totalRevenue")

    fcf_margin = (
        free_cashflow / total_revenue
        if free_cashflow is not None and total_revenue not in (None, 0)
        else None
    )

    pe_scores = [score_pe(trailing_pe), score_pe(forward_pe)]
    valuation = average(pe_scores)

    quality = average([
        score_margin(profit_margin),
        score_margin(fcf_margin),
        score_roe(roe),
        score_debt(debt_to_equity),
    ])

    growth = average([
        score_growth(revenue_growth),
        score_growth(earnings_growth),
    ])

    flags = []
    if forward_pe is not None and forward_pe <= 0:
        flags.append("negative forward P/E")
    if fcf_margin is not None and (fcf_margin < -1 or fcf_margin > 1):
        flags.append("extreme FCF margin")
    if revenue_growth is not None and abs(revenue_growth) > 2:
        flags.append("extreme revenue growth")
    if earnings_growth is not None and abs(earnings_growth) > 5:
        flags.append("extreme earnings growth")
    if roe is not None and abs(roe) > 1:
        flags.append("extreme ROE")

    confidence = "HIGH" if len(flags) == 0 else "MEDIUM" if len(flags) == 1 else "LOW"

    if growth is not None and (revenue_growth is None or earnings_growth is None):
        growth = min(growth, 3.5)
    if growth is not None and ("extreme revenue growth" in flags or "extreme earnings growth" in flags):
        growth = min(growth, 4.0)

    fundamental = None
    if valuation is not None and quality is not None and growth is not None:
        fundamental = 0.30 * valuation + 0.35 * quality + 0.35 * growth

    print(ticker)
    print(f"  Valuation: {valuation:.1f}/5" if valuation is not None else "  Valuation: N/A")
    print(f"  Quality:   {quality:.1f}/5" if quality is not None else "  Quality:   N/A")
    print(f"  Growth:    {growth:.1f}/5" if growth is not None else "  Growth:    N/A")
    print(f"  Fundamental: {fundamental:.1f}/5" if fundamental is not None else "  Fundamental: N/A")
    print(f"  Data confidence: {confidence}")
    if flags: print(f"  Flags: {', '.join(flags)}")
    print()
