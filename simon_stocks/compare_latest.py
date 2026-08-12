from pathlib import Path
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

            match = re.search(r"Fondamentaux: ([0-9.]+)/5 \(([^)]+)\)", line)
            if match:
                data[current]["fundamentals"] = match.group(1)
                data[current]["fund_confidence"] = match.group(2)

            match = re.search(r"News: ([A-Z]+) \(([^)]+)\)", line)
            if match:
                data[current]["news"] = match.group(1)
                data[current]["news_confidence"] = match.group(2)

        elif line.startswith("Verdict:"):
            data[current]["verdict"] = line.split(":", 1)[1].strip()

    return data

files = sorted(HISTORY.glob("report_*.txt"), reverse=True)

if len(files) < 2:
    raise SystemExit("Need at least two historical reports.")

latest, previous = files[0], files[1]
new = parse_report(latest)
old = parse_report(previous)

print(f"Comparing {previous.name} -> {latest.name}\n")

changes = []

for ticker, now in new.items():
    before = old.get(ticker)
    if not before:
        changes.append(f"{ticker}: new ticker")
        continue

    ticker_changes = []

    old_price = before.get("price")
    new_price = now.get("price")
    if old_price and new_price:
        pct = (new_price / old_price - 1) * 100
        if abs(pct) >= 1:
            ticker_changes.append(f"price {pct:+.1f}%")

    if now.get("verdict") != before.get("verdict"):
        ticker_changes.append(
            f"verdict: {before.get("verdict")} -> {now.get("verdict")}"
        )

    if now.get("news") != before.get("news"):
        ticker_changes.append(
            f"news: {before.get("news")} -> {now.get("news")}"
        )

    if (
        now.get("fundamentals"),
        now.get("fund_confidence"),
    ) != (
        before.get("fundamentals"),
        before.get("fund_confidence"),
    ):
        ticker_changes.append(
            f"fundamentals: {before.get("fundamentals")} ({before.get("fund_confidence")})"
            f" -> {now.get("fundamentals")} ({now.get("fund_confidence")})"
        )

    if ticker_changes:
        changes.append(ticker + ": " + " | ".join(ticker_changes))

if changes:
    print("SIGNIFICANT CHANGES")
    for change in changes:
        print("- " + change)
else:
    print("No significant change.")
