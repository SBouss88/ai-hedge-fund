import re
import subprocess
import sys
from pathlib import Path

from config import WATCHLIST

HERE = Path(__file__).resolve().parent

def run(name):
    p = subprocess.run([sys.executable, str(HERE / name)], capture_output=True, text=True)
    if p.returncode:
        print(p.stdout)
        print(p.stderr)
        raise SystemExit(f"{name} failed")
    return p.stdout

def parse_timing(text):
    out, ticker = {}, None
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"^([A-Z]+):", s)
        if m and m.group(1) in WATCHLIST:
            ticker = m.group(1)
        elif ticker and s.startswith("TIMING:"):
            out[ticker] = s.split(":", 1)[1].strip()
    return out

def parse_fundamentals(text):
    out, ticker = {}, None
    for line in text.splitlines():
        s = line.strip()
        if s in WATCHLIST:
            ticker = s
            out[ticker] = {}
        elif ticker and s.startswith("Fundamental:"):
            m = re.search(r"([0-9.]+)/5", s)
            out[ticker]["score"] = float(m.group(1)) if m else None
        elif ticker and s.startswith("Data confidence:"):
            out[ticker]["confidence"] = s.split(":", 1)[1].strip()
    return out

def parse_news(text):
    out, ticker = {}, None
    for line in text.splitlines():
        s = line.strip()
        if s in WATCHLIST:
            ticker = s
            out[ticker] = {}
        elif ticker and s.startswith("OVERALL:"):
            out[ticker]["overall"] = s.split(":", 1)[1].strip()
        elif ticker and s.startswith("CONFIDENCE:"):
            out[ticker]["confidence"] = s.split(":", 1)[1].strip()
    return out

def verdict(score, fconf, timing, news, nconf):
    if score is None or timing is None:
        return "INCOMPLETE DATA"
    if fconf == "LOW":
        return "WATCH - VERIFY FUNDAMENTALS"
    if score < 3.0:
        return "CAUTION - WEAK FUNDAMENTALS"
    if news == "NEGATIVE" and nconf == "HIGH":
        return "CAUTION - NEGATIVE NEWS"
    if timing == "OVERHEATED - DO NOT CHASE":
        return "WAIT FOR BETTER ENTRY"
    if timing == "CAUTION":
        return "WAIT - TECHNICAL TREND WEAK"
    if score >= 4.0 and timing == "POSITIVE MOMENTUM":
        return "ATTRACTIVE SETUP" if news == "POSITIVE" else "ATTRACTIVE - BUT MONITOR NEWS"
    if score >= 4.0 and timing == "WATCH - PULLBACK":
        return "WATCH - PULLBACK OPPORTUNITY"
    return "WATCH"

print("\nSIMON AI STOCK WATCHLIST - COMBINED REPORT\n")
print("Running technical analysis...")
timing = parse_timing(run("analyze.py"))
print("Running fundamentals...")
fund = parse_fundamentals(run("fundamental_scores.py"))
print("Running AI news analysis...")
raw_news = run("news_summary_structured.py")
news = parse_news(raw_news)

usage_match = re.search(
    r"TOTAL TOKEN USAGE\s+Input:\s*(\d+)\s+Output:\s*(\d+)",
    raw_news,
    re.S,
)
if usage_match:
    print(
        f"NEWS AI TOKENS: {usage_match.group(1)} input / "
        f"{usage_match.group(2)} output"
    )

print("\n" + "=" * 52)
for ticker in WATCHLIST:
    f = fund.get(ticker, {})
    n = news.get(ticker, {})
    score = f.get("score")
    fconf = f.get("confidence", "N/A")
    tech = timing.get(ticker, "N/A")
    overall = n.get("overall", "N/A")
    nconf = n.get("confidence", "N/A")
    view = verdict(score, fconf, tech, overall, nconf)

    print(f"\n{ticker}")
    print(f"  Fundamentals: {score if score is not None else 'N/A'}/5 ({fconf})")
    print(f"  Technical:    {tech}")
    print(f"  News:         {overall} ({nconf})")
    print(f"  RESEARCH VIEW: {view}")

print("\n" + "=" * 52)
print("Research support only - not an automatic trading instruction.")
