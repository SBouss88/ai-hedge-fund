import json
from datetime import datetime
from pathlib import Path

import yfinance as yf

from config import WATCHLIST


HERE = Path(__file__).resolve().parent
OUTPUT_PATH = HERE / "history" / "quick_rankings_latest.json"


def rsi(series, period=14):
    delta = series.diff()
    gains = delta.clip(lower=0).rolling(period).mean()
    losses = (-delta.clip(upper=0)).rolling(period).mean()
    relative_strength = gains / losses
    return 100 - 100 / (1 + relative_strength)


def confirmed_swing_lows(frame, lookback=90, window=3):
    start = max(0, len(frame) - lookback)
    recent = frame.iloc[start:].reset_index(drop=True)
    lows = []
    for index in range(window, len(recent) - window):
        value = float(recent.loc[index, "Low"])
        local_window = recent.loc[index - window:index + window, "Low"]
        if value <= float(local_window.min()):
            lows.append({"position": start + index, "value": value})
    return lows


def higher_low_context(frame):
    lows = confirmed_swing_lows(frame)
    if len(lows) < 2:
        return {
            "score": 0,
            "detail": "Higher low : données insuffisantes",
            "change": None,
            "age": None,
            "distance": None,
            "position": None,
        }

    latest = lows[-1]
    previous = lows[-2]
    change = (latest["value"] / previous["value"] - 1) * 100
    age = len(frame) - 1 - latest["position"]
    current_close = float(frame["Close"].iloc[-1])
    distance = (current_close / latest["value"] - 1) * 100
    if change >= 2:
        score, detail = 15, f"Higher low +{change:.1f}%"
    elif change >= 0.5:
        score, detail = 12, f"Creux ascendant +{change:.1f}%"
    elif change >= -0.5:
        score, detail = 5, f"Creux stable {change:+.1f}%"
    else:
        score, detail = 0, f"Creux descendant {change:.1f}%"
    return {
        "score": score,
        "detail": detail,
        "change": change,
        "age": age,
        "distance": distance,
        "position": latest["position"],
    }


def trend_structure_score(frame, higher_low, sma200):
    price = float(frame["Close"].iloc[-1])
    above_sma200 = price >= sma200
    score = (10 if above_sma200 else 0) + higher_low["score"]
    trend_detail = "au-dessus SMA200" if above_sma200 else "sous SMA200"
    return score, f"{higher_low['detail']} · {trend_detail}"


def breakout_trigger(frame):
    last_position = len(frame) - 1
    recent_breakout = None

    for position in range(max(20, last_position - 2), last_position + 1):
        level = float(frame["High"].iloc[position - 20:position].max())
        close = float(frame["Close"].iloc[position])
        if close > level:
            recent_breakout = {
                "position": position,
                "age": last_position - position,
                "level": level,
            }

    current_close = float(frame["Close"].iloc[-1])
    if recent_breakout:
        age = recent_breakout["age"]
        level = recent_breakout["level"]
        distance = (current_close / level - 1) * 100

        if age == 0:
            if distance <= 2:
                return 20, f"Breakout aujourd’hui +{distance:.1f}%", recent_breakout
            return 12, f"Breakout aujourd’hui déjà à +{distance:.1f}%", recent_breakout

        if age == 1:
            if 0 <= distance <= 2:
                return 15, f"Breakout hier, encore proche +{distance:.1f}%", recent_breakout
            if distance < 0:
                return 0, "Breakout d’hier non conservé", recent_breakout
            return 8, f"Breakout d’hier déjà à +{distance:.1f}%", recent_breakout

        current_low = float(frame["Low"].iloc[-1])
        successful_retest = current_low <= level * 1.005 and current_close >= level
        if successful_retest:
            return 12, "Breakout J-2 avec retest réussi", recent_breakout
        return 0, "Breakout J-2 sans retest exploitable", recent_breakout

    current_level = float(frame["High"].iloc[-21:-1].max())
    distance = (current_close / current_level - 1) * 100
    if -0.5 <= distance < 0:
        return 5, f"À {abs(distance):.1f}% du breakout", None
    return 0, f"Sous le breakout de {abs(distance):.1f}%", None


