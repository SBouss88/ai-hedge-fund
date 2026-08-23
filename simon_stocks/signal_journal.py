"""Persist one point-in-time decision snapshot per ticker and market session."""

import json
from datetime import date, datetime
from pathlib import Path


HERE = Path(__file__).resolve().parent
HISTORY = HERE / "history"
JOURNAL_PATH = HISTORY / "technical_signal_journal.jsonl"
STATE_PATH = HISTORY / "technical_signal_state_latest.json"
LEG_WINDOW_DAYS = 21
MAX_ENTRY_GAP_PCT = 2.0


def load_json(name, default):
    path = HISTORY / name
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def item_map(payload):
    items = payload.get("items", []) if isinstance(payload, dict) else []
    if isinstance(items, dict):
        return items
    return {item.get("ticker"): item for item in items if isinstance(item, dict) and item.get("ticker")}


def load_records():
    if not JOURNAL_PATH.exists():
        return []
    records = []
    for line in JOURNAL_PATH.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def technical_ready(item):
    setup_type = (item or {}).get("setup_type")
    score = int((item or {}).get("score", 0))
    confirmed = {
        "HIGHER LOW",
        "BREAKOUT",
        "RETOURNEMENT CONFIRMÉ",
        "PULLBACK CONFIRMÉ",
        "STABILISATION CONFIRMÉE",
    }
    threshold = (
        60
        if setup_type
        in {
            "RETOURNEMENT CONFIRMÉ",
            "PULLBACK CONFIRMÉ",
        }
        else 65
    )
    return setup_type in confirmed and score >= threshold


def eligibility(technical, fundamental, valuation, earnings):
    blockers = []
    if not technical_ready(technical):
        blockers.append("TECHNIQUE_NON_CONFIRMÉE")
    if fundamental.get("score") is None or fundamental.get("score", 0) < 55 or fundamental.get("max_exposure_usd", 0) <= 0:
        blockers.append("FONDAMENTAL_NON_INVESTISSABLE")
    if valuation.get("label") in {
        None,
        "UNAVAILABLE",
        "INDISPONIBLE",
        "VERY EXPENSIVE",
        "PRIME ÉLEVÉE",
        "TRÈS CHÈRE",
    }:
        blockers.append("VALORISATION_NON_FAVORABLE")
    days_until = earnings.get("days_until")
    if days_until is None or days_until <= 7:
        blockers.append("RÉSULTATS_PROCHES_OU_INCONNUS")
    return not blockers, blockers


def execution_check(signal, technical):
    reference_price = signal.get("reference_price")
    current_open = technical.get("open")
    if not reference_price or current_open is None:
        return {"status": "INDISPONIBLE", "gap_pct": None}
    gap = (float(current_open) / float(reference_price) - 1) * 100
    invalidation = signal.get("invalidation") or {}
    invalidation_level = invalidation.get("level")
    if gap > MAX_ENTRY_GAP_PCT:
        status = "ANNULER_GAP"
    elif invalidation_level is not None and current_open < invalidation_level:
        status = "ANNULER_INVALIDATION"
    else:
        status = "EXÉCUTION_PROGRESSIVE_POSSIBLE"
    return {
        "status": status,
        "gap_pct": round(gap, 1),
        "open": current_open,
        "reference_price": reference_price,
        "max_gap_pct": MAX_ENTRY_GAP_PCT,
    }


def build_journal_records():
    rankings = load_json("quick_rankings_latest.json", {})
    technical_items = item_map(rankings)
    fundamental_items = item_map(load_json("fundamental_scores_latest.json", {}))
    valuation_items = item_map(load_json("valuation_latest.json", {}))
    earnings_items = item_map(load_json("earnings_calendar_latest.json", {}))
    prior_records = load_records()
    prior_by_ticker = {}
    for record in prior_records:
        prior_by_ticker.setdefault(record.get("ticker"), []).append(record)

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    new_records = []
    for ticker, technical in technical_items.items():
        as_of = technical.get("as_of")
        ticker_history = prior_by_ticker.get(ticker, [])
        if as_of and any(record.get("technical_as_of") == as_of for record in ticker_history):
            continue

        fundamental = fundamental_items.get(ticker, {})
        valuation = valuation_items.get(ticker, {})
        earnings = earnings_items.get(ticker, {})
        eligible, blockers = eligibility(
            technical,
            fundamental,
            valuation,
            earnings,
        )
        previous = ticker_history[-1] if ticker_history else None
        signal_event = eligible and not (previous or {}).get("eligible", False)
        signal_role = None
        signal_id = None
        if signal_event:
            prior_events = [record for record in ticker_history if record.get("signal_event")]
            last_event = prior_events[-1] if prior_events else None
            if last_event and as_of:
                days_since = (date.fromisoformat(as_of) - date.fromisoformat(last_event["technical_as_of"])).days
            else:
                days_since = None
            signal_role = "RENFORCEMENT_ÉVENTUEL" if days_since is not None and days_since <= LEG_WINDOW_DAYS else "NOUVELLE_OPPORTUNITÉ"
            signal_id = f"{ticker}:{as_of}:{technical.get('setup_type')}"

        execution = None
        execution_check_for = None
        unchecked_events = [record for record in ticker_history if record.get("signal_event") and record.get("technical_as_of") != as_of and not any(later.get("execution_check_for") == record.get("signal_id") for later in ticker_history)]
        if unchecked_events:
            prior_signal = unchecked_events[-1]
            execution = execution_check(prior_signal, technical)
            execution_check_for = prior_signal.get("signal_id")

        new_records.append(
            {
                "recorded_at": generated_at,
                "ticker": ticker,
                "technical_as_of": as_of,
                "reference_price": technical.get("price"),
                "open": technical.get("open"),
                "score": technical.get("score"),
                "setup_type": technical.get("setup_type"),
                "phase": technical.get("phase"),
                "rsi14": technical.get("rsi14"),
                "components": technical.get("components", {}),
                "invalidation": technical.get("invalidation"),
                "fundamental_score": fundamental.get("score"),
                "fundamental_category": fundamental.get("category"),
                "max_exposure_usd": fundamental.get("max_exposure_usd"),
                "valuation": valuation.get("label"),
                "earnings_date": earnings.get("date"),
                "earnings_days": earnings.get("days_until"),
                "eligible": eligible,
                "blockers": blockers,
                "signal_event": signal_event,
                "signal_role": signal_role,
                "signal_id": signal_id,
                "execution_check_for": execution_check_for,
                "execution": execution,
            }
        )
    return prior_records, new_records, generated_at


def main():
    HISTORY.mkdir(exist_ok=True)
    prior_records, new_records, generated_at = build_journal_records()
    if new_records:
        with JOURNAL_PATH.open("a", encoding="utf-8") as journal:
            for record in new_records:
                journal.write(json.dumps(record, ensure_ascii=False) + "\n")
    all_records = [*prior_records, *new_records]
    latest = {}
    for record in all_records:
        latest[record["ticker"]] = record
    state = {
        "generated_at": generated_at,
        "journal": JOURNAL_PATH.name,
        "items": latest,
        "records_added": len(new_records),
    }
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(state, ensure_ascii=False))


if __name__ == "__main__":
    main()
