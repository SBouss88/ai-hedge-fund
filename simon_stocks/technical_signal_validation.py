"""Point-in-time validation of the current technical entry rules.

The replay calls ``score_ticker`` with data available on each historical date.
It never uses forward prices to create a signal; forward prices are read only
afterward to measure the signal's outcome.
"""

import argparse
import json
from datetime import date, datetime
from pathlib import Path

import yfinance as yf

from config import WATCHLIST
from quick_rankings import score_ticker


HERE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = HERE / "history" / "technical_signal_validation_latest.json"
CONFIRMED_SETUPS = {
    "HIGHER LOW",
    "BREAKOUT",
    "RETOURNEMENT CONFIRMÉ",
    "PULLBACK CONFIRMÉ",
    "STABILISATION CONFIRMÉE",
}
EARLY_SETUPS = {"RETOURNEMENT CONFIRMÉ", "PULLBACK CONFIRMÉ"}
MAX_ENTRY_GAP_PCT = 2.0
MAX_CLEAN_DRAWDOWN_PCT = 8.0
LEG_SEPARATION_SESSIONS = 15


def signal_is_actionable(item):
    setup_type = item.get("setup_type")
    score = int(item.get("score", 0))
    threshold = 60 if setup_type in EARLY_SETUPS else 65
    return setup_type in CONFIRMED_SETUPS and score >= threshold


def percent_change(end, start):
    return (float(end) / float(start) - 1) * 100


def evaluate_outcome(frame, position, horizon):
    future = frame.iloc[position + 1 : position + 1 + horizon]
    if len(future) < horizon:
        return None
    entry = float(future["Open"].iloc[0])
    end_return = percent_change(future["Close"].iloc[-1], entry)
    max_favorable = percent_change(future["High"].max(), entry)
    max_adverse = percent_change(future["Low"].min(), entry)
    downside = abs(min(max_adverse, 0))
    reward_risk = max_favorable / downside if downside > 0 else None
    return {
        "entry_date": future.index[0].date().isoformat(),
        "entry_price": round(entry, 2),
        "return_pct": round(end_return, 1),
        "max_favorable_pct": round(max_favorable, 1),
        "max_drawdown_pct": round(max_adverse, 1),
        "reward_risk": round(reward_risk, 2) if reward_risk is not None else None,
    }


def replay_ticker(ticker, frame, warmup=220, cooldown=5):
    frame = frame.dropna(subset=["Close", "High", "Low", "Volume"]).copy()
    signals = []
    last_signal_position = -cooldown
    previous_signal_position = None
    leg_id = 0
    was_actionable = False
    for position in range(warmup - 1, len(frame)):
        item = score_ticker(ticker, frame.iloc[: position + 1])
        actionable = signal_is_actionable(item)
        new_window = actionable and (not was_actionable or position - last_signal_position >= cooldown)
        if new_window:
            outcome_10 = evaluate_outcome(frame, position, 10)
            outcome_20 = evaluate_outcome(frame, position, 20)
            if previous_signal_position is None or position - previous_signal_position > LEG_SEPARATION_SESSIONS:
                leg_id += 1
                new_leg = True
            else:
                new_leg = False
            reference_outcome = outcome_20 or outcome_10
            execution_gap = percent_change(reference_outcome["entry_price"], item["price"]) if reference_outcome else None
            execution_allowed = execution_gap is not None and execution_gap <= MAX_ENTRY_GAP_PCT
            successful_20d = outcome_20 is not None and outcome_20["return_pct"] > 0 and (outcome_20["reward_risk"] is None or outcome_20["reward_risk"] >= 1)
            signals.append(
                {
                    "date": item["as_of"],
                    "price": item["price"],
                    "score": item["score"],
                    "setup_type": item["setup_type"],
                    "leg_id": leg_id,
                    "new_leg": new_leg,
                    "execution_gap_pct": (round(execution_gap, 1) if execution_gap is not None else None),
                    "execution_allowed": execution_allowed,
                    "outcome_10d": outcome_10,
                    "outcome_20d": outcome_20,
                    "successful_20d": successful_20d,
                    "clean_successful_20d": (successful_20d and execution_allowed and outcome_20["max_drawdown_pct"] >= -MAX_CLEAN_DRAWDOWN_PCT),
                }
            )
            last_signal_position = position
            previous_signal_position = position
        was_actionable = actionable
    return signals


def summarize(signals):
    completed = [signal for signal in signals if signal["outcome_20d"] is not None]
    successes = [signal for signal in completed if signal["successful_20d"]]
    clean_successes = [signal for signal in completed if signal["clean_successful_20d"]]
    executable = [signal for signal in completed if signal["execution_allowed"]]
    independent_legs = [signal for signal in completed if signal["new_leg"]]
    successful_legs = [signal for signal in independent_legs if signal["successful_20d"]]
    clean_successful_legs = [signal for signal in independent_legs if signal["clean_successful_20d"]]
    returns = [signal["outcome_20d"]["return_pct"] for signal in completed]
    drawdowns = [signal["outcome_20d"]["max_drawdown_pct"] for signal in completed]
    return {
        "signals": len(signals),
        "completed_20d": len(completed),
        "successful_20d": len(successes),
        "success_rate_20d_pct": (round(len(successes) / len(completed) * 100, 1) if completed else None),
        "clean_successful_20d": len(clean_successes),
        "clean_success_rate_20d_pct": (round(len(clean_successes) / len(completed) * 100, 1) if completed else None),
        "execution_allowed_20d": len(executable),
        "independent_legs_20d": len(independent_legs),
        "successful_independent_legs_20d": len(successful_legs),
        "clean_successful_independent_legs_20d": len(clean_successful_legs),
        "clean_independent_leg_rate_20d_pct": (round(len(clean_successful_legs) / len(independent_legs) * 100, 1) if independent_legs else None),
        "average_return_20d_pct": (round(sum(returns) / len(returns), 1) if returns else None),
        "average_max_drawdown_20d_pct": (round(sum(drawdowns) / len(drawdowns), 1) if drawdowns else None),
    }


def signal_in_window(signal, start=None, end=None):
    signal_date = date.fromisoformat(signal["date"])
    return not ((start is not None and signal_date < start) or (end is not None and signal_date > end))


def validate(tickers, period="5y", start=None, end=None):
    items = []
    unavailable = []
    all_signals = []
    for ticker in tickers:
        try:
            frame = yf.Ticker(ticker).history(period=period, auto_adjust=True)
            if frame.empty:
                raise ValueError("données indisponibles")
            signals = [signal for signal in replay_ticker(ticker, frame) if signal_in_window(signal, start, end)]
            all_signals.extend(signals)
            items.append(
                {
                    "ticker": ticker,
                    "summary": summarize(signals),
                    "signals": signals,
                }
            )
        except Exception as error:
            unavailable.append({"ticker": ticker, "reason": str(error)})
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "method": "technical_score_v7_point_in_time_validation_v2",
        "success_definition": ("Rendement à 20 séances positif et ratio excursion favorable / " "drawdown maximal au moins égal à 1."),
        "clean_success_definition": ("Succès brut, gap d’ouverture inférieur ou égal à 2 %, drawdown " "maximal limité à 8 %, avec les répétitions d’une même jambe " "identifiées séparément."),
        "summary": summarize(all_signals),
        "items": items,
        "unavailable": unavailable,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", nargs="+", default=WATCHLIST)
    parser.add_argument("--period", default="5y")
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = validate(args.tickers, args.period, args.start, args.end)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