def higher_low_trigger(frame, higher_low):
    age = higher_low.get("age")
    distance = higher_low.get("distance")
    if higher_low.get("score", 0) < 12 or age is None or distance is None:
        return 0, "Pas de higher low exploitable"
    if distance < 0:
        return 0, f"Higher low non conservé ({distance:.1f}% sous le creux)"

    current_close = float(frame["Close"].iloc[-1])
    previous_close = float(frame["Close"].iloc[-2])
    if age <= 10 and distance <= 5 and current_close > previous_close:
        return 15, f"Rebond confirmé sur higher low (+{distance:.1f}% du creux)"
    if age <= 15 and distance <= 7:
        return 12, f"Stabilisation sur higher low (+{distance:.1f}% du creux)"
    if age <= 20 and distance <= 10:
        return 7, f"Higher low récent, rebond à confirmer (+{distance:.1f}%)"
    return 0, "Higher low trop ancien ou prix déjà éloigné"


def trigger_score(frame, higher_low):
    breakout_points, breakout_detail, breakout = breakout_trigger(frame)
    higher_low_points, higher_low_detail = higher_low_trigger(frame, higher_low)
    if breakout_points >= higher_low_points and breakout_points > 0:
        return breakout_points, breakout_detail, "BREAKOUT", breakout
    if higher_low_points > 0:
        return higher_low_points, higher_low_detail, "HIGHER LOW", None
    return 0, breakout_detail, "AUCUN", None


def volume_score(frame, setup_type, breakout, higher_low):
    if setup_type == "BREAKOUT" and breakout:
        position = breakout["position"]
        event_volume = float(frame["Volume"].iloc[position])
        average_volume = float(
            frame["Volume"].iloc[position - 20:position].mean()
        )
        ratio = event_volume / average_volume if average_volume > 0 else 0
        if ratio >= 1.5:
            return 15, f"Volume du breakout {ratio:.1f}×"
        if ratio >= 1.2:
            return 12, f"Volume du breakout {ratio:.1f}×"
        if ratio >= 1.0:
            return 8, f"Volume du breakout {ratio:.1f}×"
        return 3, f"Breakout sur faible volume {ratio:.1f}×"

    if setup_type == "HIGHER LOW" and higher_low.get("position") is not None:
        low_position = int(higher_low["position"])
        pullback_start = max(0, low_position - 2)
        pullback_volume = float(
            frame["Volume"].iloc[pullback_start:low_position + 1].mean()
        )
        reference_start = max(0, pullback_start - 20)
        reference_volume = float(
            frame["Volume"].iloc[reference_start:pullback_start].mean()
        )
        pullback_ratio = (
            pullback_volume / reference_volume if reference_volume > 0 else 0
        )
        current_volume = float(frame["Volume"].iloc[-1])
        current_average = float(frame["Volume"].iloc[-21:-1].mean())
        current_ratio = current_volume / current_average if current_average > 0 else 0
        current_change = (
            float(frame["Close"].iloc[-1]) / float(frame["Close"].iloc[-2]) - 1
        )
        if current_change > 0 and current_ratio >= 1.2:
            return 15, f"Volume acheteur au rebond {current_ratio:.1f}×"
        if pullback_ratio <= 0.8:
            return 12, f"Volume en contraction sur le repli {pullback_ratio:.1f}×"
        if pullback_ratio <= 1.0:
            return 10, f"Volume contenu sur le repli {pullback_ratio:.1f}×"
        if pullback_ratio <= 1.2:
            return 7, f"Volume neutre sur le repli {pullback_ratio:.1f}×"
        return 2, f"Repli sur volume élevé {pullback_ratio:.1f}×"

    recent_volume = float(frame["Volume"].iloc[-3:].mean())
    average_volume = float(frame["Volume"].iloc[-23:-3].mean())
    ratio = recent_volume / average_volume if average_volume > 0 else 0
    recent_change = (
        float(frame["Close"].iloc[-1]) / float(frame["Close"].iloc[-4]) - 1
    )

    if recent_change < 0:
        score = 0 if ratio >= 1.2 else 2
        return score, f"Volume 3 j {ratio:.1f}× sur baisse"
    if ratio >= 1.5:
        return 8, f"Volume 3 j fort {ratio:.1f}×"
    if ratio >= 1.2:
        return 6, f"Volume 3 j en hausse {ratio:.1f}×"
    if ratio >= 1.0:
        return 4, f"Volume 3 j normal {ratio:.1f}×"
    return 2, f"Volume 3 j faible {ratio:.1f}×"


