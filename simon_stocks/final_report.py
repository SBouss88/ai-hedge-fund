import os
import re
import subprocess
import sys
from pathlib import Path

from openai import OpenAI
from pydantic import BaseModel

from config import WATCHLIST

HERE = Path(__file__).resolve().parent

if not os.getenv("OPENAI_API_KEY"):
    key = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-a",
            os.getenv("USER", ""),
            "-s",
            "OPENAI_API_KEY",
            "-w",
        ],
        capture_output=True,
        text=True,
    )
    if key.returncode != 0 or not key.stdout.strip():
        raise SystemExit("OpenAI API key not found in macOS Keychain.")
    os.environ["OPENAI_API_KEY"] = key.stdout.strip()
MODEL = "gpt-5.6-luna"


class Explanation(BaseModel):
    ticker: str
    why: str
    positives: list[str]
    risks: list[str]
    change_conditions: list[str]


class ExplanationBatch(BaseModel):
    items: list[Explanation]


p = subprocess.run(
    [sys.executable, str(HERE / "daily_report.py")],
    capture_output=True,
    text=True,
)

if p.returncode:
    print(p.stdout)
    print(p.stderr)
    raise SystemExit("daily_report.py failed")

report = p.stdout

z = subprocess.run(
    [sys.executable, str(HERE / "entry_zones.py")],
    capture_output=True,
    text=True,
)

if z.returncode:
    print(z.stdout)
    print(z.stderr)
    raise SystemExit("entry_zones.py failed")

zones = z.stdout

prompt = f"""
Voici un rapport de recherche boursiere calcule par des regles Python.

Explique chaque verdict a un investisseur debutant, en francais.

Regles:
- Utilise UNIQUEMENT les informations presentes dans le rapport.
- Ne change jamais le RESEARCH VIEW.
- N'invente aucun fait, prevision, objectif de cours, support ou prix d'entree.
- why: 1 a 2 phrases courtes expliquant le verdict.
- positives: 1 a 3 points.
- risks: 1 a 3 points.
- change_conditions: 1 a 3 conditions concretes qui amelioreraient ou deterioreraient le setup.
- Une confiance fondamentale LOW doit etre presentee comme un risque important.
- Une confiance MEDIUM signifie prudence moderee, pas un risque majeur.
- Un support ou une resistance marque DISTANT ne doit jamais etre presente comme un point positif immediat ou comme une zone d entree proche.
- Tout niveau marque DISTANT doit etre exclu de positives, meme s il est STRONG ou en confluence.
- Une actualite NEUTRAL ou MIXED ne doit pas apparaitre dans positives.
- PRICE EXTENDED signifie que la tendance peut rester favorable mais que le prix est tendu; ne le presente jamais comme une obligation d attendre ou comme un signal de baisse.
- WATCH - PULLBACK signifie un repli a surveiller; ne le presente jamais automatiquement comme une opportunite d achat.
- CAUTION - WEAK TECHNICALS signifie que la tendance technique de fond est suffisamment faible pour justifier une vraie prudence.
- Sois prudent, simple et concis.
- Retourne exactement une analyse pour chacun de ces tickers: {WATCHLIST}.

RAPPORT PRINCIPAL:
{report}

NIVEAUX TECHNIQUES:
{zones}
"""

client = OpenAI()
response = client.responses.parse(
    model=MODEL,
    input=prompt,
    text_format=ExplanationBatch,
)

views = {}
current = None

for line in report.splitlines():
    stripped = line.strip()
    if stripped in WATCHLIST:
        current = stripped
    elif current and "RESEARCH VIEW:" in line:
        views[current] = line.split("RESEARCH VIEW:", 1)[1].strip()

details = {ticker: {} for ticker in WATCHLIST}
current = None

for line in report.splitlines():
    stripped = line.strip()
    if stripped in WATCHLIST:
        current = stripped
    elif current and stripped.startswith("Fundamentals:"):
        details[current]["fundamentals"] = stripped.split(":", 1)[1].strip()
    elif current and stripped.startswith("Technical:"):
        details[current]["technical"] = stripped.split(":", 1)[1].strip()
    elif current and stripped.startswith("News:"):
        details[current]["news"] = stripped.split(":", 1)[1].strip()
    elif current and stripped.startswith("News sources:"):
        details[current]["news_sources"] = stripped.split(":", 1)[1].strip()
    elif current and stripped.startswith("News source status:"):
        details[current]["news_source_status"] = stripped.split(":", 1)[1].strip()

