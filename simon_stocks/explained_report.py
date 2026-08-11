import subprocess
import sys
from pathlib import Path

from openai import OpenAI
from pydantic import BaseModel

from config import WATCHLIST

HERE = Path(__file__).resolve().parent
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

print(report)
print("\n" + "=" * 56)
print("EXPLICATION DU VERDICT")
print("=" * 56)

for e in response.output_parsed.items:
    print(f"\n{e.ticker}")
    print(f"  POURQUOI: {e.why}")
    print("  POINTS POSITIFS:")
    for x in e.positives:
        print(f"    + {x}")
    print("  RISQUES:")
    for x in e.risks:
        print(f"    - {x}")
    print("  CE QUI FERAIT CHANGER L'AVIS:")
    for x in e.change_conditions:
        print(f"    -> {x}")

if response.usage:
    print(
        f"\nExplanation AI tokens: {response.usage.input_tokens} input / "
        f"{response.usage.output_tokens} output"
    )