def rsi_score(value):
    if 50 <= value <= 65:
        return 15, f"RSI favorable {value:.1f}"
    if 45 <= value < 50:
        return 11, f"RSI neutre {value:.1f}"
    if 65 < value <= 70:
        return 10, f"RSI soutenu {value:.1f}"
    if 35 <= value < 45:
        return 6, f"RSI faible {value:.1f}"
    if 70 < value <= 75:
        return 5, f"RSI tendu {value:.1f}"
    if value < 35:
        return 3, f"RSI survendu {value:.1f}"
    return 0, f"RSI très tendu {value:.1f}"


def price_location_score(price, sma50, sma200):
    if price < sma200:
        distance = (price / sma200 - 1) * 100
        return 0, f"Sous SMA200 de {abs(distance):.1f}%"

    distance = (price / sma50 - 1) * 100
    absolute_distance = abs(distance)
    if absolute_distance <= 3:
        return 25, f"Prix proche SMA50 ({distance:+.1f}%)"
    if absolute_distance <= 5:
        return 20, f"Prix à proximité SMA50 ({distance:+.1f}%)"
    if absolute_distance <= 7:
        return 12, f"Prix à distance modérée SMA50 ({distance:+.1f}%)"
    if 7 < distance <= 10:
        return 5, f"Prix éloigné SMA50 ({distance:+.1f}%)"
    return 0, f"Prix mal placé par rapport à SMA50 ({distance:+.1f}%)"


def score_ticker(ticker, frame):
    frame = frame.dropna(subset=["Close", "High", "Low", "Volume"]).copy()
    if len(frame) < 200:
        raise ValueError("historique insuffisant")

    price = float(frame["Close"].iloc[-1])
    sma50 = float(frame["Close"].rolling(50).mean().iloc[-1])
    sma200 = float(frame["Close"].rolling(200).mean().iloc[-1])
    rsi14 = float(rsi(frame["Close"]).iloc[-1])
    higher_low = higher_low_context(frame)
    trigger_points, trigger_detail, setup_type, breakout = trigger_score(
        frame, higher_low
    )

    components = {
        "trend_structure": trend_structure_score(frame, higher_low, sma200),
        "price_location": price_location_score(price, sma50, sma200),
        "trigger": (trigger_points, trigger_detail),
        "volume": volume_score(frame, setup_type, breakout, higher_low),
        "rsi": rsi_score(rsi14),
    }
    total = sum(value[0] for value in components.values())

    strongest = sorted(
        components.items(), key=lambda item: item[1][0], reverse=True
    )[:2]
    summary = " · ".join(value[1] for _, value in strongest)

    return {
        "ticker": ticker,
        "score": total,
        "setup_type": setup_type,
        "price": round(price, 2),
        "rsi14": round(rsi14, 1),
        "as_of": frame.index[-1].date().isoformat(),
        "summary": summary,
        "components": {
            name: {"score": value[0], "detail": value[1]}
            for name, value in components.items()
        },
    }


def build_rankings(tickers):
    items = []
    unavailable = []
    for ticker in tickers:
        try:
            frame = yf.Ticker(ticker).history(period="1y", auto_adjust=True)
            if frame.empty:
                raise ValueError("données indisponibles")
            current = score_ticker(ticker, frame)
            score_history = []
            for offset in (2, 1, 0):
                sample = frame.iloc[: len(frame) - offset] if offset else frame
                if len(sample.dropna(subset=["Close", "High", "Low", "Volume"])) < 200:
                    continue
                historical = score_ticker(ticker, sample)
                score_history.append({
                    "date": historical["as_of"],
                    "score": historical["score"],
                })
            current["score_history"] = score_history
            if len(score_history) >= 2:
                change = score_history[-1]["score"] - score_history[0]["score"]
            else:
                change = 0
            current["score_change_3d"] = change
            trigger_score_now = current["components"]["trigger"]["score"]
            current["rapid_improvement"] = (
                len(score_history) >= 2
                and change >= 8
                and current["score"] < 75
                and trigger_score_now < 20
            )
            items.append(current)
        except Exception as error:
            unavailable.append({"ticker": ticker, "reason": str(error)})

    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "method": "technical_score_v2_dual_setup",
        "items": sorted(items, key=lambda item: item["score"], reverse=True),
        "unavailable": unavailable,
    }


def main():
    output = build_rankings(WATCHLIST)
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
