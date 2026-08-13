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


HORIZONS = (5, 20, 60)

print("\nTECHNICAL BACKTEST V2 - SIGNAL VS NORMAL BEHAVIOUR\n")

for ticker in WATCHLIST:
    df = yf.Ticker(ticker).history(period="5y", auto_adjust=True)

    if df.empty:
        print(f"{ticker}: no data")
        continue

    df = df[["Close"]].copy()
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()
    df["RSI"] = rsi(df["Close"])
    df = df.dropna().copy()

    df["Signal"] = df.apply(classify, axis=1)
    df["NewSignal"] = df["Signal"] != df["Signal"].shift(1)

    for days in HORIZONS:
        df[f"Return_{days}d"] = (
            df["Close"].shift(-days) / df["Close"] - 1
        ) * 100

    events = df[df["NewSignal"]].copy()

    print(f"\n{'=' * 60}")
    print(ticker)
    print(f"{'=' * 60}")

    baselines = {}

    print("\nCOMPORTEMENT NORMAL")
    for days in HORIZONS:
        values = df[f"Return_{days}d"].dropna()

        mean = values.mean()
        median = values.median()
        positive = (values > 0).mean() * 100

        baselines[days] = mean

        print(
            f"{days:2d}j | moyenne {mean:+6.1f}% | "
            f"médiane {median:+6.1f}% | "
            f"{positive:4.0f}% positifs | N={len(values)}"
        )

    print("\nAPRÈS APPARITION D'UN SIGNAL")

    for signal, group in events.groupby("Signal"):
        print(f"\n{signal}")

        for days in HORIZONS:
            values = group[f"Return_{days}d"].dropna()

            if values.empty:
                continue

            mean = values.mean()
            median = values.median()
            positive = (values > 0).mean() * 100
            excess = mean - baselines[days]

            print(
                f"  {days:2d}j | moyenne {mean:+6.1f}% | "
                f"médiane {median:+6.1f}% | "
                f"{positive:4.0f}% positifs | "
                f"vs normal {excess:+6.1f} pts | "
                f"N={len(values)}"
            )
