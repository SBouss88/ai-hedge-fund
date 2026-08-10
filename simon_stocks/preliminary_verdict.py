import subprocess
import sys
from pathlib import Path
from config import WATCHLIST

HERE = Path(__file__).resolve().parent

def run_script(name):
    return subprocess.check_output(
        [sys.executable, str(HERE / name)],
        text=True,
    )

def parse_timing(text):
    result = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        for ticker in WATCHLIST:
            if line.startswith(ticker + ":"):
                current = ticker
                result.setdefault(ticker, {})
                break
        if current and line.startswith("TIMING:"):
            result[current]["timing"] = line.split(":", 1)[1].strip()
    return result
def parse_fundamentals(text):
    result = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if line in WATCHLIST:
            current = line
            result.setdefault(current, {})
        elif current and line.startswith("Fundamental:"):
            value = line.split(":", 1)[1].strip().split("/")[0]
            result[current]["score"] = float(value)
        elif current and line.startswith("Data confidence:"):
            result[current]["confidence"] = line.split(":", 1)[1].strip()
    return result

def verdict(score, confidence, timing):
    if score is None or timing is None:
        return "INCOMPLETE DATA"
    if confidence == "LOW":
        return "WATCH - VERIFY FUNDAMENTALS"
    if score < 3.0:
        return "CAUTION - WEAK FUNDAMENTALS"
    if timing == "OVERHEATED - DO NOT CHASE":
        return "WAIT FOR BETTER ENTRY"
    if timing == "CAUTION":
        return "WAIT - TECHNICAL TREND WEAK"
    if score >= 4.0 and timing == "POSITIVE MOMENTUM":
        return "ATTRACTIVE SETUP"
    if score >= 4.0 and timing == "WATCH - PULLBACK":
        return "WATCH - PULLBACK OPPORTUNITY"
    return "WATCH"

if __name__ == "__main__":
    timing_data = parse_timing(run_script("analyze.py"))
    fundamental_data = parse_fundamentals(run_script("fundamental_scores.py"))

    print("\nSIMON AI STOCK WATCHLIST - PRELIMINARY VERDICT\n")

    for ticker in WATCHLIST:
        t = timing_data.get(ticker, {}).get("timing")
        f = fundamental_data.get(ticker, {})
        score = f.get("score")
        confidence = f.get("confidence")
        result = verdict(score, confidence, t)

        print(ticker)
        print(f"  Fundamental: {score:.1f}/5" if score is not None else "  Fundamental: N/A")
        print(f"  Confidence: {confidence or 'N/A'}")
        print(f"  Technical timing: {t or 'N/A'}")
        print(f"  PRELIMINARY VERDICT: {result}")
        print()
