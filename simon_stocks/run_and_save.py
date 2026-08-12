from datetime import datetime
from pathlib import Path
import subprocess
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
stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
path = HISTORY_DIR / f"report_{stamp}.txt"
path.write_text(report, encoding="utf-8")

print(report, end="")
print(f"\nSaved: {path.name}")

print("\n--- Changes since previous report ---")
subprocess.run([sys.executable, str(HERE / "compare_latest.py")])
