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
            "state": "INSUFFICIENT",
            "detail": "Higher low : données insuffisantes",
            "change": None,
            "age": None,
            "distance": None,
            "position": None,
            "value": None,
        }

    latest = lows[-1]
    previous = lows[-2]
    change = (latest["value"] / previous["value"] - 1) * 100
    age = len(frame) - 1 - latest["position"]
    current_close = float(frame["Close"].iloc[-1])
    distance = (current_close / latest["value"] - 1) * 100
    if distance < 0:
        score, state = 0, "INVALIDATED"
        detail = f"Higher low invalidé ({distance:.1f}% sous le creux)"
    elif change >= 2:
        score, state = 15, "CONFIRMED"
        detail = f"Higher low confirmé +{change:.1f}%"
    elif change >= 0.5:
        score, state = 12, "CONFIRMED"
        detail = f"Higher low confirmé +{change:.1f}%"
    elif change >= -0.5:
        score, state = 5, "STABLE"
        detail = f"Creux stable {change:+.1f}%"
    else:
        candidate_start = max(latest["position"] + 1, len(frame) - 5)
        candidate_window = frame["Low"].iloc[candidate_start:]
        candidate_low = (
            float(candidate_window.min()) if not candidate_window.empty else None
        )
        candidate_change = (
            (candidate_low / latest["value"] - 1) * 100
            if candidate_low is not None
            else None
        )
        if candidate_change is not None and candidate_change >= 0.5:
            score, state = 7, "FORMING"
            detail = f"Higher low en formation +{candidate_change:.1f}%"
        else:
            score, state = 0, "LOWER LOW"
            detail = f"Creux descendant {change:.1f}%"
    return {
        "score": score,
        "state": state,
        "detail": detail,
        "change": change,
        "age": age,
        "distance": distance,
        "position": latest["position"],
        "value": latest["value"],
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
            event_volume = float(frame["Volume"].iloc[position])
            average_volume = float(
                frame["Volume"].iloc[position - 20:position].mean()
            )
            volume_ratio = (
                event_volume / average_volume if average_volume > 0 else 0
            )
            recent_breakout = {
                "position": position,
                "age": last_position - position,
                "level": level,
                "volume_ratio": volume_ratio,
                "confirmed": volume_ratio >= 1.0,
            }

    current_close = float(frame["Close"].iloc[-1])
    if recent_breakout:
        age = recent_breakout["age"]
        level = recent_breakout["level"]
        volume_ratio = recent_breakout["volume_ratio"]
        distance = (current_close / level - 1) * 100

        if volume_ratio < 1.0:
            if distance < 0:
                return 0, "Breakout faible non conservé", recent_breakout
            return (
                5,
                f"Breakout à confirmer : volume faible {volume_ratio:.1f}×",
                recent_breakout,
            )

        if age == 0:
            if distance <= 2:
                points = 20 if volume_ratio >= 1.2 else 15
                return (
                    points,
                    f"Breakout aujourd’hui +{distance:.1f}% · volume {volume_ratio:.1f}×",
                    recent_breakout,
                )
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


def reversal_trigger(frame):
    """Detect a forceful bullish reversal, then require one-session confirmation."""
    last_position = len(frame) - 1
    event = None
    for position in range(max(21, last_position - 2), last_position + 1):
        previous_close = float(frame["Close"].iloc[position - 1])
        previous_high = float(frame["High"].iloc[position - 1])
        close = float(frame["Close"].iloc[position])
        high = float(frame["High"].iloc[position])
        low = float(frame["Low"].iloc[position])
        candle_range = high - low
        close_location = (close - low) / candle_range if candle_range > 0 else 0
        daily_change = (close / previous_close - 1) * 100
        pullback_reference = float(frame["Close"].iloc[position - 3])
        prior_pullback = (previous_close / pullback_reference - 1) * 100
        sma200_at_event = float(
            frame["Close"].iloc[: position + 1].rolling(200).mean().iloc[-1]
        )
        if not (
            close >= sma200_at_event
            and daily_change >= 4
            and close_location >= 0.75
            and close > previous_high
            and prior_pullback <= -4
        ):
            continue

        event_volume = float(frame["Volume"].iloc[position])
        average_volume = float(
            frame["Volume"].iloc[position - 20:position].mean()
        )
        event = {
            "position": position,
            "age": last_position - position,
            "close": close,
            "low": low,
            "midpoint": low + candle_range * 0.5,
            "daily_change": daily_change,
            "close_location": close_location,
            "volume_ratio": (
                event_volume / average_volume if average_volume > 0 else 0
            ),
        }

    if not event:
        return 0, "Pas de retournement haussier récent", "AUCUN", None

    age = event["age"]
    volume_ratio = event["volume_ratio"]
    if age == 0:
        points = 18 if volume_ratio >= 1.2 else 15 if volume_ratio >= 0.8 else 12
        return (
            points,
            f"Retournement haussier +{event['daily_change']:.1f}% à confirmer",
            "RETOURNEMENT",
            event,
        )

    current_close = float(frame["Close"].iloc[-1])
    current_low = float(frame["Low"].iloc[-1])
    held = current_close >= event["midpoint"] and current_low >= event["low"]
    if age <= 2 and held:
        points = 16 if age == 1 else 14
        return (
            points,
            f"Retournement confirmé depuis {age} séance{'s' if age > 1 else ''}",
            "RETOURNEMENT CONFIRMÉ",
            event,
        )
    return 0, "Retournement non confirmé", "AUCUN", event


def pullback_trigger(frame):
    """Find an orderly pullback, then require a bullish price reclaim."""
    last_position = len(frame) - 1
    event = None
    for position in range(max(220, last_position - 2), last_position + 1):
        history = frame.iloc[: position + 1]
        close = float(history["Close"].iloc[-1])
        low = float(history["Low"].iloc[-1])
        sma50 = float(history["Close"].rolling(50).mean().iloc[-1])
        sma200 = float(history["Close"].rolling(200).mean().iloc[-1])
        sma200_previous = float(history["Close"].rolling(200).mean().iloc[-21])
        rsi_at_event = float(rsi(history["Close"]).iloc[-1])
        prior_high = float(frame["High"].iloc[position - 20:position].max())
        drawdown = (close / prior_high - 1) * 100
        distance_sma200 = (close / sma200 - 1) * 100
        recent_volume = float(
            frame["Volume"].iloc[max(0, position - 2):position + 1].mean()
        )
        reference_volume = float(
            frame["Volume"].iloc[max(0, position - 22):position - 2].mean()
        )
        volume_ratio = (
            recent_volume / reference_volume if reference_volume > 0 else 0
        )
        if not (
            close >= sma200
            and sma50 >= sma200
            and sma200 >= sma200_previous
            and -15 <= drawdown <= -5
            and 0 <= distance_sma200 <= 8
            and 28 <= rsi_at_event <= 42
            and volume_ratio <= 1.0
        ):
            continue
        event = {
            "position": position,
            "age": last_position - position,
            "close": close,
            "low": low,
            "drawdown": drawdown,
            "distance_sma200": distance_sma200,
            "rsi": rsi_at_event,
            "volume_ratio": volume_ratio,
        }

    if not event:
        return 0, "Pas de pullback favorable récent", "AUCUN", None

    age = event["age"]
    if age == 0:
        return (
            8,
            f"Pullback favorable {event['drawdown']:.1f}% · reprise à confirmer",
            "PULLBACK FAVORABLE",
            event,
        )

    confirmation_position = event["position"] + 1
    confirmation_close = float(frame["Close"].iloc[confirmation_position])
    confirmation_high = float(frame["High"].iloc[confirmation_position])
    confirmation_low = float(frame["Low"].iloc[confirmation_position])
    confirmation_previous_close = float(
        frame["Close"].iloc[confirmation_position - 1]
    )
    confirmation_previous_high = float(
        frame["High"].iloc[confirmation_position - 1]
    )
    confirmation_range = confirmation_high - confirmation_low
    confirmation_location = (
        (confirmation_close - confirmation_low) / confirmation_range
        if confirmation_range > 0
        else 0
    )
    confirmation_change = (
        confirmation_close / confirmation_previous_close - 1
    ) * 100
    reclaimed = (
        confirmation_change >= 2
        and confirmation_close > confirmation_previous_high
        and confirmation_location >= 0.65
        and confirmation_low >= event["low"]
    )
    current_close = float(frame["Close"].iloc[-1])
    current_low = float(frame["Low"].iloc[-1])
    held = current_close >= event["close"] and current_low >= event["low"]
    if age <= 2 and reclaimed and held:
        event["confirmation_change"] = confirmation_change
        event["confirmation_position"] = confirmation_position
        return (
            15 if age == 1 else 13,
            f"Pullback confirmé : reprise +{confirmation_change:.1f}%",
            "PULLBACK CONFIRMÉ",
            event,
        )
    if age <= 2 and held:
        return 5, "Zone de pullback tenue · reprise manquante", "PULLBACK FAVORABLE", event
    return 0, "Pullback favorable invalidé", "AUCUN", event


def shock_stabilization_trigger(frame):
    """Confirm that a high-volume bearish shock has stopped making new lows."""
    last_position = len(frame) - 1
    event = None
    for position in range(max(220, last_position - 4), last_position + 1):
        previous_close = float(frame["Close"].iloc[position - 1])
        close = float(frame["Close"].iloc[position])
        daily_change = (close / previous_close - 1) * 100
        event_volume = float(frame["Volume"].iloc[position])
        average_volume = float(
            frame["Volume"].iloc[position - 20:position].mean()
        )
        volume_ratio = event_volume / average_volume if average_volume > 0 else 0
        previous_history = frame.iloc[:position]
        previous_sma50 = float(
            previous_history["Close"].rolling(50).mean().iloc[-1]
        )
        previous_sma200 = float(
            previous_history["Close"].rolling(200).mean().iloc[-1]
        )
        previously_healthy = (
            previous_close >= previous_sma200 and previous_sma50 >= previous_sma200
        )
        if daily_change <= -5 and volume_ratio >= 1.5 and previously_healthy:
            event = {
                "position": position,
                "age": last_position - position,
                "close": close,
                "low": float(frame["Low"].iloc[position]),
                "daily_change": daily_change,
                "volume": event_volume,
                "volume_ratio": volume_ratio,
            }

    if not event:
        return 0, "Pas de choc baissier récent", "AUCUN", None

    age = event["age"]
    if age < 2:
        return (
            5,
            f"Choc baissier {event['daily_change']:.1f}% · stabilisation à confirmer",
            "CHOC EN STABILISATION",
            event,
        )

    subsequent = frame.iloc[event["position"] + 1:last_position + 1]
    lows_hold = (
        not subsequent.empty
        and float(subsequent["Low"].min()) >= event["low"] * 0.995
    )
    closes = [event["close"], *[float(value) for value in subsequent["Close"]]]
    rising_closes = all(
        closes[index] > closes[index - 1]
        for index in range(1, len(closes))
    )
    current_close = float(frame["Close"].iloc[-1])
    current_sma200 = float(frame["Close"].rolling(200).mean().iloc[-1])
    recovery = (current_close / event["close"] - 1) * 100
    post_volume = float(subsequent["Volume"].mean())
    post_volume_ratio = (
        post_volume / event["volume"] if event["volume"] > 0 else 0
    )
    event["post_volume_ratio"] = post_volume_ratio
    event["recovery"] = recovery

    if (
        age <= 4
        and lows_hold
        and rising_closes
        and recovery >= 2
        and current_close >= current_sma200
        and post_volume_ratio <= 0.7
    ):
        return (
            15,
            f"Stabilisation confirmée après choc · reprise +{recovery:.1f}%",
            "STABILISATION CONFIRMÉE",
            event,
        )
    if age <= 4 and lows_hold:
        return (
            5,
            "Point bas tenu après choc · reprise encore incomplète",
            "CHOC EN STABILISATION",
            event,
        )
    return 0, "Stabilisation après choc invalidée", "AUCUN", event


def higher_low_trigger(frame, higher_low):
    age = higher_low.get("age")
    distance = higher_low.get("distance")
    structural_change = higher_low.get("change")
    if (
        higher_low.get("score", 0) < 12
        or structural_change is None
        or structural_change < 2
        or age is None
        or distance is None
    ):
        return 0, "Pas de higher low structurellement assez fort", "AUCUN"
    if distance < 0:
        return 0, f"Higher low non conservé ({distance:.1f}% sous le creux)", "AUCUN"

    current_close = float(frame["Close"].iloc[-1])
    previous_close = float(frame["Close"].iloc[-2])
    previous_high = float(frame["High"].iloc[-2])
    current_high = float(frame["High"].iloc[-1])
    current_low = float(frame["Low"].iloc[-1])
    candle_range = current_high - current_low
    close_location = (
        (current_close - current_low) / candle_range if candle_range > 0 else 0
    )
    rebound_change = (current_close / previous_close - 1) * 100
    rebound_confirmed = (
        age <= 15
        and distance <= 7
        and rebound_change >= 1.5
        and current_close > previous_high
        and close_location >= 0.65
    )
    if rebound_confirmed:
        return (
            15,
            f"Higher low confirmé : reprise +{rebound_change:.1f}% au-dessus du plus haut J-1",
            "HIGHER LOW",
        )
    if age <= 15 and distance <= 7:
        return (
            5,
            f"Higher low valide (+{structural_change:.1f}%) · reprise du prix à confirmer",
            "HIGHER LOW À CONFIRMER",
        )
    if age <= 20 and distance <= 10:
        return 3, f"Higher low récent, mais prix déjà à +{distance:.1f}% du creux", "HIGHER LOW À CONFIRMER"
    return 0, "Higher low trop ancien ou prix déjà éloigné", "AUCUN"


def trigger_score(frame, higher_low):
    breakout_points, breakout_detail, breakout = breakout_trigger(frame)
    higher_low_points, higher_low_detail, higher_low_type = higher_low_trigger(
        frame, higher_low
    )
    reversal_points, reversal_detail, reversal_type, reversal = reversal_trigger(frame)
    pullback_points, pullback_detail, pullback_type, pullback = pullback_trigger(frame)
    shock_points, shock_detail, shock_type, shock = shock_stabilization_trigger(frame)
    breakout_type = (
        "BREAKOUT"
        if breakout and breakout.get("confirmed")
        else "BREAKOUT FAIBLE"
    )
    candidates = (
        (breakout_points, breakout_detail, breakout_type, breakout),
        (higher_low_points, higher_low_detail, higher_low_type, higher_low),
        (reversal_points, reversal_detail, reversal_type, reversal),
        (pullback_points, pullback_detail, pullback_type, pullback),
        (shock_points, shock_detail, shock_type, shock),
    )
    best = max(candidates, key=lambda candidate: candidate[0])
    if best[0] > 0:
        return best
    return 0, breakout_detail, "AUCUN", None


def volume_score(frame, setup_type, trigger_event, higher_low):
    if setup_type.startswith("BREAKOUT") and trigger_event:
        position = trigger_event["position"]
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

    if setup_type.startswith("RETOURNEMENT") and trigger_event:
        ratio = trigger_event.get("volume_ratio", 0)
        if ratio >= 1.5:
            return 15, f"Volume fort sur le retournement {ratio:.1f}×"
        if ratio >= 1.2:
            return 12, f"Volume soutenu sur le retournement {ratio:.1f}×"
        if ratio >= 1.0:
            return 10, f"Volume normal sur le retournement {ratio:.1f}×"
        if ratio >= 0.8:
            return 8, f"Retournement sur volume modéré {ratio:.1f}×"
        return 4, f"Retournement sur faible volume {ratio:.1f}×"

    if setup_type.startswith("PULLBACK") and trigger_event:
        pullback_ratio = trigger_event.get("volume_ratio", 0)
        if setup_type == "PULLBACK CONFIRMÉ":
            position = trigger_event.get("confirmation_position")
            if position is not None:
                current_volume = float(frame["Volume"].iloc[position])
                current_average = float(
                    frame["Volume"].iloc[max(0, position - 20):position].mean()
                )
                current_ratio = (
                    current_volume / current_average if current_average > 0 else 0
                )
                if current_ratio >= 1.2:
                    return 15, f"Volume acheteur sur la reprise {current_ratio:.1f}×"
        if pullback_ratio <= 0.8:
            return 12, f"Pression vendeuse en contraction {pullback_ratio:.1f}×"
        if pullback_ratio <= 1.0:
            return 10, f"Volume contenu pendant le pullback {pullback_ratio:.1f}×"
        return 5, f"Volume du pullback à surveiller {pullback_ratio:.1f}×"

    if setup_type in ("CHOC EN STABILISATION", "STABILISATION CONFIRMÉE") and trigger_event:
        post_ratio = trigger_event.get("post_volume_ratio")
        if post_ratio is None:
            return 0, "Attendre la contraction du volume après le choc"
        if post_ratio <= 0.5:
            return 15, f"Volume post-choc fortement contracté {post_ratio:.1f}×"
        if post_ratio <= 0.7:
            return 12, f"Volume post-choc en contraction {post_ratio:.1f}×"
        if post_ratio <= 0.9:
            return 7, f"Volume post-choc encore présent {post_ratio:.1f}×"
        return 0, f"Pression vendeuse post-choc persistante {post_ratio:.1f}×"

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
        if ratio >= 1.2:
            return 0, f"Repli sur volume élevé {ratio:.1f}×"
        if ratio <= 0.8:
            return 8, f"Repli sur volume en contraction {ratio:.1f}×"
        if ratio <= 1.0:
            return 7, f"Repli sur volume contenu {ratio:.1f}×"
        return 5, f"Repli sur volume neutre {ratio:.1f}×"
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


def price_location_score(price, sma50, sma200, setup_type="AUCUN"):
    if price < sma200:
        distance = (price / sma200 - 1) * 100
        return 0, f"Sous SMA200 de {abs(distance):.1f}%"

    distance_sma200 = (price / sma200 - 1) * 100
    if setup_type in ("CHOC EN STABILISATION", "STABILISATION CONFIRMÉE"):
        if 0 <= distance_sma200 <= 3:
            return 25, f"Prix proche du support SMA200 (+{distance_sma200:.1f}%)"
        if 3 < distance_sma200 <= 5:
            return 20, f"Prix à proximité SMA200 (+{distance_sma200:.1f}%)"

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


def trend_regime(frame, price, sma50, sma200):
    sma50_previous = float(frame["Close"].rolling(50).mean().iloc[-21])
    sma200_previous = float(frame["Close"].rolling(200).mean().iloc[-21])
    sma50_rising = sma50 > sma50_previous
    sma200_rising = sma200 > sma200_previous
    if (
        price >= sma50
        and sma50 >= sma200
        and sma50_rising
        and sma200_rising
    ):
        return "HAUSSIÈRE FORTE"
    if price >= sma200 and sma50 >= sma200:
        return "HAUSSIÈRE"
    if price >= sma200:
        return "CONSOLIDATION HAUSSIÈRE"
    if sma50 >= sma200:
        return "FRAGILISÉE"
    return "BAISSIÈRE"


def market_phase(price, sma50, sma200, rsi14, setup_type, higher_low):
    distance_sma50 = (price / sma50 - 1) * 100
    if setup_type == "BREAKOUT":
        return "BREAKOUT / RETEST"
    if setup_type == "BREAKOUT FAIBLE":
        return "BREAKOUT À CONFIRMER"
    if setup_type == "RETOURNEMENT CONFIRMÉ":
        return "RETOURNEMENT CONFIRMÉ"
    if setup_type == "RETOURNEMENT":
        return "RETOURNEMENT À CONFIRMER"
    if setup_type == "PULLBACK CONFIRMÉ":
        return "REPRISE SUR PULLBACK CONFIRMÉE"
    if setup_type == "PULLBACK FAVORABLE":
        return "ZONE DE PULLBACK FAVORABLE"
    if setup_type == "STABILISATION CONFIRMÉE":
        return "STABILISATION APRÈS CHOC CONFIRMÉE"
    if setup_type == "CHOC EN STABILISATION":
        return "STABILISATION APRÈS CHOC EN COURS"
    if setup_type == "HIGHER LOW":
        return "REBOND SUR HIGHER LOW"
    if setup_type == "HIGHER LOW À CONFIRMER":
        return "HIGHER LOW À CONFIRMER"
    if higher_low.get("state") == "FORMING":
        return "HIGHER LOW EN FORMATION"
    if rsi14 > 75 or distance_sma50 > 10:
        return "PRIX ÉTENDU"
    if price >= sma200 and abs(distance_sma50) <= 5:
        return "CONSOLIDATION"
    if price >= sma200 and price < sma50:
        return "REPLI"
    if price >= sma200:
        return "TENDANCE SANS DÉCLENCHEUR"
    return "TENDANCE FRAGILE"


def setup_invalidation(setup_type, trigger_event, higher_low, price):
    level = None
    rule = None
    if setup_type in ("HIGHER LOW", "HIGHER LOW À CONFIRMER"):
        level = higher_low.get("value")
        rule = "Creux du Higher Low cassé"
    elif setup_type in ("BREAKOUT", "BREAKOUT FAIBLE") and trigger_event:
        level = trigger_event.get("level")
        rule = "Clôture de retour sous le niveau de breakout"
    elif setup_type.startswith("PULLBACK") and trigger_event:
        level = trigger_event.get("low")
        rule = "Plus bas du pullback cassé"
    elif setup_type.startswith("RETOURNEMENT") and trigger_event:
        level = trigger_event.get("low")
        rule = "Plus bas de la bougie de retournement cassé"
    elif setup_type in ("CHOC EN STABILISATION", "STABILISATION CONFIRMÉE"):
        level = (trigger_event or {}).get("low")
        rule = "Point bas de stabilisation cassé"

    if level is None or rule is None:
        return None
    distance = (float(level) / price - 1) * 100
    return {
        "level": round(float(level), 2),
        "distance_pct": round(distance, 1),
        "rule": rule,
    }


def score_ticker(ticker, frame):
    frame = frame.dropna(subset=["Open", "Close", "High", "Low", "Volume"]).copy()
    if len(frame) < 200:
        raise ValueError("historique insuffisant")

    price = float(frame["Close"].iloc[-1])
    sma50 = float(frame["Close"].rolling(50).mean().iloc[-1])
    sma200 = float(frame["Close"].rolling(200).mean().iloc[-1])
    rsi14 = float(rsi(frame["Close"]).iloc[-1])
    higher_low = higher_low_context(frame)
    trigger_points, trigger_detail, setup_type, trigger_event = trigger_score(
        frame, higher_low
    )
    trend = trend_regime(frame, price, sma50, sma200)
    phase = market_phase(
        price,
        sma50,
        sma200,
        rsi14,
        setup_type,
        higher_low,
    )

    components = {
        "trend_structure": trend_structure_score(frame, higher_low, sma200),
        "price_location": price_location_score(price, sma50, sma200, setup_type),
        "trigger": (trigger_points, trigger_detail),
        "volume": volume_score(frame, setup_type, trigger_event, higher_low),
        "rsi": rsi_score(rsi14),
    }
    total = sum(value[0] for value in components.values())

    strongest = sorted(
        components.items(), key=lambda item: item[1][0], reverse=True
    )[:2]
    summary = " · ".join(value[1] for _, value in strongest)
    current_open = float(frame["Open"].iloc[-1])
    previous_close = float(frame["Close"].iloc[-2])
    opening_gap = (current_open / previous_close - 1) * 100
    invalidation = setup_invalidation(
        setup_type,
        trigger_event,
        higher_low,
        price,
    )

    return {
        "ticker": ticker,
        "score": total,
        "setup_type": setup_type,
        "higher_low_state": higher_low.get("state"),
        "trend_regime": trend,
        "phase": phase,
        "price": round(price, 2),
        "open": round(current_open, 2),
        "previous_close": round(previous_close, 2),
        "opening_gap_pct": round(opening_gap, 1),
        "invalidation": invalidation,
        "rsi14": round(rsi14, 1),
        "metrics": {
            "sma50": round(sma50, 2),
            "sma200": round(sma200, 2),
            "vs_sma50_pct": round((price / sma50 - 1) * 100, 1),
            "vs_sma200_pct": round((price / sma200 - 1) * 100, 1),
        },
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
                    "setup_type": historical["setup_type"],
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
        "method": "technical_score_v7_confirmed_higher_low_and_signal_validation",
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
