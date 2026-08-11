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


def swing_levels(df, lookback=90, window=2):
    recent = df.tail(lookback).reset_index(drop=True)
    lows, highs = [], []

    for i in range(window, len(recent) - window):
        low = float(recent.loc[i, "Low"])
        high = float(recent.loc[i, "High"])
        low_window = recent.loc[i-window:i+window, "Low"]
        high_window = recent.loc[i-window:i+window, "High"]

        if low <= float(low_window.min()):
            lows.append(low)
        if high >= float(high_window.max()):
            highs.append(high)

    return lows, highs


def cluster_levels(levels, tolerance):
    if not levels:
        return []

    levels = sorted(levels)
    clusters = [[levels[0]]]

    for level in levels[1:]:
        mean = sum(clusters[-1]) / len(clusters[-1])
        if abs(level - mean) <= tolerance:
            clusters[-1].append(level)
        else:
            clusters.append([level])

    return [
        {"level": sum(c) / len(c), "touches": len(c)}
        for c in clusters
    ]


def closest_level(clusters, price, side):
    if side == "below":
        candidates = [c for c in clusters if c["level"] < price]
        return max(candidates, key=lambda x: x["level"], default=None)
    candidates = [c for c in clusters if c["level"] > price]
    return min(candidates, key=lambda x: x["level"], default=None)


def strength(touches):
    if touches >= 3:
        return "STRONG"
    if touches == 2:
        return "MEDIUM"
    return "WEAK"


def make_zone(cluster, atr_value):
    if not cluster:
        return None
    half = 0.25 * atr_value
    return {
        "low": cluster["level"] - half,
        "high": cluster["level"] + half,
        "center": cluster["level"],
        "touches": cluster["touches"],
        "strength": strength(cluster["touches"]),
    }


def overlaps(a, b):
    if not a or not b:
        return False
    return max(a["low"], b["low"]) <= min(a["high"], b["high"])


def merge_pivot(a, b):
    touches = a["touches"] + b["touches"]
    return {
        "low": min(a["low"], b["low"]),
        "high": max(a["high"], b["high"]),
        "center": (a["center"] + b["center"]) / 2,
        "touches": touches,
        "strength": strength(touches),
    }



def confluence(zone, sma50, sma200):
    if not zone:
        return []
    labels = []
    margin = 0.10 * (zone["high"] - zone["low"])
    if zone["low"] - margin <= sma50 <= zone["high"] + margin:
        labels.append("SMA50")
    if zone["low"] - margin <= sma200 <= zone["high"] + margin:
        labels.append("SMA200")
    return labels


def distance_pct(price, level):
    return abs(price / level - 1) * 100


print("\nSIMON AI STOCK WATCHLIST - ENTRY ZONES V2\n")

for ticker in WATCHLIST:
    df = yf.Ticker(ticker).history(period="1y", auto_adjust=True)

    if df.empty or len(df) < 200:
        print(f"{ticker}: insufficient data\n")
        continue

    close = df["Close"]
    price = float(close.iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1])
    sma200 = float(close.rolling(200).mean().iloc[-1])
    rsi14 = float(rsi(close).iloc[-1])
    atr14 = float(atr(df).iloc[-1])

    lows, highs = swing_levels(df)
    tolerance = max(0.35 * atr14, 0.01 * price)

    low_clusters = cluster_levels(lows, tolerance)
    high_clusters = cluster_levels(highs, tolerance)

    support = make_zone(closest_level(low_clusters, price, "below"), atr14)
    resistance = make_zone(closest_level(high_clusters, price, "above"), atr14)
    pivot = merge_pivot(support, resistance) if overlaps(support, resistance) else None

    print(ticker)
    print(f"  Price: ${price:.2f}")
    print(f"  RSI14: {rsi14:.1f}")
    print(f"  ATR14: ${atr14:.2f} ({atr14/price*100:.1f}%)")
    print(f"  SMA50: ${sma50:.2f} ({(price/sma50-1)*100:+.1f}% vs SMA50)")
    print(f"  SMA200: ${sma200:.2f} ({(price/sma200-1)*100:+.1f}% vs SMA200)")

    if pivot:
        conf = confluence(pivot, sma50, sma200)
        dist = distance_pct(price, pivot["center"])
        conf_text = ", ".join(conf) if conf else "none"
        print(
            f"  DECISION ZONE: ${pivot['low']:.2f} - ${pivot['high']:.2f} "
            f"({pivot['strength']}, {pivot['touches']} combined touches, "
            f"{dist:.1f}% away)"
        )
        print(f"  Confluence: {conf_text}")
    else:
        if support:
            conf = confluence(support, sma50, sma200)
            dist = distance_pct(price, support["center"])
            label = "NEARBY" if dist <= 8 else "DISTANT"
            conf_text = ", ".join(conf) if conf else "none"
            print(
                f"  Support: ${support['low']:.2f} - ${support['high']:.2f} "
                f"({support['strength']}, {support['touches']} touches, "
                f"{dist:.1f}% away, {label})"
            )
            print(f"  Support confluence: {conf_text}")
        else:
            print("  Support: N/A")

    if not pivot:
        if resistance:
            conf = confluence(resistance, sma50, sma200)
            dist = distance_pct(price, resistance["center"])
            label = "NEARBY" if dist <= 8 else "DISTANT"
            conf_text = ", ".join(conf) if conf else "none"
            print(
                f"  Resistance: ${resistance['low']:.2f} - ${resistance['high']:.2f} "
                f"({resistance['strength']}, {resistance['touches']} touches, "
                f"{dist:.1f}% away, {label})"
            )
            print(f"  Resistance confluence: {conf_text}")
        else:
            print("  Resistance: N/A")

    if rsi14 >= 70:
        setup = "EXTENDED - WAIT FOR COOLING"
    elif pivot and pivot["low"] <= price <= pivot["high"]:
        setup = "IN DECISION ZONE - WAIT FOR BREAK / RECLAIM"
    elif price < sma50 and price > sma200:
        setup = "PULLBACK - WATCH SUPPORT / SMA50 RECLAIM"
    elif price > sma50 > sma200 and rsi14 < 70:
        setup = "UPTREND - WATCH SUPPORT ON PULLBACK"
    elif price < sma200:
        setup = "CAUTION - BELOW LONG-TERM TREND"
    else:
        setup = "MIXED - WAIT FOR CONFIRMATION"

    print(f"  SETUP: {setup}\n")

print("V2 zones are heuristic research levels, not automatic buy/sell prices.")
