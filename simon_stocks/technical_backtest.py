import pandas as pd
import yfinance as yf

from config import WATCHLIST


def rsi(s, n=14):
    d = s.diff()
    g = d.clip(lower=0).rolling(n).mean()
    l = (-d.clip(upper=0)).rolling(n).mean()
    return 100 - 100 / (1 + g / l)


def classify(row):
    p = row["Close"]
    s50 = row["SMA50"]
    s200 = row["SMA200"]
    r = row["RSI"]

    if r >= 70:
        return "OVERHEATED"
    elif p > s50 > s200:
        return "POSITIVE MOMENTUM"
    elif p > s200 and p < s50:
        return "WATCH - PULLBACK"
    elif p < s200:
        return "CAUTION"
    else:
        return "MIXED"


print("\nTECHNICAL BACKTEST - 5 YEARS\n")

all_results = []

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

    # On compte uniquement l'apparition d'un nouveau signal
    df["NewSignal"] = df["Signal"] != df["Signal"].shift(1)
    events = df[df["NewSignal"]].copy()

    for days in (5, 20, 60):
        df[f"Return_{days}d"] = (
            df["Close"].shift(-days) / df["Close"] - 1
        ) * 100

        events[f"Return_{days}d"] = df.loc[
            events.index, f"Return_{days}d"
        ]

    print(f"\n{ticker}")
    print("-" * len(ticker))

    for signal, group in events.groupby("Signal"):
        row = {"Ticker": ticker, "Signal": signal, "N": len(group)}

        text = f"{signal:20} | N={len(group):3d}"

        for days in (5, 20, 60):
            values = group[f"Return_{days}d"].dropna()

            if len(values):
                avg = values.mean()
                positive = (values > 0).mean() * 100

                row[f"Avg_{days}d"] = avg
                row[f"Positive_{days}d"] = positive

                text += (
                    f" | {days}j: {avg:+5.1f}% "
                    f"({positive:4.0f}% positif)"
                )

        print(text)
        all_results.append(row)

results = pd.DataFrame(all_results)

print("\n\n========== GLOBAL ==========")

for signal, group in results.groupby("Signal"):
    print(f"\n{signal}")

    total_n = group["N"].sum()
    print(f"  Occurrences: {total_n}")

    for days in (5, 20, 60):
        avg_col = f"Avg_{days}d"
        pos_col = f"Positive_{days}d"

        valid = group.dropna(subset=[avg_col])

        if not valid.empty:
            weighted_avg = (
                valid[avg_col] * valid["N"]
            ).sum() / valid["N"].sum()

            weighted_positive = (
                valid[pos_col] * valid["N"]
            ).sum() / valid["N"].sum()

            print(
                f"  {days} jours: rendement moyen "
                f"{weighted_avg:+.1f}% | "
                f"{weighted_positive:.0f}% positifs"
            )