zone_details = {ticker: {} for ticker in WATCHLIST}
current = None

for line in zones.splitlines():
    stripped = line.strip()
    if stripped in WATCHLIST:
        current = stripped
    elif current and stripped.startswith("Price:"):
        zone_details[current]["price"] = stripped.split(":", 1)[1].strip()
    elif current and stripped.startswith("Support:"):
        zone_details[current]["support"] = stripped.split(":", 1)[1].strip()
    elif current and stripped.startswith("Resistance:"):
        zone_details[current]["resistance"] = stripped.split(":", 1)[1].strip()
    elif current and stripped.startswith("SETUP:"):
        zone_details[current]["setup"] = stripped.split(":", 1)[1].strip()


def display_level(view):
    if view == "ATTRACTIVE SETUP":
        return "🟢", "ATTRACTIVE"
    if view == "ATTRACTIVE - PRICE EXTENDED":
        return "🟢🟡", "ATTRACTIVE - PRICE EXTENDED"
    if "ATTRACTIVE" in view:
        return "🟢🟡", "ATTRACTIVE - MONITOR"
    if view == "WATCH - PRICE EXTENDED":
        return "🟡", "WATCH - PRICE EXTENDED"
    if view == "WATCH - PULLBACK":
        return "🟡", "WATCH - PULLBACK"
    if "VERIFY FUNDAMENTALS" in view:
        return "🟠🔴", "VERIFY - HIGH UNCERTAINTY"
    if "CAUTION" in view:
        return "🔴", "CAUTION"
    return "⚪", "WATCH"


def ranking_score(view):
    if view == "ATTRACTIVE SETUP":
        return 6
    if view == "ATTRACTIVE - PRICE EXTENDED":
        return 5
    if "ATTRACTIVE" in view:
        return 5
    if view in ("WATCH - PRICE EXTENDED", "WATCH - PULLBACK"):
        return 3
    if "VERIFY FUNDAMENTALS" in view:
        return 2
    if "CAUTION" in view:
        return 1
    return 3



explanations = {e.ticker: e for e in response.output_parsed.items}
ranked_tickers = sorted(
    WATCHLIST,
    key=lambda ticker: ranking_score(views.get(ticker, "UNKNOWN")),
    reverse=True,
)


print("\n" + "=" * 60)
print("SIMON AI STOCK WATCHLIST - FINAL REPORT")
print("=" * 60)

for rank, ticker in enumerate(ranked_tickers, start=1):
    e = explanations[ticker]
    view = views.get(ticker, "UNKNOWN")
    emoji, level = display_level(view)
    d = details.get(ticker, {})
    zinfo = zone_details.get(ticker, {})

    print(f"\n#{rank}  {emoji} {ticker} — {level}")
    print(
        f"  Prix: {zinfo.get("price", "N/A")} | "
        f"Fondamentaux: {d.get("fundamentals", "N/A")} | "
        f"News: {d.get("news", "N/A")}"
    )
    print(f"  Technique: {d.get("technical", "N/A")}")
    print(f"  Sources news: {d.get("news_sources", "Yahoo Finance")}")
    print(f"  Statut sources news: {d.get("news_source_status", "Yahoo Finance=OK")}")
    print(f"  Support: {zinfo.get("support", "N/A")}")
    print(f"  Resistance: {zinfo.get("resistance", "N/A")}")
    print(f"  Verdict: {view}")
    print(f"  Pourquoi: {e.why}")

    if e.risks:
        print(f"  Risque principal: {e.risks[0]}")

    if e.change_conditions:
        print(f"  A surveiller: {e.change_conditions[0]}")


print("\nResearch support only - not an automatic trading instruction.")

news_usage = re.search(
    r"NEWS AI TOKENS:\s*(\d+) input / (\d+) output",
    report,
)

news_in = int(news_usage.group(1)) if news_usage else 0
news_out = int(news_usage.group(2)) if news_usage else 0

final_in = response.usage.input_tokens if response.usage else 0
final_out = response.usage.output_tokens if response.usage else 0

print(f"Explanation AI tokens: {final_in} input / {final_out} output")
print(
    f"TOTAL AI TOKENS: {news_in + final_in} input / "
    f"{news_out + final_out} output"
)
