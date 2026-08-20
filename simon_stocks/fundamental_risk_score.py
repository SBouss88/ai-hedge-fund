import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Literal

import yfinance as yf
from openai import OpenAI
from pydantic import BaseModel, Field

from config import WATCHLIST
from external_news import fetch_external_news


HERE = Path(__file__).resolve().parent
HISTORY_DIR = HERE / "history"
LATEST_PATH = HISTORY_DIR / "fundamental_scores_latest.json"
MODEL = "gpt-5.6-luna"


class QualitativeAssessment(BaseModel):
    ticker: str
    moat: int = Field(ge=0, le=25)
    moat_reason: str
    diversification: int = Field(ge=0, le=20)
    diversification_reason: str
    competitive_resilience: int = Field(ge=0, le=15)
    competitive_reason: str
    specific_risk_resilience: int = Field(ge=0, le=15)
    specific_risks_reason: str
    confidence: Literal["LOW", "MEDIUM", "HIGH"]
    watch_items: list[str]


class QualitativeBatch(BaseModel):
    items: list[QualitativeAssessment]


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratio(numerator, denominator):
    numerator = _number(numerator)
    denominator = _number(denominator)
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _band_score(value, bands, missing=0):
    if value is None:
        return missing
    for threshold, points in bands:
        if value >= threshold:
            return points
    return 0


def financial_strength(info):
    revenue_growth = _number(info.get("revenueGrowth"))
    profit_margin = _number(info.get("profitMargins"))
    free_cashflow = _number(info.get("freeCashflow"))
    operating_cashflow = _number(info.get("operatingCashflow"))
    total_revenue = _number(info.get("totalRevenue"))
    total_cash = _number(info.get("totalCash"))
    total_debt = _number(info.get("totalDebt"))
    fcf_margin = _ratio(free_cashflow, total_revenue)

    growth = _band_score(
        revenue_growth,
        ((0.20, 5), (0.10, 4), (0.05, 3), (0.00, 2), (-0.05, 1)),
    )
    profitability = _band_score(
        profit_margin,
        ((0.25, 5), (0.15, 4), (0.08, 3), (0.00, 2)),
    )
    cash_generation = _band_score(
        fcf_margin,
        ((0.20, 5), (0.12, 4), (0.05, 3), (0.00, 2)),
    )

    if total_cash is None or total_debt is None:
        balance_sheet = 1
        debt_to_cash = None
    elif total_debt <= total_cash:
        balance_sheet = 5
        debt_to_cash = _ratio(total_debt, total_cash)
    else:
        debt_to_cash = _ratio(total_debt, total_cash)
        if debt_to_cash is not None and debt_to_cash <= 1.5:
            balance_sheet = 4
        elif debt_to_cash is not None and debt_to_cash <= 3:
            balance_sheet = 2
        else:
            balance_sheet = 0

    if free_cashflow is None and operating_cashflow is None:
        funding_resilience = 0
    elif (free_cashflow or 0) > 0 and (operating_cashflow or 0) > 0:
        funding_resilience = 5
    elif (free_cashflow or 0) > 0 or (operating_cashflow or 0) > 0:
        funding_resilience = 3
    else:
        funding_resilience = 0

    components = {
        "revenue_growth": growth,
        "profitability": profitability,
        "cash_generation": cash_generation,
        "balance_sheet": balance_sheet,
        "funding_resilience": funding_resilience,
    }
    available = sum(
        value is not None
        for value in (
            revenue_growth,
            profit_margin,
            fcf_margin,
            total_cash,
            total_debt,
            operating_cashflow,
        )
    )
    return {
        "score": sum(components.values()),
        "components": components,
        "metrics": {
            "revenue_growth": revenue_growth,
            "profit_margin": profit_margin,
            "fcf_margin": fcf_margin,
            "total_cash": total_cash,
            "total_debt": total_debt,
            "debt_to_cash": debt_to_cash,
            "free_cashflow": free_cashflow,
            "operating_cashflow": operating_cashflow,
        },
        "confidence": "HIGH" if available >= 6 else "MEDIUM" if available >= 4 else "LOW",
    }


def company_snapshot(ticker):
    company = yf.Ticker(ticker)
    info = company.info or {}
    financial = financial_strength(info)

    try:
        recent_news, source_status = fetch_external_news(ticker)
    except Exception:
        recent_news, source_status = [], {}

    headlines = [
        {
            "title": item.get("title", ""),
            "summary": item.get("summary", ""),
            "source": item.get("source", ""),
            "date": item.get("date", ""),
            "event_type": item.get("event_type", "CORPORATE_NEWS"),
        }
        for item in recent_news[:6]
    ]
    return {
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName") or ticker,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "business_summary": (info.get("longBusinessSummary") or "")[:2400],
        "financial_strength": financial,
        "recent_public_headlines": headlines,
        "source_status": source_status,
    }


