import pandas as pd
import yfinance as yf

from config import WATCHLIST


def rsi(s, n=14):
    d = s.diff()
    gains = d.clip(lower=0).rolling(n).mean()
    losses = (-d.clip(upper=0)).rolling(n).mean()
    return 100 - 100 / (1 + gains / losses)


def classify(row):
    p = row["Close"]
    sma50 = row["SMA50"]
    sma200 = row["SMA200"]
    r = row["RSI"]

    if r >= 70:
        return "OVERHEATED"
    elif p > sma50 > sma200:
        return "POSITIVE MOMENTUM"
    elif p > sma200 and p < sma50:
        return "WATCH - PULLBACK"
    elif p < sma200:
        return "CAUTION"
    else:
        return "MIXED"


HORIZONS = (5, 10, 20)

print("\nTECHNICAL BACKTEST V3 - QUALITY OF ENTRY\n")

for ticker in WATCHLIST:
    df = yf.Ticker(ticker).history(period="5y", auto_adjust=True)

    if df.empty:
        continue

    df = df[["Close"]].copy()
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()
    df["RSI"] = rsi(df["Close"])
    df = df.dropna().copy()

    df["Signal"] = df.apply(classify, axis=1)
    df["NewSignal"] = df["Signal"] != df["Signal"].shift(1)

    for days in HORIZONS:
        future_prices = pd.concat(
            [df["Close"].shift(-i) for i in range(1, days + 1)],
            axis=1,
        )

        future_min = future_prices.min(axis=1)
        future_min[future_prices.count(axis=1) < days] = float("nan")

        df[f"BestDiscount_{days}d"] = (
            future_min / df["Close"] - 1
        ) * 100

    events = df[df["NewSignal"]].copy()

    print(f"\n{'=' * 60}")
    print(ticker)
    print(f"{'=' * 60}")

    print("\nJOURNÉE NORMALE")
    for days in HORIZONS:
        values = df[f"BestDiscount_{days}d"].dropna()

        print(
            f"{days:2d}j | meilleur prix moyen {values.mean():+5.1f}% | "
            f"médiane {values.median():+5.1f}% | "
            f"≥3% moins cher {(values <= -3).mean()*100:4.0f}% | "
            f"≥5% moins cher {(values <= -5).mean()*100:4.0f}%"
        )

    print("\nAPRÈS APPARITION D'UN SIGNAL")

    for signal, group in events.groupby("Signal"):
        print(f"\n{signal}")

        for days in HORIZONS:
            values = group[f"BestDiscount_{days}d"].dropna()

            if values.empty:
                continue

            print(
                f"  {days:2d}j | meilleur prix moyen {values.mean():+5.1f}% | "
                f"médiane {values.median():+5.1f}% | "
                f"≥3% moins cher {(values <= -3).mean()*100:4.0f}% | "
                f"≥5% moins cher {(values <= -5).mean()*100:4.0f}% | "
                f"N={len(values)}"
            )
