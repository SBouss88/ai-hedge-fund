from pathlib import Path
import json
import re

HERE = Path(__file__).resolve().parent
HISTORY = HERE / "history"

def parse_report(path):
    data = {}
    current = None

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if line.startswith("#") and "—" in line:
            left = line.split("—", 1)[0].split()
            current = left[-1]
            data[current] = {}
            continue

        if not current:
            continue

        if line.startswith("Prix:"):
            match = re.search(r"Prix: \$([0-9.,]+)", line)
            if match:
                data[current]["price"] = float(match.group(1).replace(",", ""))

            match = re.search(
                r"Fondamentaux: ([0-9.]+)/(5|100) \(([^)]+)\)",
                line,
            )
            if match:
                data[current]["fundamentals"] = match.group(1)
                data[current]["fund_scale"] = match.group(2)
                data[current]["fund_confidence"] = match.group(3)

            match = re.search(r"News: ([A-Z]+) \(([^)]+)\)", line)
            if match:
                data[current]["news"] = match.group(1)
                data[current]["news_confidence"] = match.group(2)

        elif line.startswith("Verdict:"):
            data[current]["verdict"] = line.split(":", 1)[1].strip()

    return data


def load_json(name):
    path = HISTORY / name
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def item_map(payload):
    items = payload.get("items", [])
    if isinstance(items, dict):
        return items
    return {
        item.get("ticker"): item
        for item in items
        if isinstance(item, dict) and item.get("ticker")
    }


def score_band(value, setup_type="AUCUN"):
    try:
        score = int(value)
    except (TypeError, ValueError):
        return "INDISPONIBLE"
    confirmed = setup_type in (
        "HIGHER LOW",
        "BREAKOUT",
        "RETOURNEMENT CONFIRMÉ",
        "PULLBACK CONFIRMÉ",
        "STABILISATION CONFIRMÉE",
    )
    if setup_type in ("RETOURNEMENT CONFIRMÉ", "PULLBACK CONFIRMÉ") and score >= 60:
        return "EARLY SETUP"
    if confirmed and score >= 75:
        return "VERY GOOD SETUP"
    if confirmed and score >= 65:
        return "GOOD SETUP"
    if score >= 50:
        return "WATCH"
    return "WAIT"


files = sorted(HISTORY.glob("report_*.txt"), reverse=True)
if len(files) < 2:
    raise SystemExit("Need at least two historical reports.")

latest, previous = files[0], files[1]
new = parse_report(latest)
old = parse_report(previous)

technical_now_payload = load_json("quick_rankings_latest.json")
technical_before_payload = load_json("quick_rankings_previous.json")
technical_now = item_map(technical_now_payload)
technical_before = item_map(technical_before_payload)
same_technical_method = (
    technical_now_payload.get("method")
    and technical_now_payload.get("method")
    == technical_before_payload.get("method")
)
valuation_now = item_map(load_json("valuation_latest.json"))
valuation_before = item_map(load_json("valuation_previous.json"))
earnings_now = item_map(load_json("earnings_calendar_latest.json"))
earnings_before = item_map(load_json("earnings_calendar_previous.json"))

print(f"Comparing {previous.name} -> {latest.name}\n")
changes = []

tickers = list(dict.fromkeys([*new, *technical_now]))
for ticker in tickers:
    now = new.get(ticker, {})
    before = old.get(ticker)
    ticker_changes = []

    if before is None and ticker in new:
        ticker_changes.append("new ticker")
    elif before:
        old_price = before.get("price")
        new_price = now.get("price")
        if old_price and new_price:
            pct = (new_price / old_price - 1) * 100
            if abs(pct) >= 3:
                ticker_changes.append(f"price {pct:+.1f}%")

        if now.get("news") == "NEGATIVE" and before.get("news") != "NEGATIVE":
            ticker_changes.append(
                f"news: {before.get('news')} -> {now.get('news')}"
            )

        if before.get("fund_scale") == now.get("fund_scale") and (
            now.get("fundamentals"),
            now.get("fund_confidence"),
        ) != (
            before.get("fundamentals"),
            before.get("fund_confidence"),
        ):
            ticker_changes.append(
                "fundamentals: "
                f"{before.get('fundamentals')} ({before.get('fund_confidence')})"
                " -> "
                f"{now.get('fundamentals')} ({now.get('fund_confidence')})"
            )

    technical = technical_now.get(ticker, {})
    prior_technical = (
        technical_before.get(ticker, {}) if same_technical_method else {}
    )
    history = technical.get("score_history", [])
    current_score = technical.get("score")
    prior_score = prior_technical.get("score")
    if prior_score is None and len(history) >= 2:
        prior_score = history[0].get("score")

    current_setup = technical.get("setup_type", "AUCUN")
    prior_setup = prior_technical.get("setup_type")
    if prior_setup is None and history:
        prior_setup = history[0].get("setup_type")
    if prior_setup is None and prior_score is not None:
        prior_setup = "AUCUN" if prior_score < 65 else current_setup

    if current_score is not None and prior_score is not None:
        score_change = current_score - prior_score
        current_band = score_band(current_score, current_setup)
        prior_band = score_band(prior_score, prior_setup)
        if abs(score_change) >= 8:
            ticker_changes.append(
                f"technical score {prior_score} -> {current_score}"
            )
        if current_band != prior_band:
            ticker_changes.append(f"technical band {prior_band} -> {current_band}")

    if (
        current_setup != prior_setup
        and (current_setup != "AUCUN" or prior_setup != "AUCUN")
    ):
        ticker_changes.append(f"setup {prior_setup or 'AUCUN'} -> {current_setup}")

    current_valuation = valuation_now.get(ticker, {}).get("label")
    prior_valuation = valuation_before.get(ticker, {}).get("label")
    if (
        current_valuation
        and prior_valuation
        and current_valuation != prior_valuation
    ):
        ticker_changes.append(
            f"valuation {prior_valuation} -> {current_valuation}"
        )

    current_earnings = earnings_now.get(ticker, {})
    prior_earnings = earnings_before.get(ticker, {})
    current_date = current_earnings.get("date")
    prior_date = prior_earnings.get("date")
    if current_date and prior_date and current_date != prior_date:
        ticker_changes.append(f"earnings date {prior_date} -> {current_date}")
    current_days = current_earnings.get("days_until")
    prior_days = prior_earnings.get("days_until")
    if (
        isinstance(current_days, int)
        and current_days <= 7
        and (not isinstance(prior_days, int) or prior_days > 7)
    ):
        ticker_changes.append(f"earnings now J-{current_days}")

    if ticker_changes:
        changes.append(ticker + ": " + " | ".join(ticker_changes))

if changes:
    print("SIGNIFICANT CHANGES")
    for change in changes:
        print("- " + change)
else:
    print("No significant change.")
