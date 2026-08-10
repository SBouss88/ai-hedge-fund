import yfinance as yf
from config import WATCHLIST

def rsi(s, n=14):
    d = s.diff()
    g = d.clip(lower=0).rolling(n).mean()
    l = (-d.clip(upper=0)).rolling(n).mean()
    return 100 - 100 / (1 + g / l)

print("\nSIMON AI STOCK WATCHLIST - TIMING\n")

for t in WATCHLIST:
    d = yf.Ticker(t).history(period="1y", auto_adjust=True)
    c = d["Close"]
    p = c.iloc[-1]
    s50 = c.rolling(50).mean().iloc[-1]
    s200 = c.rolling(200).mean().iloc[-1]
    r = rsi(c).iloc[-1]
    d50 = (p / s50 - 1) * 100
    d200 = (p / s200 - 1) * 100

    if r >= 70:
        timing = "OVERHEATED - DO NOT CHASE"
    elif p > s50 > s200:
        timing = "POSITIVE MOMENTUM"
    elif p > s200 and p < s50:
        timing = "WATCH - PULLBACK"
    elif p < s200:
        timing = "CAUTION"
    else:
        timing = "MIXED"

    print(f"{t}: ${p:.2f}")
    print(f"  vs SMA50: {d50:+.1f}% | vs SMA200: {d200:+.1f}% | RSI: {r:.1f}")
    print(f"  TIMING: {timing}\n")
