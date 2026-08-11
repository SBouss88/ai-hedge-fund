import yfinance as yf
import pandas as pd

from config import WATCHLIST


def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(df, period=14):
    prev = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev).abs(),
        (df["Low"] - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

print("\nSIMON AI STOCK WATCHLIST - TECHNICAL LEVELS\n")

for ticker in WATCHLIST:
    df = yf.Ticker(ticker).history(period="1y", auto_adjust=True)
    if df.empty or len(df) < 200:
        print(f"{ticker}: insufficient data\n")
        continue

    close = data_close = df["Close"]
    price = float(close.iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1])
    sma200 = float(close.rolling(200).mean().iloc[-1])
    rsi14 = float(rsi(close).iloc[-1])
    atr14 = float(atr(df).iloc[-1])

    low20 = float(df["Low"].tail(20).min())
    high20 = float(df["High"].tail(20).max())
    low60 = float(df["Low"].tail(60).min())
    high60 = float(df["High"].tail(60).max())

    print(ticker)
    print(f"  Price:   ${price:.2f}")
    print(f"  SMA50:   ${sma50:.2f}")
    print(f"  SMA200:  ${sma200:.2f}")
    print(f"  RSI14:   {rsi14:.1f}")
    print(f"  ATR14:   ${atr14:.2f} ({atr14/price*100:.1f}% of price)")
    print(f"  20d low/high:  ${low20:.2f} / ${high20:.2f}")
    print(f"  60d low/high:  ${low60:.2f} / ${high60:.2f}\n")
