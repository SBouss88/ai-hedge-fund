from datetime import datetime
from pathlib import Path
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

usage = re.search(r"TOTAL AI TOKENS:\s*(\d+) input / (\d+) output", report)
if usage:
    input_tokens = int(usage.group(1))
    output_tokens = int(usage.group(2))
    analysis_cost = (input_tokens * 0.20 + output_tokens * 1.20) / 1_000_000

    spent_path = HISTORY_DIR / "openai_spent.txt"
    previous_spent = float(spent_path.read_text().strip()) if spent_path.exists() else 0.0
    total_spent = previous_spent + analysis_cost
    spent_path.write_text(f"{total_spent:.8f}", encoding="utf-8")

    print(f"OpenAI estimated cost: ${analysis_cost:.4f}")
stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
path = HISTORY_DIR / f"report_{stamp}.txt"
path.write_text(report, encoding="utf-8")

print(report, end="")
print(f"\nSaved: {path.name}")

print("\n--- Changes since previous report ---")
subprocess.run([sys.executable, str(HERE / "compare_latest.py")])