def category_for(score):
    if score >= 85:
        return "A", 15000
    if score >= 70:
        return "B", 10000
    if score >= 55:
        return "C", 5000
    return "WATCHLIST", 0


def load_api_key():
    if os.getenv("OPENAI_API_KEY"):
        return
    result = subprocess.run(
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
    if result.returncode != 0 or not result.stdout.strip():
        raise SystemExit("OpenAI API key not found in macOS Keychain.")
    os.environ["OPENAI_API_KEY"] = result.stdout.strip()


def load_previous_scores():
    if not LATEST_PATH.exists():
        return {}, None
    try:
        payload = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}, None
    return {
        item["ticker"]: item
        for item in payload.get("items", [])
        if item.get("ticker")
    }, payload


def material_reassessment_reasons(snapshot, previous):
    if previous is None:
        return ["première évaluation"]

    reasons = []
    previous_financial = (
        previous.get("criteria", {}).get("financial_strength", {})
    )
    old_financial_score = previous_financial.get("score")
    new_financial_score = snapshot["financial_strength"]["score"]
    if (
        old_financial_score is not None
        and abs(new_financial_score - old_financial_score) >= 2
    ):
        reasons.append(
            f"solidité financière {old_financial_score} → {new_financial_score}"
        )

    previously_seen = set(previous.get("evidence_headlines", []))
    material_markers = (
        "quarterly results",
        "financial results",
        "earnings",
        "guidance",
        "acquisition",
        "merger",
        "financing",
        "offering",
        "debt",
        "antitrust",
        "export restriction",
        "investor day",
    )
    if previously_seen:
        for headline in snapshot.get("recent_public_headlines", []):
            title = headline.get("title", "")
            if not title or title in previously_seen:
                continue
            event_type = headline.get("event_type")
            if event_type == "QUARTERLY_RESULTS" or any(
                marker in title.lower() for marker in material_markers
            ):
                reasons.append(f"nouvel événement matériel : {title}")
                break
    return reasons


