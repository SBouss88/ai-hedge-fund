from datetime import datetime
from pathlib import Path
import json
import subprocess
import re
import sys

HERE = Path(__file__).resolve().parent
HISTORY_DIR = HERE / "history"
HISTORY_DIR.mkdir(exist_ok=True)

result = subprocess.run(
    [sys.executable, str(HERE / "final_report.py")],
    capture_output=True,
    text=True,
)

if result.stderr:
    print(result.stderr, file=sys.stderr, end="")

if result.returncode != 0:
    raise SystemExit(result.returncode)

report = result.stdout

market_result = subprocess.run(
    [sys.executable, str(HERE / "ai_market_news.py")],
    capture_output=True,
    text=True,
)
market_data = None
if market_result.returncode == 0:
    try:
        market_data = json.loads(market_result.stdout)
        (HISTORY_DIR / "ai_market_news_latest.json").write_text(
            json.dumps(market_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except json.JSONDecodeError:
        print("AI market news returned invalid data.", file=sys.stderr)
elif market_result.stderr:
    print(market_result.stderr, file=sys.stderr, end="")

earnings_result = subprocess.run(
    [sys.executable, str(HERE / "earnings_calendar.py")],
    capture_output=True,
    text=True,
)
if earnings_result.returncode != 0 and earnings_result.stderr:
    print(earnings_result.stderr, file=sys.stderr, end="")

ranking_result = subprocess.run(
    [sys.executable, str(HERE / "quick_rankings.py")],
    capture_output=True,
    text=True,
)
if ranking_result.returncode != 0 and ranking_result.stderr:
    print(ranking_result.stderr, file=sys.stderr, end="")

valuation_result = subprocess.run(
    [sys.executable, str(HERE / "valuation.py")],
    capture_output=True,
    text=True,
)
if valuation_result.returncode != 0 and valuation_result.stderr:
    print(valuation_result.stderr, file=sys.stderr, end="")

audit_result = subprocess.run(
    [sys.executable, str(HERE / "market_data_audit.py")],
    capture_output=True,
    text=True,
)
if audit_result.returncode != 0 and audit_result.stderr:
    print(audit_result.stderr, file=sys.stderr, end="")

input_tokens = 0
output_tokens = 0
usage = re.search(r"TOTAL AI TOKENS:\s*(\d+) input / (\d+) output", report)
if usage:
    input_tokens += int(usage.group(1))
    output_tokens += int(usage.group(2))

if market_data:
    market_usage = market_data.get("usage", {})
    input_tokens += int(market_usage.get("input", 0))
    output_tokens += int(market_usage.get("output", 0))

if input_tokens or output_tokens:
    analysis_cost = (input_tokens * 0.20 + output_tokens * 1.20) / 1_000_000

    spent_path = HISTORY_DIR / "openai_spent.txt"
    previous_spent = float(spent_path.read_text().strip()) if spent_path.exists() else 0.0
    total_spent = previous_spent + analysis_cost
    spent_path.write_text(f"{total_spent:.8f}", encoding="utf-8")

    print(f"OpenAI estimated cost: ${analysis_cost:.4f}")
    if market_data:
        print(
            "AI market news: "
            f"{len(market_data.get('items', []))} major event(s) selected"
        )
stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
path = HISTORY_DIR / f"report_{stamp}.txt"
path.write_text(report, encoding="utf-8")

print(report, end="")
print(f"\nSaved: {path.name}")

print("\n--- Changes since previous report ---")
subprocess.run([sys.executable, str(HERE / "compare_latest.py")])
