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


HORIZONS = (10, 20)
TARGETS = (3, 5)

print("\nBACKTEST V4 - ACHETER MAINTENANT OU ATTENDRE ?\n")

for ticker in WATCHLIST:
    df = yf.Ticker(ticker).history(period="5y", auto_adjust=True)

    if df.empty:
        continue

    df = df[["Close", "Low"]].copy()
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()
    df["RSI"] = rsi(df["Close"])
    df = df.dropna().copy()

    df["Signal"] = df.apply(classify, axis=1)
    df["NewSignal"] = df["Signal"] != df["Signal"].shift(1)

    records = []

    for pos in range(len(df)):
        if not df["NewSignal"].iloc[pos]:
            continue

        signal = df["Signal"].iloc[pos]
        price = df["Close"].iloc[pos]

        for horizon in HORIZONS:
            future = df.iloc[pos + 1:pos + 1 + horizon]

            if len(future) < horizon:
                continue

            end_return = (
                future["Close"].iloc[-1] / price - 1
            ) * 100

            for target in TARGETS:
                target_price = price * (1 - target / 100)
                hits = future["Low"] <= target_price

                if hits.any():
                    days_to_hit = list(hits).index(True) + 1
                    hit = True
                else:
                    days_to_hit = None
                    hit = False

                records.append({
                    "Signal": signal,
                    "Horizon": horizon,
                    "Target": target,
                    "Hit": hit,
                    "DaysToHit": days_to_hit,
                    "ReturnIfMissed": end_return if not hit else None,
                })

    results = pd.DataFrame(records)

    print("\n" + "=" * 65)
    print(ticker)
    print("=" * 65)

    for signal in sorted(results["Signal"].unique()):
        print(f"\n{signal}")

        subset_signal = results[results["Signal"] == signal]

        for horizon in HORIZONS:
            for target in TARGETS:
                g = subset_signal[
                    (subset_signal["Horizon"] == horizon)
                    & (subset_signal["Target"] == target)
                ]

                if g.empty:
                    continue

                hit_rate = g["Hit"].mean() * 100

                hit_days = g.loc[g["Hit"], "DaysToHit"]
                avg_days = hit_days.mean() if not hit_days.empty else float("nan")

                missed = g.loc[
                    ~g["Hit"], "ReturnIfMissed"
                ].dropna()

                if missed.empty:
                    missed_text = "aucun cas manqué"
                else:
                    missed_text = (
                        f"si non atteint: cours après {horizon}j "
                        f"{missed.mean():+5.1f}% en moyenne "
                        f"(médiane {missed.median():+5.1f}%)"
                    )

                print(
                    f"  attendre -{target}% pendant {horizon:2d}j | "
                    f"atteint {hit_rate:4.0f}% | "
                    f"délai moyen {avg_days:4.1f}j | "
                    f"{missed_text} | N={len(g)}"
                )
