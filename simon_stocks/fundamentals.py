import yfinance as yf
from config import WATCHLIST


def pct(value):
    return "N/A" if value is None else f"{value * 100:.1f}%"


def num(value):
    return "N/A" if value is None else f"{value:.1f}"


print("\nSIMON AI STOCK WATCHLIST - FUNDAMENTALS\n")

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

    print(ticker)
    print(f"  P/E: {num(trailing_pe)} | Forward P/E: {num(forward_pe)}")
    print(
        f"  Profit margin: {pct(profit_margin)} | ROE: {pct(roe)} | "
        f"FCF margin: {pct(fcf_margin)}"
    )
    print(
        f"  Revenue growth: {pct(revenue_growth)} | "
        f"Earnings growth: {pct(earnings_growth)}"
    )
    print(
        f"  Debt/Equity: "
        f"{'N/A' if debt_to_equity is None else f'{debt_to_equity:.1f}%'}"
    )
    warnings=[]
    if forward_pe is not None and forward_pe <= 0: warnings.append("negative forward P/E")
    if fcf_margin is not None and (fcf_margin < -1 or fcf_margin > 1): warnings.append("extreme FCF margin")
    if revenue_growth is not None and abs(revenue_growth) > 2: warnings.append("extreme revenue growth")
    if earnings_growth is not None and abs(earnings_growth) > 5: warnings.append("extreme earnings growth")
    if roe is not None and abs(roe) > 1: warnings.append("extreme ROE")
    print(f"  DATA FLAGS: {", ".join(warnings) if warnings else "none"}")
    print()