def build_scores(tickers):
    snapshots = []
    unavailable = []
    for ticker in tickers:
        try:
            snapshots.append(company_snapshot(ticker))
        except Exception as error:
            unavailable.append({"ticker": ticker, "reason": str(error)})

    if not snapshots:
        raise SystemExit("No company data available for fundamental scoring.")

    previous_items, previous_payload = load_previous_scores()
    triggers = {
        snapshot["ticker"]: material_reassessment_reasons(
            snapshot,
            previous_items.get(snapshot["ticker"]),
        )
        for snapshot in snapshots
    }
    snapshots_to_assess = [
        snapshot for snapshot in snapshots if triggers[snapshot["ticker"]]
    ]

    if not snapshots_to_assess and previous_payload:
        output = dict(previous_payload)
        output["usage"] = {"input": 0, "output": 0}
        output["reassessment_status"] = "FROZEN_NO_MATERIAL_TRIGGER"
        output["reassessed_tickers"] = []
        output["_unchanged"] = True
        return output

    load_api_key()
    prompt = f"""
Évalue la qualité structurelle des entreprises ci-dessous pour une allocation de risque.

Le score ne mesure JAMAIS le timing d'achat et ne doit tenir compte d'aucun cours,
graphique, RSI, breakout, higher low, volume ou valorisation boursière.

Attribue uniquement les quatre blocs qualitatifs suivants :
- moat et position stratégique : 0 à 25 ;
- diversification et résilience du business : 0 à 20 ;
- résilience face au risque concurrentiel/technologique : 0 à 15 ;
- résilience face aux risques spécifiques : 0 à 15.

Pour les deux blocs de risque, un score élevé signifie que le risque est faible ou bien
maîtrisé. Pénalise explicitement la concentration clients/produits/régions, les alternatives
internes développées par les clients, la géopolitique, la réglementation, les restrictions
d'exportation, la supply chain, le capex, la dette et la dilution quand ils sont matériels.

La solidité financière sur 25 est calculée séparément par des règles quantitatives : ne la
rescore pas. Appuie-toi d'abord sur les profils et données fournis. Tu peux utiliser des faits
structurels largement établis sur ces sociétés, mais baisse la confiance si un élément décisif
n'est pas étayé. Sois conservateur et discriminant ; n'accorde pas mécaniquement des scores
élevés aux grandes capitalisations.

Retourne exactement une évaluation par ticker fourni. Chaque justification tient en une phrase
courte et watch_items contient au maximum trois facteurs susceptibles de changer le score.

DONNÉES PUBLIQUES :
{json.dumps(snapshots_to_assess, ensure_ascii=False)}
"""

    response = OpenAI().responses.parse(
        model=MODEL,
        input=prompt,
        text_format=QualitativeBatch,
    )
    parsed = response.output_parsed
    if parsed is None:
        raise SystemExit("Could not parse fundamental score response.")

    assessments = {item.ticker.upper(): item for item in parsed.items}
    results = []
    for snapshot in snapshots:
        ticker = snapshot["ticker"]
        if not triggers[ticker] and ticker in previous_items:
            frozen = dict(previous_items[ticker])
            frozen["stability"] = {
                "status": "FROZEN_NO_MATERIAL_TRIGGER",
                "reason": "Aucun résultat trimestriel, événement structurel ou changement financier matériel détecté.",
            }
            results.append(frozen)
            continue

        assessment = assessments.get(ticker)
        if assessment is None:
            unavailable.append({"ticker": ticker, "reason": "AI assessment missing"})
            continue

        financial = snapshot["financial_strength"]
        total = (
            assessment.moat
            + financial["score"]
            + assessment.diversification
            + assessment.competitive_resilience
            + assessment.specific_risk_resilience
        )
        category, max_exposure = category_for(total)
        confidence = assessment.confidence
        if financial["confidence"] == "LOW":
            confidence = "LOW"
        elif financial["confidence"] == "MEDIUM" and confidence == "HIGH":
            confidence = "MEDIUM"

        results.append({
            "ticker": ticker,
            "company": snapshot["name"],
            "score": total,
            "category": category,
            "max_exposure_usd": max_exposure,
            "confidence": confidence,
            "criteria": {
                "moat": {
                    "score": assessment.moat,
                    "max": 25,
                    "reason": assessment.moat_reason,
                },
                "financial_strength": {
                    "score": financial["score"],
                    "max": 25,
                    "reason": "Score quantitatif fondé sur croissance, marges, cash-flow, bilan et autonomie de financement.",
                    "components": financial["components"],
                    "metrics": financial["metrics"],
                },
                "diversification": {
                    "score": assessment.diversification,
                    "max": 20,
                    "reason": assessment.diversification_reason,
                },
                "competitive_resilience": {
                    "score": assessment.competitive_resilience,
                    "max": 15,
                    "reason": assessment.competitive_reason,
                },
                "specific_risk_resilience": {
                    "score": assessment.specific_risk_resilience,
                    "max": 15,
                    "reason": assessment.specific_risks_reason,
                },
            },
            "watch_items": assessment.watch_items[:3],
            "source_status": snapshot["source_status"],
            "evidence_headlines": [
                headline.get("title", "")
                for headline in snapshot.get("recent_public_headlines", [])
                if headline.get("title")
            ],
            "stability": {
                "status": "REASSESSED_ON_MATERIAL_TRIGGER",
                "reasons": triggers[ticker],
            },
        })

    usage = response.usage
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "method": "fundamental_risk_score_v1",
        "portfolio_envelope_usd": 50000,
        "items": sorted(results, key=lambda item: item["score"], reverse=True),
        "unavailable": unavailable,
        "usage": {
            "input": usage.input_tokens if usage else 0,
            "output": usage.output_tokens if usage else 0,
        },
        "reassessment_status": "MATERIAL_REASSESSMENT",
        "reassessed_tickers": sorted(
            ticker for ticker, reasons in triggers.items() if reasons
        ),
    }


def save_output(output):
    HISTORY_DIR.mkdir(exist_ok=True)
    content = json.dumps(output, ensure_ascii=False, indent=2)
    LATEST_PATH.write_text(content, encoding="utf-8")
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
    (HISTORY_DIR / f"fundamental_scores_{stamp}.json").write_text(
        content,
        encoding="utf-8",
    )

    usage = output.get("usage", {})
    cost = (
        int(usage.get("input", 0)) * 0.20
        + int(usage.get("output", 0)) * 1.20
    ) / 1_000_000
    spent_path = HISTORY_DIR / "openai_spent.txt"
    previous = float(spent_path.read_text().strip()) if spent_path.exists() else 0.0
    spent_path.write_text(f"{previous + cost:.8f}", encoding="utf-8")
    return cost


def main():
    output = build_scores(WATCHLIST)
    unchanged = output.pop("_unchanged", False)
    cost = 0.0 if unchanged else save_output(output)
    output["estimated_cost_usd"] = cost
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
