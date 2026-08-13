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


WAIT_DAYS = 20
FINAL_DAYS = 60

print("\nBACKTEST V5 - COMPARAISON DES STRATEGIES D'ENTREE\n")

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

        if pos + FINAL_DAYS >= len(df):
            continue

        signal = df["Signal"].iloc[pos]
        start_price = df["Close"].iloc[pos]
        final_price = df["Close"].iloc[pos + FINAL_DAYS]

        wait_window = df.iloc[pos + 1:pos + 1 + WAIT_DAYS]

        # A - 100% maintenant
        shares_a = 1 / start_price
        value_a = shares_a * final_price
        return_a = (value_a - 1) * 100

        # B - 100% si -3%, sinon achat au jour 20
        target_3 = start_price * 0.97
        hits_3 = wait_window["Low"] <= target_3

        if hits_3.any():
            buy_price_b = target_3
        else:
            buy_price_b = df["Close"].iloc[pos + WAIT_DAYS]

        shares_b = 1 / buy_price_b
        value_b = shares_b * final_price
        return_b = (value_b - 1) * 100

        # C - 50% maintenant, 25% à -3%, 25% à -5%
        shares_c = 0.50 / start_price
        remaining_cash = 0.50

        target_5 = start_price * 0.95
        hits_5 = wait_window["Low"] <= target_5

        if hits_3.any():
            shares_c += 0.25 / target_3
            remaining_cash -= 0.25

        if hits_5.any():
            shares_c += 0.25 / target_5
            remaining_cash -= 0.25

        # Le cash restant est investi au bout de 20 séances
        if remaining_cash > 0:
            fallback_price = df["Close"].iloc[pos + WAIT_DAYS]
            shares_c += remaining_cash / fallback_price

        value_c = shares_c * final_price
        return_c = (value_c - 1) * 100

        records.append({
            "Signal": signal,
            "BuyNow": return_a,
            "Wait3": return_b,
            "Progressive": return_c,
        })

    results = pd.DataFrame(records)

    print("\n" + "=" * 70)
    print(ticker)
    print("=" * 70)

    for signal, group in results.groupby("Signal"):
        n = len(group)

        avg_a = group["BuyNow"].mean()
        avg_b = group["Wait3"].mean()
        avg_c = group["Progressive"].mean()

        med_a = group["BuyNow"].median()
        med_b = group["Wait3"].median()
        med_c = group["Progressive"].median()

        win_b = (group["Wait3"] > group["BuyNow"]).mean() * 100
        win_c = (group["Progressive"] > group["BuyNow"]).mean() * 100

        best = {
            "TOUT MAINTENANT": avg_a,
            "ATTENDRE -3%": avg_b,
            "PROGRESSIF": avg_c,
        }
        winner = max(best, key=best.get)

        print(f"\n{signal} | N={n}")
        print(
            f"  Tout maintenant : moyenne {avg_a:+6.1f}% | "
            f"médiane {med_a:+6.1f}%"
        )
        print(
            f"  Attendre -3%    : moyenne {avg_b:+6.1f}% | "
            f"médiane {med_b:+6.1f}% | "
            f"bat achat immédiat {win_b:4.0f}% du temps"
        )
        print(
            f"  Progressif      : moyenne {avg_c:+6.1f}% | "
            f"médiane {med_c:+6.1f}% | "
            f"bat achat immédiat {win_c:4.0f}% du temps"
        )
        print(f"  >>> MEILLEURE MOYENNE : {winner}")
