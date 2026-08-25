import html
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import streamlit as st
from config import WATCHLIST

HERE = Path(__file__).resolve().parent
FRENCH_MONTHS = (
    "janv.", "févr.", "mars", "avr.", "mai", "juin",
    "juil.", "août", "sept.", "oct.", "nov.", "déc.",
)
AI_BIOTECH_TICKERS = {"SDGR", "RXRX", "ABSI"}
NEWS_IMPACT_LABELS = {
    "POSITIVE": "positif",
    "NEGATIVE": "négatif",
    "MIXED": "mitigé",
    "UNCLEAR": "incertain",
}


def stock_section(ticker):
    return "IA-biotech" if ticker in AI_BIOTECH_TICKERS else "IA"


def ticker_is_visible(ticker, universe):
    return stock_section(ticker) == universe

def fr(text):
    replacements = {
        "VERIFY - HIGH UNCERTAINTY": "À VÉRIFIER - FORTE INCERTITUDE",
        "WAIT - BETTER ENTRY": "ATTENDRE - MEILLEURE ENTRÉE",
        "WAIT FOR BETTER ENTRY": "ATTENDRE UNE MEILLEURE ENTRÉE",
        "WATCH - VERIFY FUNDAMENTALS": "À SURVEILLER - VÉRIFIER LES FONDAMENTAUX",
        "OVERHEATED - DO NOT CHASE": "SURCHAUFFE - NE PAS POURSUIVRE LA HAUSSE",
        "POSITIVE MOMENTUM - PRICE EXTENDED": "DYNAMIQUE HAUSSIÈRE - PRIX TENDU",
        "ATTRACTIVE - PRICE EXTENDED": "ATTRACTIF - PRIX TENDU",
        "WATCH - PRICE EXTENDED": "À SURVEILLER - PRIX TENDU",
        "ATTRACTIVE - BUT MONITOR NEWS": "ATTRACTIF - SURVEILLER LES ACTUALITÉS",
        "ATTRACTIVE - MONITOR": "ATTRACTIF - À SURVEILLER",
        "POSITIVE MOMENTUM": "DYNAMIQUE HAUSSIÈRE",
        "WATCH - PULLBACK": "À SURVEILLER - REPLI",
        "PULLBACK OPPORTUNITY": "OPPORTUNITÉ SUR REPLI",
        "CAUTION - NEGATIVE NEWS": "PRUDENCE - ACTUALITÉS NÉGATIVES",
        "CAUTION - WEAK FUNDAMENTALS": "PRUDENCE - FONDAMENTAUX FAIBLES",
        "CAUTION - WEAK TECHNICALS": "PRUDENCE - TECHNIQUE FAIBLE",
        "WAIT FOR COOLING": "ATTENDRE UN MEILLEUR POINT D’ENTRÉE",
        "ATTRACTIVE SETUP": "CONFIGURATION ATTRACTIVE",
        "— ATTRACTIVE": "— ATTRACTIF",
        "INCOMPLETE": "INCOMPLET",
        "NOT CONFIGURED": "NON CONFIGURÉ",
        "UNAVAILABLE": "INDISPONIBLE",
        "POSITIVE": "POSITIVES",
        "NEGATIVE": "NÉGATIVES",
        "MIXED": "MITIGÉES",
        "NEUTRAL": "NEUTRE",
        "UNCLEAR": "INCERTAIN",
        "STRONG": "FORT",
        "WEAK": "FAIBLE",
        "NEARBY": "PROCHE",
        "DISTANT": "ÉLOIGNÉ",
        "HIGH": "ÉLEVÉE",
        "MEDIUM": "MOYENNE",
        "LOW": "FAIBLE",
        "WATCH": "À SURVEILLER",
        "away": "d’écart",
        "1 touches": "1 contact",
        "touches": "contacts",
    }
    result = str(text)
    for old, new in replacements.items():
        result = result.replace(old, new)
    return result


def section_heading(text, level=3):
    st.markdown(
        f'<h{level} class="section-heading">{text}</h{level}>',
        unsafe_allow_html=True,
    )


def section_gap():
    st.markdown(
        '<div class="section-gap" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )


def report_timestamp(path):
    match = re.fullmatch(
        r"report_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.txt",
        path.name,
    )
    if match:
        return datetime.strptime(match.group(1), "%Y-%m-%d_%H-%M-%S")
    return datetime.fromtimestamp(path.stat().st_mtime)


def french_datetime(value):
    return (
        f"{value.day} {FRENCH_MONTHS[value.month - 1]} {value.year} "
        f"à {value.hour:02d}:{value.minute:02d}"
    )


def parsed_datetime(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def usd_amount(value):
    try:
        return f"{int(value):,} $".replace(",", " ")
    except (TypeError, ValueError):
        return "Surveillance uniquement"


def current_verdict(report, ticker):
    lines = report.splitlines()
    inside = False
    for line in lines:
        if line.startswith("#"):
            inside = f" {ticker} " in line
        elif inside and line.strip().startswith("Verdict:"):
            return line.split(":", 1)[1].strip()
    return ""

def report_tickers(report):
    tickers = []
    for line in (report or "").splitlines():
        if line.startswith("#") and "—" in line:
            left = line.split("—", 1)[0].split()
            if left:
                tickers.append(left[-1])
    return tickers or WATCHLIST

def verdict_icon(verdict):
    if "ATTRACTIVE" in verdict:
        return "🟢"
    if "PRICE EXTENDED" in verdict or "PULLBACK" in verdict:
        return "🟡"
    if "VERIFY FUNDAMENTALS" in verdict:
        return "🟠🔴"
    if "CAUTION" in verdict:
        return "🔴"
    return "⚪"

def rsi_label(value):
    try:
        rsi = float(value)
    except (TypeError, ValueError):
        return "⚪ Indisponible"
    if rsi >= 70:
        return "🟠 Prix tendu"
    if rsi >= 65:
        return "🟡 Zone neutre haute — proche du seuil de tension"
    if rsi <= 30:
        return "🔵 Faible / survendu"
    return "⚪ Zone neutre"


def concise_explanation(value):
    return re.sub(
        r"^Le verdict (?:est|reste)\s+«[^»]+»\s*:\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )


def earnings_label(item):
    if not item or item.get("status") == "UNAVAILABLE" or not item.get("date"):
        return "📅 Prochains résultats : date indisponible"
    return (
        f"📅 Prochains résultats : {earnings_timezone_label(item, include_year=True)} "
        f"· {earnings_comparison_text(item)} · date indicative"
    )


def earnings_days_until(item):
    try:
        days = (date.fromisoformat(item["date"]) - date.today()).days
        return days if days >= 0 else None
    except (KeyError, TypeError, ValueError):
        return None


def _earnings_date_text(raw_value, include_year=False):
    try:
        value = date.fromisoformat(raw_value)
    except (TypeError, ValueError):
        return "date indisponible"
    text = f"{value.day} {FRENCH_MONTHS[value.month - 1]}"
    return f"{text} {value.year}" if include_year else text


def earnings_timezone_label(item, include_year=False, include_times=True, compact=False):
    if not item:
        return "date indisponible"
    us_date = _earnings_date_text(
        item.get("date_us") or item.get("date"),
        include_year,
    )
    singapore_date = _earnings_date_text(
        item.get("date_singapore") or item.get("date"),
        include_year,
    )
    us_time = item.get("time_us")
    singapore_time = item.get("time_singapore")
    us_suffix = f" {us_time} ET" if include_times and us_time else ""
    singapore_suffix = (
        f" {singapore_time}" if include_times and singapore_time else ""
    )
    singapore_label = "SG" if compact else "Singapour"
    return (
        f"{us_date}{us_suffix} US / "
        f"{singapore_date}{singapore_suffix} {singapore_label}"
    )


def earnings_risk_icon(days):
    if days <= 7:
        return "🔴"
    if days <= 14:
        return "🟠"
    if days <= 30:
        return "🟡"
    return "⚪"


def positioning_summary(view, earnings_days):
    if "CAUTION" in view:
        return "RESTER À L’ÉCART", "red"
    if "VERIFY FUNDAMENTALS" in view:
        return "VÉRIFIER AVANT D’AGIR", "orange"
    if "PRICE EXTENDED" in view:
        return "ATTENDRE UN MEILLEUR POINT D’ENTRÉE", "orange"
    if view == "WATCH - PULLBACK":
        return "ATTENDRE UNE CONFIRMATION", "yellow"
    if view == "ATTRACTIVE SETUP":
        if earnings_days is not None and earnings_days <= 7:
            return "ATTENDRE LES RÉSULTATS", "orange"
        if earnings_days is not None and earnings_days <= 14:
            return "SURVEILLER AVANT LES RÉSULTATS", "yellow"
        return "CONFIGURATION FAVORABLE — OPPORTUNITÉ À ÉTUDIER", "green"
    if "ATTRACTIVE" in view:
        return "SURVEILLER AVANT D’AGIR", "yellow"
    return "SURVEILLER", "yellow"


def has_confirmed_trigger(item):
    return (item or {}).get("setup_type") in (
        "HIGHER LOW",
        "BREAKOUT",
        "RETOURNEMENT CONFIRMÉ",
        "PULLBACK CONFIRMÉ",
        "STABILISATION CONFIRMÉE",
    )


def technical_signal_ready(item):
    item = item or {}
    score = item.get("score", 0)
    setup_type = item.get("setup_type")
    if setup_type in ("RETOURNEMENT CONFIRMÉ", "PULLBACK CONFIRMÉ"):
        return score >= 60
    return score >= 65 and has_confirmed_trigger(item)


def technical_blocker_text(item):
    item = item or {}
    score = item.get("score", 0)
    setup_type = item.get("setup_type", "AUCUN")
    if setup_type == "RETOURNEMENT":
        return "retournement à confirmer une séance"
    if setup_type == "PULLBACK FAVORABLE":
        return "zone de pullback favorable · reprise à confirmer"
    if setup_type == "HIGHER LOW À CONFIRMER":
        return "higher low valide · attendre une clôture confirmant le rebond"
    if setup_type == "CHOC EN STABILISATION":
        return "choc à fort volume · attendre deux séances de stabilisation"
    if setup_type == "BREAKOUT FAIBLE":
        return "breakout non confirmé par le volume"
    if setup_type in ("RETOURNEMENT CONFIRMÉ", "PULLBACK CONFIRMÉ") and score < 60:
        return f"technique {score}/100, seuil d’entrée progressive 60"
    if score < 65:
        return f"technique {score}/100, seuil standard 65"
    return "déclencheur technique non confirmé"


def technical_setup_label(score, setup_type=None):
    try:
        value = int(score)
    except (TypeError, ValueError):
        return "INDISPONIBLE"
    confirmed = setup_type in (
        "HIGHER LOW",
        "BREAKOUT",
        "RETOURNEMENT CONFIRMÉ",
        "PULLBACK CONFIRMÉ",
        "STABILISATION CONFIRMÉE",
    )
    if setup_type in ("RETOURNEMENT CONFIRMÉ", "PULLBACK CONFIRMÉ") and value >= 60:
        return "EARLY SETUP"
    if confirmed and value >= 85:
        return "EXCEPTIONAL SETUP"
    if confirmed and value >= 75:
        return "VERY GOOD SETUP"
    if confirmed and value >= 65:
        return "GOOD SETUP"
    if value >= 50:
        return "WATCH"
    return "WAIT"


POSITIVE_VALUATIONS = {"TRÈS ATTRACTIVE", "ATTRACTIVE"}
CAUTION_VALUATIONS = {"UN PEU EXIGEANTE", "PRIME MODÉRÉE", "CHÈRE"}
BLOCKING_VALUATIONS = {"PRIME ÉLEVÉE", "TRÈS CHÈRE", "INDISPONIBLE"}


def valuation_is_positive(label):
    return label in POSITIVE_VALUATIONS


def valuation_is_blocking(label):
    return label in BLOCKING_VALUATIONS


def structured_positioning(technical_item, fundamental_item, valuation_item, days):
    fundamental_score = (fundamental_item or {}).get("score")
    max_exposure = (fundamental_item or {}).get("max_exposure_usd", 0)
    valuation_label = (valuation_item or {}).get("label", "INDISPONIBLE")
    score = (technical_item or {}).get("score", 0)
    phase = (technical_item or {}).get("phase")

    if fundamental_score is None or fundamental_score < 55 or max_exposure <= 0:
        return "SURVEILLANCE UNIQUEMENT — RISQUE FONDAMENTAL", "orange"
    if valuation_is_blocking(valuation_label):
        return "ATTENDRE — VALORISATION NON FAVORABLE", "orange"
    if days is not None and days <= 7:
        return "ATTENDRE LES RÉSULTATS", "orange"
    if technical_signal_ready(technical_item):
        if (technical_item or {}).get("setup_type") in (
            "RETOURNEMENT CONFIRMÉ",
            "PULLBACK CONFIRMÉ",
        ):
            return "ENTRÉE PROGRESSIVE À ÉTUDIER", "green"
        return "CONFIGURATION FAVORABLE — OPPORTUNITÉ À ÉTUDIER", "green"
    if phase == "RETOURNEMENT À CONFIRMER":
        return "SURVEILLER — RETOURNEMENT À CONFIRMER", "yellow"
    if phase == "ZONE DE PULLBACK FAVORABLE":
        return "SURVEILLER — ZONE DE PULLBACK FAVORABLE", "yellow"
    if phase == "STABILISATION APRÈS CHOC EN COURS":
        return "SURVEILLER — STABILISATION APRÈS CHOC", "yellow"
    if phase == "BREAKOUT À CONFIRMER":
        return "SURVEILLER — BREAKOUT SANS VOLUME", "yellow"
    if phase == "HIGHER LOW EN FORMATION":
        return "SURVEILLER — HIGHER LOW EN FORMATION", "yellow"
    if phase == "HIGHER LOW À CONFIRMER":
        return "SURVEILLER — REBOND DU HIGHER LOW À CONFIRMER", "yellow"
    if score >= 50:
        return "SURVEILLER — CONFIRMATION TECHNIQUE MANQUANTE", "yellow"
    return "ATTENDRE UN SIGNAL TECHNIQUE", "yellow"


def structured_technical_reading(item):
    if not item:
        return "Données techniques structurées indisponibles."
    trend = item.get("trend_regime", "indisponible")
    phase = item.get("phase", "indisponible")
    components = item.get("components", {})
    trigger = components.get("trigger", {}).get("detail", "")
    volume = components.get("volume", {}).get("detail", "")
    return (
        f"Tendance de fond : {trend}. Phase actuelle : {phase}. "
        f"{trigger}. {volume}. "
        f"Timing technique : {item.get('score', 'N/A')}/100 — "
        f"{technical_setup_label(item.get('score'), item.get('setup_type'))}."
    )


def level_distance(value, direction):
    match = re.search(r"([0-9.]+)% away", value or "")
    if not match:
        return "N/A"
    sign = "-" if direction == "support" else "+"
    return f"{sign}{match.group(1)} %"


def valuation_metrics_text(item):
    if not item:
        return "Données indisponibles"
    metrics = item.get("metrics", {})
    parts = []
    forward_pe = metrics.get("forward_pe")
    price_to_sales = metrics.get("price_to_sales")
    enterprise_to_revenue = metrics.get("enterprise_to_revenue")
    historical_pe = metrics.get("historical_pe_median")
    peer_median = metrics.get("peer_median")
    if item.get("method") == "PROFITABLE" and forward_pe is not None and forward_pe > 0:
        parts.append(f"P/E forward {forward_pe:.1f}x")
    if item.get("method") != "PROFITABLE" and price_to_sales is not None:
        parts.append(f"P/S {price_to_sales:.1f}x")
    if item.get("method") != "PROFITABLE" and enterprise_to_revenue is not None:
        parts.append(f"EV/Sales {enterprise_to_revenue:.1f}x")
    if item.get("method") == "PROFITABLE" and historical_pe is not None:
        parts.append(f"P/E historique médian {historical_pe:.1f}x")
    if peer_median is not None:
        multiple_name = "P/E pairs" if item.get("method") == "PROFITABLE" else "P/S pairs"
        parts.append(f"{multiple_name} {peer_median:.1f}x")
    return " · ".join(parts) or "Données insuffisantes"


def valuation_transparency_text(item):
    if not item:
        return "Méthodologie indisponible"
    score = item.get("score")
    coverage = item.get("coverage_pct")
    confidence = item.get("confidence", "LOW")
    confidence_label = {
        "HIGH": "élevée",
        "MEDIUM": "moyenne",
        "LOW": "faible",
    }.get(confidence, str(confidence).lower())
    parts = [
        f"Score {score}/100" if score is not None else "Score indisponible",
        f"couverture {coverage}%" if coverage is not None else "couverture inconnue",
        f"confiance {confidence_label}",
    ]
    components = item.get("components", {})
    component_labels = {
        "own_history": "historique propre",
        "peers": "pairs",
        "growth_adjusted": "croissance ajustée",
        "cash_flow": "cash-flow",
    }
    available = [
        f"{component_labels.get(name, name)} {component.get('score')}/100"
        for name, component in components.items()
        if component.get("available") and component.get("score") is not None
    ]
    if available:
        parts.append(" · ".join(available))
    return " — ".join(parts)


def decimal_fr(value, digits=2):
    try:
        return f"{float(value):.{digits}f}".replace(".", ",")
    except (TypeError, ValueError):
        return "N/A"


def valuation_audit_text(item):
    if not item:
        return "Source indisponible"
    metrics = item.get("metrics", {})
    price = metrics.get("price_used")
    forward_eps = metrics.get("forward_eps_ntm")
    currency = metrics.get("currency") or "USD"
    source = metrics.get("source") or "Source indisponible"
    raw_date = metrics.get("price_date")
    try:
        source_date = date.fromisoformat(raw_date)
        date_text = (
            f"{source_date.day} {FRENCH_MONTHS[source_date.month - 1]} "
            f"{source_date.year}"
        )
    except (TypeError, ValueError):
        date_text = "date indisponible"

    if price is not None and forward_eps is not None and forward_eps > 0:
        return (
            f"Prix {decimal_fr(price)} {currency} / "
            f"EPS NTM {decimal_fr(forward_eps)} {currency} — "
            f"{source} — séance du {date_text}"
        )
    return f"Calcul détaillé indisponible — {source} — {date_text}"


def score_evolution_text(item):
    history = (item or {}).get("score_history", [])
    scores = [str(point.get("score")) for point in history if point.get("score") is not None]
    if not scores and item and item.get("score") is not None:
        scores = [str(item["score"])]
    text = " → ".join(scores) + "/100" if scores else "N/A"
    if (item or {}).get("rapid_improvement"):
        text += " · ↗ amélioration rapide"
    return text


def fundamental_evolution_text(ticker, item):
    scores = fundamental_score_history.get(ticker, [])
    if not scores and item and item.get("score") is not None:
        scores = [item["score"]]
    evolution = " → ".join(str(score) for score in scores[-3:])
    category = (item or {}).get("category", "—")
    return f"{evolution}/100 · {category}" if evolution else "N/A"


def earnings_comparison_text(item):
    days = earnings_days_until(item or {})
    if days is None:
        return "Date indisponible"
    if days == 0:
        return "Aujourd’hui"
    return f"J-{days}"


def compact_max_exposure(value):
    try:
        amount = int(value)
    except (TypeError, ValueError):
        return "—"
    return f"{amount // 1000}k" if amount > 0 else "—"


def comparison_action_label(
    technical_item,
    fundamental_item,
    valuation_item,
    earnings_item,
):
    earnings_days = earnings_days_until(earnings_item or {})
    action, color = structured_positioning(
        technical_item,
        fundamental_item,
        valuation_item,
        earnings_days,
    )
    if color == "green":
        return "Étudier une entrée", True
    if "SURVEILLER" in action:
        return "Surveiller", False
    return "Attendre", False


def comparison_cell(value, css_class=""):
    class_attribute = f' class="{css_class}"' if css_class else ""
    return f"<td{class_attribute}>{html.escape(str(value))}</td>"


def fundamental_max_cell(fundamental_text, max_text, positive=False):
    fundamental_class = ' class="positive"' if positive else ""
    return (
        f"<td><span{fundamental_class}>"
        f"{html.escape(str(fundamental_text))}</span>"
        f"<span> → {html.escape(str(max_text))}</span></td>"
    )


def render_change_list(changes, report, selected_universe):
    change_lines = {
        line[2:].split(":", 1)[0].strip(): line
        for line in changes.splitlines()
        if line.startswith("- ")
    }
    rendered = 0
    for ticker in report_tickers(report):
        if not ticker_is_visible(ticker, selected_universe):
            continue
        if ticker not in change_lines:
            continue
        line = change_lines[ticker]
        raw_changes = line.split(":", 1)[1].strip().split(" | ")
        facts = []
        for raw_change in raw_changes:
            if raw_change == "new ticker":
                facts.append("Nouveau titre ajouté")
                continue

            match = re.fullmatch(
                r"technical score (-?\d+) (?:->|→) (-?\d+)",
                raw_change,
            )
            if match:
                before, now = match.groups()
                facts.append(f"Score technique : {before} → {now}")
                continue

            match = re.fullmatch(
                r"technical band (.+) (?:->|→) (.+)",
                raw_change,
            )
            if match:
                before, now = match.groups()
                facts.append(f"Statut technique : {before} → {now}")
                continue

            match = re.fullmatch(r"setup (.+) (?:->|→) (.+)", raw_change)
            if match:
                before, now = match.groups()
                if before == "AUCUN":
                    facts.append(f"Nouveau setup détecté : {now}")
                elif now == "AUCUN":
                    facts.append(f"Setup {before} invalidé")
                else:
                    facts.append(f"Type de setup : {before} → {now}")
                continue

            match = re.fullmatch(
                r"valuation (.+) (?:->|→) (.+)",
                raw_change,
            )
            if match:
                before, now = match.groups()
                facts.append(f"Valorisation : {fr(before)} → {fr(now)}")
                continue

            match = re.fullmatch(
                r"earnings date ([0-9-]+) (?:->|→) ([0-9-]+)",
                raw_change,
            )
            if match:
                before, now = match.groups()
                facts.append(f"Date des résultats modifiée : {before} → {now}")
                continue

            match = re.fullmatch(r"earnings now J-(\d+)", raw_change)
            if match:
                facts.append(f"Résultats désormais à J-{match.group(1)}")
                continue

            match = re.fullmatch(
                r"news: (\S+) (?:->|→) (\S+)",
                raw_change,
            )
            if match:
                before, now = match.groups()
                facts.append(f"Actualités : {fr(before)} → {fr(now)}")
                continue

            match = re.fullmatch(r"price ([+-][0-9.]+)%", raw_change)
            if match:
                facts.append(f"Variation du cours : {match.group(1)} %")
                continue

            if raw_change.startswith("fundamentals:"):
                facts.append(
                    raw_change.replace("fundamentals:", "Fondamental :")
                    .replace(" -> ", " → ")
                )
                continue

            facts.append(raw_change.replace(" -> ", " → "))

        st.markdown(f"- **{ticker}** — " + " · ".join(facts) + ".")
        rendered += 1
    return rendered


def numeric_level_distance(value):
    match = re.search(r"([0-9.]+)% away", value or "")
    return float(match.group(1)) if match else None


def critical_alerts(
    fields,
    earnings_days,
    technical_item,
    audit_item,
    signal_record=None,
):
    alerts = []
    if earnings_days is not None and earnings_days <= 7:
        alerts.append(f"⚠ Résultats J-{earnings_days}")

    resistance = numeric_level_distance(fields.get("Resistance"))
    if resistance is not None and resistance <= 2:
        alerts.append(f"⚠ Résistance +{resistance:.1f} %")

    components = (technical_item or {}).get("components", {})
    trigger = components.get("trigger", components.get("breakout", {}))
    volume = components.get("volume", {})
    if (technical_item or {}).get("setup_type") in (
        "BREAKOUT",
        "BREAKOUT FAIBLE",
    ) and trigger.get(
        "score", 0
    ) >= 8 and (
        volume.get("score", 0) <= 5
        or "faible" in volume.get("detail", "").lower()
    ):
        alerts.append("⚠ Breakout non confirmé : volume faible")

    if (technical_item or {}).get("rapid_improvement"):
        alerts.append("↗ Setup en amélioration rapide")
    if technical_signal_ready(technical_item):
        alerts.append("Condition d’exécution : ne pas poursuivre une ouverture > +2 %")
    if signal_record and signal_record.get("signal_event"):
        role = signal_record.get("signal_role")
        if role == "NOUVELLE_OPPORTUNITÉ":
            alerts.append("Nouveau signal indépendant")
        elif role == "RENFORCEMENT_ÉVENTUEL":
            alerts.append("Signal répété : renforcement éventuel, pas nouvelle entrée")
    execution = (signal_record or {}).get("execution") or {}
    if execution.get("status") == "ANNULER_GAP":
        alerts.append(f"Annuler : gap d’ouverture {execution.get('gap_pct', 0):+.1f} %")
    elif execution.get("status") == "ANNULER_INVALIDATION":
        alerts.append("Annuler : niveau d’invalidation déjà cassé à l’ouverture")
    elif execution.get("status") == "EXÉCUTION_PROGRESSIVE_POSSIBLE":
        alerts.append(
            f"Ouverture compatible avec le signal ({execution.get('gap_pct', 0):+.1f} %)"
        )
    if audit_item and audit_item.get("status") == "REVIEW":
        alerts.append("⚠ Données de marché à vérifier")
    return alerts


def event_risk_summary(days):
    if days is None:
        return "INCONNU", "Date indisponible"
    event_detail = "Résultats aujourd’hui" if days == 0 else f"Résultats dans {days} jours"
    if days <= 7:
        return "ÉLEVÉ", event_detail
    if days <= 14:
        return "MODÉRÉ", event_detail
    if days <= 30:
        return "MODÉRÉ", event_detail
    return "FAIBLE", event_detail


def news_date_label(value):
    if not value:
        return "Date de publication indisponible"
    try:
        published = date.fromisoformat(value)
    except (TypeError, ValueError):
        return "Date de publication indisponible"
    months = (
        "janv.", "févr.", "mars", "avr.", "mai", "juin",
        "juil.", "août", "sept.", "oct.", "nov.", "déc.",
    )
    date_text = f"{published.day} {months[published.month - 1]} {published.year}"
    age = max((date.today() - published).days, 0)
    if age == 0:
        freshness = "aujourd’hui"
    elif age == 1:
        freshness = "hier"
    else:
        freshness = f"il y a {age} jours"
    stale = " · ⚠️ actualité ancienne" if age > 14 else ""
    return f"Publié le {date_text} · {freshness}{stale}"

def entry_change_summary(line, report):
    raw = line[2:] if line.startswith("- ") else line
    ticker = raw.split(":", 1)[0].strip()
    verdict = current_verdict(report, ticker)

    change = None
    if "price " in raw:
        try:
            change = float(raw.split("price ", 1)[1].split("%", 1)[0])
        except ValueError:
            pass

    if "verdict:" in raw:
        verdict_change = raw.split("verdict:", 1)[1].strip()
        old_verdict, new_verdict = [x.strip() for x in verdict_change.split("->", 1)]

        ranks = {
            "CAUTION - WEAK FUNDAMENTALS": 1,
            "CAUTION - NEGATIVE NEWS": 1,
            "CAUTION - WEAK TECHNICALS": 1,
            "WATCH - VERIFY FUNDAMENTALS": 2,
            "WAIT FOR BETTER ENTRY": 3,
            "WATCH": 3,
            "WATCH - PULLBACK": 3,
            "WATCH - PRICE EXTENDED": 3,
            "WATCH - PULLBACK OPPORTUNITY": 4,
            "ATTRACTIVE - PRICE EXTENDED": 5,
            "ATTRACTIVE - BUT MONITOR NEWS": 5,
            "ATTRACTIVE SETUP": 6,
        }

        old_rank = ranks.get(old_verdict, 3)
        new_rank = ranks.get(new_verdict, 3)

        if old_verdict == "WAIT FOR BETTER ENTRY" and new_verdict == "WATCH":
            return "🟢", "La situation s’améliore : il n’y a plus de raison technique forte d’attendre une baisse avant d’envisager une entrée."

        if old_verdict == "INCOMPLETE DATA" and new_verdict == "WATCH - VERIFY FUNDAMENTALS":
            return "🟠", "L’analyse est maintenant plus précise, mais les fondamentaux restent trop incertains pour conclure."

        if new_rank > old_rank:
            return "🟢", "La situation s’améliore : le titre devient plus intéressant pour envisager un achat."

        if new_rank < old_rank:
            if new_rank <= 2:
                return "🔴", "La situation se dégrade : la prudence devient plus importante."
            return "🟠", "La situation devient un peu moins favorable pour une nouvelle entrée."

        if new_verdict == "ATTRACTIVE - PRICE EXTENDED":
            return "🟠", "Le dossier reste attractif, mais le prix est maintenant plus tendu."

        if new_verdict == "WATCH - PRICE EXTENDED":
            return "🟠", "La tendance reste à surveiller et le prix est actuellement tendu."

    if "news:" in raw:
        news_change = raw.split("news:", 1)[1].split(" | ", 1)[0].strip()
        old_news, new_news = [x.strip() for x in news_change.split("->", 1)]
        news_ranks = {
            "NEGATIVE": 0,
            "NEUTRAL": 1,
            "MIXED": 1,
            "POSITIVE": 2,
        }
        if news_ranks.get(new_news, 1) > news_ranks.get(old_news, 1):
            return "🟢", "Les actualités deviennent plus favorables pour le dossier."
        if news_ranks.get(new_news, 1) < news_ranks.get(old_news, 1):
            return "🟠", "Les actualités deviennent moins favorables et méritent davantage de surveillance."
        return "🟠", "La tonalité des actualités a changé, sans modifier clairement l’intérêt du titre."

    if change is not None:
        if change > 5:
            return "🔴", "Le cours a fortement monté : le prix est maintenant moins intéressant pour acheter."

        if change < 0 and (
            "WAIT FOR BETTER ENTRY" in verdict
            or "PRICE EXTENDED" in verdict
        ):
            return "🟢", "Le cours baisse : le prix devient un peu plus intéressant pour une entrée."

        if change > 0 and "WATCH - VERIFY FUNDAMENTALS" in verdict:
            return "🟠", "Le cours monte, mais cela ne rend pas l’achat plus intéressant pour le moment."

        if change > 0:
            return "🟠", "Le cours a légèrement monté, sans changement important pour envisager un achat."

        if change < 0:
            return "🟠", "Le cours baisse légèrement, mais cela ne suffit pas encore à rendre l’achat plus intéressant."

    return "🟠", "Pas de changement important concernant l’intérêt d’un achat pour le moment."

st.set_page_config(
    page_title="Simon AI Stock Watchlist",
    page_icon="📈",
    layout="wide",
)

st.markdown(
    """
    <style>
    .positioning-card {
        border: 1px solid;
        border-left-width: 7px;
        border-radius: 0.75rem;
        font-size: 1.05rem;
        font-weight: 700;
        letter-spacing: 0.01em;
        margin: 0.15rem 0 1rem;
        padding: 1rem 1.15rem;
    }
    .positioning-card.green {
        background: #ecfdf3;
        border-color: #16a34a;
        color: #166534;
    }
    .positioning-card.yellow {
        background: #fffbeb;
        border-color: #eab308;
        color: #854d0e;
    }
    .positioning-card.orange {
        background: #fff7ed;
        border-color: #f97316;
        color: #9a3412;
    }
    .positioning-card.red {
        background: #fef2f2;
        border-color: #dc2626;
        color: #991b1b;
    }
    .express-decision {
        border: 1px solid;
        border-left-width: 8px;
        border-radius: 0.75rem;
        margin-bottom: 1rem;
        padding: 1.15rem 1.25rem;
    }
    .express-decision.warning {
        background: #fff8db;
        border-color: #d4a000;
        color: #765800;
    }
    .express-decision.success {
        background: #eaf9ef;
        border-color: #16a34a;
        color: #14532d;
    }
    .express-decision-title {
        font-size: 1.2rem;
        font-weight: 850;
        letter-spacing: 0.015em;
        line-height: 1.35;
    }
    .express-decision-subtitle {
        font-size: 0.92rem;
        font-weight: 600;
        margin-top: 0.4rem;
    }
    .express-checks {
        display: grid;
        gap: 0.65rem;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        margin: 0.75rem 0 1rem;
    }
    .express-check {
        border: 1px solid rgba(110, 118, 129, 0.38);
        border-radius: 0.65rem;
        min-width: 0;
        padding: 0.72rem 0.8rem;
    }
    .express-check-label {
        color: #8b9099;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.03em;
        text-transform: uppercase;
    }
    .express-check-value {
        font-size: 1rem;
        font-weight: 800;
        margin-top: 0.18rem;
        overflow-wrap: anywhere;
    }
    .express-check-status {
        color: #8b9099;
        font-size: 0.74rem;
        margin-top: 0.18rem;
    }
    .express-check.pass .express-check-value,
    .express-check.pass .express-check-status {
        color: #15803d;
    }
    .express-check.block .express-check-status {
        color: #b45309;
        font-weight: 700;
    }
    .express-check.caution .express-check-value,
    .express-check.caution .express-check-status {
        color: #b45309;
    }
    .st-key-earnings_calendar_panel {
        border: 2px solid rgba(110, 118, 129, 0.48) !important;
        border-radius: 0.8rem !important;
    }
    .st-key-universe_filter_panel {
        border: 2px solid rgba(110, 118, 129, 0.48) !important;
        border-radius: 0.8rem !important;
    }
    .earnings-row {
        align-items: baseline;
        display: flex;
        gap: 0.5rem;
        justify-content: space-between;
        margin: 0.12rem 0;
    }
    .earnings-main {
        font-size: 0.82rem;
        font-weight: 700;
        white-space: nowrap;
    }
    .earnings-date {
        color: #737780;
        font-size: 0.66rem;
        line-height: 1.15;
        text-align: right;
    }
    .comparison-wrap {
        overflow-x: auto;
        width: 100%;
    }
    .comparison-table {
        border-collapse: collapse;
        color: inherit;
        font-size: 0.82rem;
        width: 100%;
    }
    .comparison-table th,
    .comparison-table td {
        border-bottom: 1px solid rgba(110, 118, 129, 0.25);
        padding: 0.65rem 0.55rem;
        text-align: left;
        vertical-align: middle;
        white-space: nowrap;
    }
    .comparison-table th {
        color: #5f636b;
        font-weight: 700;
    }
    .comparison-table .positive {
        color: #15803d;
        font-weight: 800;
    }
    .comparison-table .near-event {
        color: inherit;
        font-weight: 800;
    }
    .st-key-express_summary_panel {
        border: 3px solid rgba(90, 98, 108, 0.62) !important;
        border-radius: 0.8rem !important;
    }
    .section-heading {
        text-decoration-line: underline;
        text-decoration-color: #000000;
        text-decoration-thickness: 2px;
        text-underline-offset: 7px;
    }
    .section-gap {
        height: 1.25rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

earnings_path = HERE / "history" / "earnings_calendar_latest.json"
earnings_items = {}
if earnings_path.exists():
    try:
        earnings_items = json.loads(
            earnings_path.read_text(encoding="utf-8")
        ).get("items", {})
    except json.JSONDecodeError:
        earnings_items = {}

fundamental_scores_path = HERE / "history" / "fundamental_scores_latest.json"
fundamental_scores = None
if fundamental_scores_path.exists():
    try:
        fundamental_scores = json.loads(
            fundamental_scores_path.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError:
        fundamental_scores = None

if "fundamental_scores" not in st.session_state:
    st.session_state.fundamental_scores = fundamental_scores

fundamental_items = {
    item.get("ticker"): item
    for item in (st.session_state.fundamental_scores or {}).get("items", [])
    if item.get("ticker")
}

if "selected_universe" not in st.session_state:
    st.session_state.selected_universe = "IA"
selected_universe = st.session_state.selected_universe

next_earnings = sorted(
    (
        (ticker, item, earnings_days_until(item))
        for ticker, item in earnings_items.items()
        if earnings_days_until(item) is not None
        and earnings_days_until(item) >= 0
        and ticker_is_visible(ticker, selected_universe)
    ),
    key=lambda row: row[2],
)[:4]

header_column, calendar_column = st.columns([4, 1.35])
with header_column:
    section_heading("Simon AI — Suivi des actions", level=1)
    st.caption("Tableau de bord d’aide à l’analyse boursière par IA")
with calendar_column:
    with st.container(border=True, key="earnings_calendar_panel"):
        section_heading("Prochaines échéances", level=4)
        if next_earnings:
            for ticker, item, days_until in next_earnings:
                st.markdown(
                    '<div class="earnings-row">'
                    f'<span class="earnings-main">{earnings_risk_icon(days_until)} '
                    f'{html.escape(ticker)} · J‑{days_until}</span>'
                    f'<span class="earnings-date">{html.escape(earnings_timezone_label(item, include_times=False, compact=True))}</span>'
                    "</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("Aucune date disponible")
        st.caption("Dates indicatives")

history_dir = HERE / "history"
reports = sorted(history_dir.glob("report_*.txt"), reverse=True)
if "report" not in st.session_state:
    st.session_state.report = (
        reports[0].read_text(encoding="utf-8") if reports else None
    )
if "analysis_updated_at" not in st.session_state:
    st.session_state.analysis_updated_at = (
        report_timestamp(reports[0]) if reports else None
    )

if True:
    comparison = subprocess.run(
        [sys.executable, str(HERE / "compare_latest.py")],
        capture_output=True,
        text=True,
    )
    st.session_state.changes = comparison.stdout.strip()

analysis_button_column, fundamental_button_column, universe_column = st.columns(
    [1, 1, 0.684]
)
with analysis_button_column:
    update_analysis = st.button(
        "Mettre à jour l’analyse du marché",
        type="primary",
        use_container_width=True,
    )
with fundamental_button_column:
    update_fundamentals = st.button(
        "Réévaluer le score fondamental",
        use_container_width=True,
    )
with universe_column:
    with st.container(border=True, key="universe_filter_panel"):
        st.caption("VUE AFFICHÉE")
        selected_universe = st.segmented_control(
            "Univers",
            options=("IA", "IA-biotech"),
            key="selected_universe",
            label_visibility="collapsed",
        ) or "IA"

if update_analysis:
    with st.spinner(
        "Mise à jour de la technique, de la valorisation et des échéances..."
    ):
        result = subprocess.run(
            [sys.executable, str(HERE / "run_and_save.py")],
            capture_output=True,
            text=True,
        )

    if result.returncode == 0:
        st.session_state.report = result.stdout.split("\nSaved:", 1)[0].rstrip()
        st.session_state.analysis_updated_at = datetime.now()

        comparison = subprocess.run(
            [sys.executable, str(HERE / "compare_latest.py")],
            capture_output=True,
            text=True,
        )
        st.session_state.changes = comparison.stdout.strip()
        st.session_state.market_update_success = True
        st.rerun()
    else:
        st.error("Erreur pendant la mise à jour de l’analyse du marché")
        st.code(result.stderr, language=None)

if st.session_state.pop("market_update_success", False):
    st.success(
        "Analyse du marché mise à jour : technique, valorisation et échéances."
    )

if update_fundamentals:
    with st.spinner("Réévaluation fondamentale des entreprises..."):
        result = subprocess.run(
            [sys.executable, str(HERE / "fundamental_risk_score.py")],
            capture_output=True,
            text=True,
        )

    if result.returncode == 0:
        try:
            st.session_state.fundamental_scores = json.loads(result.stdout)
            if (
                st.session_state.fundamental_scores.get("reassessment_status")
                == "FROZEN_NO_MATERIAL_TRIGGER"
            ):
                st.info(
                    "Aucun déclencheur fondamental matériel détecté : "
                    "les scores restent strictement inchangés."
                )
            else:
                st.success("Scores fondamentaux réévalués sur événement matériel")
            st.rerun()
        except json.JSONDecodeError:
            st.error("Le score fondamental retourné est illisible")
    else:
        st.error("Erreur pendant la réévaluation fondamentale")
        st.code(result.stderr, language=None)

if st.session_state.analysis_updated_at:
    st.caption(
        "Dernière mise à jour de l’analyse du marché : "
        + french_datetime(st.session_state.analysis_updated_at)
    )
else:
    st.caption("Dernière mise à jour de l’analyse du marché : aucune")

fundamental_generated_at = parsed_datetime(
    (st.session_state.fundamental_scores or {}).get("generated_at")
)
if fundamental_generated_at:
    st.caption(
        "Dernière réévaluation fondamentale : "
        + french_datetime(fundamental_generated_at)
    )
else:
    st.caption("Dernière réévaluation fondamentale : aucune")

balance_path = HERE / "history" / "openai_balance_start.txt"
spent_path = HERE / "history" / "openai_spent.txt"

start_balance = float(balance_path.read_text().strip()) if balance_path.exists() else 0.0
spent = float(spent_path.read_text().strip()) if spent_path.exists() else 0.0
remaining = max(start_balance - spent, 0.0)

with st.expander("Coût des analyses"):
    st.caption(
        f"Dépensé : ${spent:.4f} · solde estimé : ${remaining:.2f} "
        f"sur ${start_balance:.2f}"
    )
section_gap()

quick_rankings_path = HERE / "history" / "quick_rankings_latest.json"
quick_rankings = None
if quick_rankings_path.exists():
    try:
        quick_rankings = json.loads(
            quick_rankings_path.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError:
        quick_rankings = None

technical_items = {
    item.get("ticker"): item
    for item in (quick_rankings or {}).get("items", [])
    if item.get("ticker")
}

valuation_path = HERE / "history" / "valuation_latest.json"
valuations = None
if valuation_path.exists():
    try:
        valuations = json.loads(valuation_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        valuations = None
valuation_items = {
    item.get("ticker"): item
    for item in (valuations or {}).get("items", [])
    if item.get("ticker")
}

audit_path = HERE / "history" / "market_data_audit_latest.json"
market_audit = None
if audit_path.exists():
    try:
        market_audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        market_audit = None
audit_items = {
    item.get("ticker"): item
    for item in (market_audit or {}).get("items", [])
    if item.get("ticker")
}

signal_state_path = HERE / "history" / "technical_signal_state_latest.json"
signal_state = {}
if signal_state_path.exists():
    try:
        signal_state = json.loads(
            signal_state_path.read_text(encoding="utf-8")
        ).get("items", {})
    except json.JSONDecodeError:
        signal_state = {}

fundamental_score_history = {}
for history_path in sorted(
    (HERE / "history").glob("fundamental_scores_*.json")
)[-3:]:
    try:
        historical_payload = json.loads(history_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        continue
    for item in historical_payload.get("items", []):
        ticker = item.get("ticker")
        score = item.get("score")
        if ticker and score is not None:
            fundamental_score_history.setdefault(ticker, []).append(score)

if quick_rankings:
    ranking_items = [
        item
        for item in quick_rankings.get("items", [])
        if ticker_is_visible(item.get("ticker", ""), selected_universe)
    ]
    investable_rankings = []
    actionable_rankings = []
    express_checks = {}
    for ranking in ranking_items:
        ticker = ranking.get("ticker", "")
        fundamental_item = fundamental_items.get(ticker) or {}
        valuation_item = valuation_items.get(ticker) or {}
        fundamental_score = fundamental_item.get("score")
        fundamental_category = fundamental_item.get("category", "—")
        max_exposure = fundamental_item.get("max_exposure_usd", 0)
        valuation_label = valuation_item.get("label", "INDISPONIBLE")
        earnings_days = earnings_days_until(earnings_items.get(ticker, {}))
        blockers = []
        if fundamental_score is None or fundamental_score < 55 or max_exposure <= 0:
            blockers.append("fondamental inférieur au seuil investissable")
        else:
            investable_rankings.append(ranking)
        if not technical_signal_ready(ranking):
            blockers.append(technical_blocker_text(ranking))
        if valuation_label == "INDISPONIBLE":
            blockers.append("valorisation indisponible")
        elif valuation_is_blocking(valuation_label):
            blockers.append("prime de valorisation élevée")
        if earnings_days is not None and earnings_days <= 7:
            blockers.append(f"résultats {earnings_comparison_text(earnings_items.get(ticker))}")
        express_checks[ticker] = {
            "blockers": blockers,
            "fundamental_score": fundamental_score,
            "fundamental_category": fundamental_category,
            "max_exposure": max_exposure,
            "valuation_label": valuation_label,
            "earnings": earnings_comparison_text(earnings_items.get(ticker)),
            "earnings_days": earnings_days,
            "trend_regime": ranking.get("trend_regime"),
            "phase": ranking.get("phase"),
        }
        if not blockers:
            actionable_rankings.append(ranking)
    actionable_rankings = actionable_rankings[:3]

    as_of_text = None
    as_of = ranking_items[0].get("as_of") if ranking_items else None
    if as_of:
        try:
            as_of_date = date.fromisoformat(as_of)
            as_of_text = (
                "Dernière séance utilisée : "
                f"{as_of_date.day} "
                f"{FRENCH_MONTHS[as_of_date.month - 1]} "
                f"{as_of_date.year}"
            )
        except ValueError:
            pass

    component_labels = {
        "trend_structure": "Tendance / Higher Low",
        "price_location": "Emplacement du prix",
        "trigger": "Déclencheur d’entrée",
        "higher_low": "Higher low",
        "breakout": "Breakout",
        "volume": "Volume",
        "rsi": "RSI",
        "price": "Prix",
    }
    has_clear_opportunity = bool(actionable_rankings)
    focus_ranking = (
        actionable_rankings[0]
        if has_clear_opportunity
        else (investable_rankings[0] if investable_rankings else None)
    )
    express_title = "AUCUNE CONFIGURATION SUFFISAMMENT FAVORABLE AUJOURD’HUI"
    express_style = "warning"
    if has_clear_opportunity:
        focus_setup = actionable_rankings[0].get("setup_type")
        if focus_setup == "RETOURNEMENT CONFIRMÉ":
            express_title = "ENTRÉE PROGRESSIVE À ÉTUDIER APRÈS RETOURNEMENT"
        elif focus_setup == "PULLBACK CONFIRMÉ":
            express_title = "ENTRÉE PROGRESSIVE À ÉTUDIER APRÈS PULLBACK"
        elif focus_setup == "STABILISATION CONFIRMÉE":
            express_title = "ENTRÉE PROGRESSIVE À ÉTUDIER APRÈS STABILISATION"
        else:
            express_title = "OPPORTUNITÉ D’ENTRÉE À ÉTUDIER AUJOURD’HUI"
        actionable_valuation = express_checks.get(
            actionable_rankings[0].get("ticker", ""), {}
        ).get("valuation_label")
        if actionable_valuation in CAUTION_VALUATIONS:
            express_title = (
                "SETUP TECHNIQUE VALIDÉ — VALORISATION UN PEU EXIGEANTE"
            )
            express_style = "warning"
        else:
            express_style = "success"
    elif focus_ranking:
        focus_preview = express_checks.get(focus_ranking.get("ticker", ""), {})
        preview_fundamental = focus_preview.get("fundamental_score")
        preview_max = focus_preview.get("max_exposure", 0)
        preview_valuation = focus_preview.get("valuation_label", "INDISPONIBLE")
        preview_technical = focus_ranking.get("score", 0)
        preview_trigger = has_confirmed_trigger(focus_ranking)
        preview_technical_pass = technical_signal_ready(focus_ranking)
        preview_earnings_days = focus_preview.get("earnings_days")
        preview_fundamental_pass = (
            preview_fundamental is not None
            and preview_fundamental >= 55
            and preview_max > 0
        )
        preview_valuation_pass = not valuation_is_blocking(preview_valuation)
        if preview_fundamental_pass and preview_valuation_pass:
            if (
                preview_valuation in CAUTION_VALUATIONS
                and (not preview_technical_pass or not preview_trigger)
            ):
                express_title = (
                    "ENTREPRISE SOLIDE — VALORISATION UN PEU EXIGEANTE — "
                    "DÉCLENCHEUR TECHNIQUE MANQUANT"
                )
            elif (
                preview_technical_pass
                and preview_earnings_days is not None
                and preview_earnings_days <= 7
            ):
                if preview_earnings_days == 0:
                    express_title = "SETUP FAVORABLE — RÉSULTATS AUJOURD’HUI"
                else:
                    day_label = "JOUR" if preview_earnings_days == 1 else "JOURS"
                    express_title = (
                        "SETUP FAVORABLE — ATTENDRE LES RÉSULTATS "
                        f"DANS {preview_earnings_days} {day_label}"
                    )
            elif not preview_technical_pass and preview_technical < 65:
                express_title = (
                    "DOSSIER FAVORABLE — ATTENDRE UN MEILLEUR SETUP TECHNIQUE"
                )
            elif not preview_technical_pass or not preview_trigger:
                express_title = (
                    "CONTEXTE FAVORABLE — DÉCLENCHEUR TECHNIQUE MANQUANT"
                )
            elif preview_earnings_days is None:
                express_title = (
                    "SETUP FAVORABLE — DATE DES RÉSULTATS À VÉRIFIER"
                )
            else:
                express_title = "DOSSIER FAVORABLE — ATTENDRE UN MEILLEUR TIMING"
        elif preview_fundamental_pass and not preview_valuation_pass:
            express_title = "DOSSIER INVESTISSABLE — VALORISATION TROP EXIGEANTE"
        elif not preview_fundamental_pass:
            express_title = "SURVEILLANCE UNIQUEMENT — RISQUE FONDAMENTAL TROP ÉLEVÉ"
    if focus_ranking:
        express_title = f"{focus_ranking.get('ticker', '—')} — {express_title}"

    with st.container(border=True, key="express_summary_panel"):
        section_heading("Synthèse express")
        if as_of_text:
            st.caption(as_of_text)

        st.markdown(
            f"""
            <div class="express-decision {express_style}">
                <div class="express-decision-title">
                    {html.escape(express_title)}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if focus_ranking:
            focus_ticker = focus_ranking.get("ticker", "—")
            focus_check = express_checks.get(focus_ticker, {})
            technical_score = focus_ranking.get("score", 0)
            fundamental_score = focus_check.get("fundamental_score")
            max_exposure = focus_check.get("max_exposure", 0)
            valuation_label = focus_check.get("valuation_label", "INDISPONIBLE")
            earnings_days = focus_check.get("earnings_days")
            technical_pass = technical_signal_ready(focus_ranking)
            fundamental_pass = (
                fundamental_score is not None
                and fundamental_score >= 55
                and max_exposure > 0
            )
            valuation_pass = not valuation_is_blocking(valuation_label)
            earnings_pass = earnings_days is not None and earnings_days > 7

            if valuation_is_positive(valuation_label):
                valuation_status = "FAVORABLE"
                valuation_css_class = "pass"
            elif valuation_label == "RAISONNABLE":
                valuation_status = "NEUTRE"
                valuation_css_class = "neutral"
            elif valuation_label in CAUTION_VALUATIONS:
                valuation_status = (
                    "PRUDENCE"
                )
                valuation_css_class = "caution"
            else:
                valuation_status = "FREIN"
                valuation_css_class = "block"

            if earnings_days is None:
                earnings_status = "DATE À VÉRIFIER"
                earnings_css_class = "block"
            elif earnings_days <= 7:
                earnings_status = "VIGILANCE · publication proche"
                earnings_css_class = "block"
            else:
                earnings_status = "ÉCHÉANCE À VENIR"
                earnings_css_class = "neutral"

            checks = (
                (
                    "Technique",
                    f"{technical_score}/100",
                    (
                        f"OK · {focus_ranking.get('setup_type', 'SETUP')}"
                        if technical_pass
                        else f"FREIN · {technical_blocker_text(focus_ranking)}"
                    ),
                    "pass" if technical_pass else "block",
                ),
                (
                    "Fondamental / Max",
                    f"{focus_check.get('fundamental_category', '—')} ({fundamental_score if fundamental_score is not None else 'N/A'})",
                    (
                        f"OK · Max {compact_max_exposure(max_exposure)}"
                        if fundamental_pass
                        else "FREIN · non investissable"
                    ),
                    "pass" if fundamental_pass else "block",
                ),
                (
                    "Valorisation",
                    valuation_label,
                    valuation_status,
                    valuation_css_class,
                ),
                (
                    "Résultats",
                    focus_check.get("earnings", "date indisponible"),
                    earnings_status,
                    earnings_css_class,
                ),
            )
            checks_html = []
            for label, value, status, css_class in checks:
                checks_html.append(
                    f'<div class="express-check {css_class}">'
                    f'<div class="express-check-label">{html.escape(label)}</div>'
                    f'<div class="express-check-value">{html.escape(str(value))}</div>'
                    f'<div class="express-check-status">{html.escape(status)}</div>'
                    "</div>"
                )
            st.markdown(
                '<div class="express-checks">'
                + "".join(checks_html)
                + "</div>",
                unsafe_allow_html=True,
            )
            if has_clear_opportunity:
                if valuation_label in CAUTION_VALUATIONS:
                    st.warning(
                        "SETUP TECHNIQUE VALIDÉ — entrée éventuelle à étudier avec "
                        "prudence car la valorisation reste un peu exigeante"
                    )
                elif focus_ranking.get("setup_type") in (
                    "RETOURNEMENT CONFIRMÉ",
                    "PULLBACK CONFIRMÉ",
                ):
                    st.success(
                        "ENTRÉE PROGRESSIVE À ÉTUDIER — reprise confirmée, "
                        "sans attendre le breakout · annuler si l’ouverture "
                        "dépasse le cours du signal de plus de 2 %"
                    )
                else:
                    st.success(
                        "À ÉTUDIER POUR ACHAT — critères validés · annuler si "
                        "l’ouverture dépasse le cours du signal de plus de 2 %"
                    )
            else:
                reasons = []
                if not technical_pass:
                    reasons.append(technical_blocker_text(focus_ranking))
                if not fundamental_pass:
                    reasons.append(
                        "le score fondamental ne permet pas encore une position"
                    )
                if not valuation_pass:
                    reasons.append(
                        "la valorisation est trop exigeante ou indisponible"
                    )
                if not earnings_pass:
                    if earnings_days is None:
                        reasons.append("la date des prochains résultats est inconnue")
                    elif earnings_days == 0:
                        reasons.append("les résultats sont publiés aujourd’hui")
                    else:
                        reasons.append(
                            f"les résultats seront publiés dans {earnings_days} jours"
                        )
                st.info(
                    "Pourquoi attendre : "
                    + "; ".join(reasons[:3])
                    + "."
                )
            st.caption(
                "Fondamental + valorisation = qualité du dossier. "
                "Technique + résultats = qualité du moment d’entrée."
            )

            with st.expander("Détail du score technique"):
                for name, component in focus_ranking.get("components", {}).items():
                    label = component_labels.get(name, name)
                    st.write(
                        f"**{label} : {component.get('score', 0)}** — "
                        f"{component.get('detail', '')}"
                    )

        with st.expander("Comment le score technique est calculé"):
            st.caption(
                "Score sur 100 : tendance et higher low 25, emplacement du prix 25, "
                "déclencheur d’entrée 20, volume adapté au setup 15 et RSI 15. "
                "Le déclencheur retient le meilleur chemin entre Higher Low confirmé, breakout, "
                "retournement haussier et pullback favorable, sans les additionner. "
                "Un Higher Low exige un creux au moins 2 % plus haut, puis une hausse "
                "d’au moins 1,5 %, le dépassement du plus haut de la séance précédente "
                "et une clôture dans les 35 % supérieurs de la bougie. "
                "Un pullback favorable exige une tendance longue haussière, un recul "
                "contrôlé vers la SMA200, un RSI bas et un volume vendeur en contraction. "
                "Il ne devient exploitable qu’après une reprise du prix. Un retournement doit "
                "tenir au moins une séance avant de devenir exploitable. Un breakout "
                "sous le volume moyen reste non confirmé. Le volume est interprété "
                "différemment : contraction pendant un repli ou expansion lors d’un "
                "breakout/retournement. Après un choc baissier d’au moins 5 % sur "
                "volume exceptionnel, le point bas doit tenir deux séances, les clôtures "
                "doivent remonter et le volume doit nettement se contracter. "
                "Le prix nominal de l’action n’est pas récompensé. Les dossiers "
                "doivent avoir un fondamental d’au moins 55/100, un score technique "
                "d’au moins 65/100 avec Higher Low/breakout confirmé, ou 60/100 "
                "après un retournement ou pullback confirmé, une valorisation disponible et non "
                "PRIME ÉLEVÉE, et aucun résultat dans les 7 jours. "
                "Ces critères "
                "restent séparés et ne sont pas mélangés dans un score global. Tri de recherche, "
                "pas une recommandation ni un ordre d’achat."
            )
else:
    with st.container(border=True, key="express_summary_panel"):
        section_heading("Synthèse express")
        st.info("La synthèse express sera disponible après la prochaine mise à jour.")

section_gap()
market_news_path = HERE / "history" / "ai_market_news_latest.json"
if market_news_path.exists():
    try:
        market_news = json.loads(market_news_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        market_news = None

    if market_news:
        section_heading("Actualités majeures de l’IA")
        source_status = market_news.get("source_status", {})
        with st.expander("Disponibilité des sources"):
            st.caption(
                " · ".join(
                    f"{source}={fr(status)}"
                    for source, status in source_status.items()
                )
            )

        market_items = [
            item
            for item in market_news.get("items", [])
            if (
                bool(
                    set(item.get("related_tickers", []))
                    & AI_BIOTECH_TICKERS
                )
                == (selected_universe == "IA-biotech")
            )
        ]
        if not market_items:
            st.info("Aucune actualité suffisamment importante n’a été retenue.")

        positioning_labels = {
            "POSITION TO STUDY": "CONFIGURATION FAVORABLE — OPPORTUNITÉ À ÉTUDIER",
            "WAIT FOR CONFIRMATION": "ATTENDRE UNE CONFIRMATION",
            "DO NOT POSITION ON THIS NEWS ALONE": "NE PAS SE POSITIONNER SUR CETTE SEULE NEWS",
        }

        for item in market_items:
            with st.container(border=True):
                companies = item.get("companies", [])
                st.markdown(f"#### {item.get('event', 'Actualité IA')}")
                metadata = news_date_label(item.get("published_at"))
                if companies:
                    metadata += " · " + ", ".join(companies)
                metadata += (
                    " · Impact "
                    f"{NEWS_IMPACT_LABELS.get(item.get('impact'), 'incertain')} · "
                    f"confiance {fr(item.get('confidence', 'LOW')).lower()}"
                )
                st.caption(metadata)

                positioning = item.get("positioning", "WAIT FOR CONFIRMATION")
                positioning_text = positioning_labels.get(positioning, positioning)
                if positioning == "POSITION TO STUDY":
                    st.success(positioning_text)
                elif positioning == "DO NOT POSITION ON THIS NEWS ALONE":
                    st.error(positioning_text)
                else:
                    st.warning(positioning_text)

                with st.expander("Voir l’analyse et les sources"):
                    positioning_reason = item.get("positioning_reason", "")
                    if positioning_reason:
                        st.write(
                            "**Pourquoi cette décision :**",
                            positioning_reason,
                        )
                    st.write(
                        "**Pourquoi c’est important :**",
                        item.get("why_it_matters", "N/A"),
                    )
                    st.caption(
                        "Confirmation nécessaire : "
                        + item.get("confirmation_needed", "Analyse complémentaire")
                    )
                    st.caption(
                        "Sources utilisées : "
                        + ", ".join(item.get("sources", []))
                    )

                    contexts = item.get("market_context", [])
                    if contexts:
                        st.write("**Contexte marché :**")
                        for context in contexts[:3]:
                            ticker = context.get("ticker", "—")
                            rsi14 = context.get("rsi14")
                            forward_pe = context.get("forward_pe")
                            context_parts = [
                                ticker,
                                (
                                    f"RSI {rsi14:.1f}"
                                    if rsi14 is not None
                                    else "RSI N/A"
                                ),
                                context.get("technical_regime", "N/A"),
                            ]
                            if forward_pe is not None:
                                context_parts.append(
                                    f"P/E forward {forward_pe:.1f}x"
                                )
                            if context.get("price_to_sales") is not None:
                                context_parts.append(
                                    f"P/S {context['price_to_sales']:.1f}x"
                                )
                            st.caption(" · ".join(context_parts))

                    links = item.get("links", [])
                    if links:
                        link_columns = st.columns(min(len(links), 3))
                        for index, link in enumerate(links[:3]):
                            with link_columns[index]:
                                st.link_button(
                                    "Lire la source",
                                    link.get("url", ""),
                                    use_container_width=True,
                                )

        st.caption(
            "Lecture de recherche uniquement : une « position à étudier » n’est jamais un ordre d’achat."
        )

section_gap()
if technical_items or fundamental_items:
    section_heading("Comparatif depuis la dernière analyse")
    comparison_rows = {"IA": [], "IA-biotech": []}
    comparison_universe = (
        set(WATCHLIST)
        | set(report_tickers(st.session_state.report))
        | set(technical_items)
        | set(fundamental_items)
        | set(valuation_items)
    )
    comparison_universe = {
        ticker
        for ticker in comparison_universe
        if ticker_is_visible(ticker, selected_universe)
    }
    comparison_tickers = sorted(
        comparison_universe,
        key=lambda ticker: (
            0
            if (fundamental_items.get(ticker) or {}).get("max_exposure_usd", 0) > 0
            else 1,
            -(technical_items.get(ticker) or {}).get("score", -1),
            -(fundamental_items.get(ticker) or {}).get("score", -1),
            ticker,
        ),
    )
    for ticker in comparison_tickers:
        technical_item = technical_items.get(ticker)
        fundamental_item = fundamental_items.get(ticker)
        valuation_item = valuation_items.get(ticker)
        earnings_item = earnings_items.get(ticker)
        max_exposure = (fundamental_item or {}).get("max_exposure_usd", 0)
        technical_score = (technical_item or {}).get("score")
        setup_type = (technical_item or {}).get("setup_type")
        setup_suffix = (
            f" · {setup_type}"
            if setup_type and setup_type != "AUCUN"
            else ""
        )
        technical_text = (
            f"{technical_score} — "
            f"{technical_setup_label(technical_score, setup_type)}"
            f"{setup_suffix}"
            if technical_score is not None
            else "INDISPONIBLE"
        )
        score_change = (technical_item or {}).get("score_change_3d")
        evolution_text = (
            f"{score_change:+d}" if isinstance(score_change, int) else "—"
        )
        rapid_improvement = isinstance(score_change, int) and score_change >= 8
        if rapid_improvement:
            evolution_text += " · amélioration rapide"
        valuation_label = (valuation_item or {}).get("label", "INDISPONIBLE")
        fundamental_score = (fundamental_item or {}).get("score")
        fundamental_category = (fundamental_item or {}).get("category", "—")
        fundamental_text = (
            f"{fundamental_category} ({fundamental_score})"
            if fundamental_score is not None
            else "INDISPONIBLE"
        )
        action_text, action_is_positive = comparison_action_label(
            technical_item,
            fundamental_item,
            valuation_item,
            earnings_item,
        )
        results_text = earnings_comparison_text(earnings_item)
        results_days = earnings_days_until(earnings_item or {})
        cells = [
            comparison_cell(ticker),
            comparison_cell(
                technical_text,
                (
                    "positive"
                    if technical_score is not None
                    and technical_signal_ready(technical_item)
                    else ""
                ),
            ),
            comparison_cell(evolution_text, "positive" if rapid_improvement else ""),
            comparison_cell(
                valuation_label,
                "positive" if valuation_is_positive(valuation_label) else "",
            ),
            fundamental_max_cell(
                fundamental_text,
                compact_max_exposure(max_exposure),
                fundamental_score is not None and fundamental_score >= 85 and fundamental_category == "A",
            ),
            comparison_cell(
                results_text,
                "near-event" if results_days is not None and results_days <= 7 else "",
            ),
            comparison_cell(action_text, "positive" if action_is_positive else ""),
        ]
        comparison_rows[stock_section(ticker)].append(
            "<tr>" + "".join(cells) + "</tr>"
        )
    comparison_headers = (
        "Action", "Technique", "Évolution technique depuis 3 séances", "Valorisation",
        "Fondamental / Max", "Résultats", "À faire",
    )
    for section_name in (selected_universe,):
        rows = comparison_rows[section_name]
        if not rows:
            continue
        section_heading(section_name, level=4)
        st.markdown(
            '<div class="comparison-wrap"><table class="comparison-table">'
            "<thead><tr>"
            + "".join(
                f"<th>{html.escape(label)}</th>"
                for label in comparison_headers
            )
            + "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></div>",
            unsafe_allow_html=True,
        )
    st.caption(
        "Les dossiers investissables (catégories A, B ou C) sont affichés en premier, "
        "puis classés par score technique actuel. Les titres WATCHLIST apparaissent "
        "ensuite, quelle que soit leur note technique."
    )
    if st.session_state.changes:
        section_heading("Changements significatifs", level=4)
        rendered_changes = render_change_list(
            st.session_state.changes,
            st.session_state.report,
            selected_universe,
        )
        if not rendered_changes:
            st.caption(
                "Aucun changement significatif depuis la dernière analyse."
            )
    section_gap()

if st.session_state.report:
    report = st.session_state.report
    blocks = []
    current = []

    for line in report.splitlines():
        if line.startswith("#"):
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)

    if current:
        blocks.append(current)

    blocks = [
        block
        for block in blocks
        if ticker_is_visible(
            block[0].split("—", 1)[0].split()[-1],
            selected_universe,
        )
    ]

    blocks.sort(
        key=lambda block: (
            1
            if stock_section(block[0].split("—", 1)[0].split()[-1])
            == "IA-biotech"
            else 0
        )
    )

    current_stock_section = None
    for block in blocks:
        header = block[0]
        ticker = header.split("—", 1)[0].split()[-1]
        section_name = stock_section(ticker)
        if section_name != current_stock_section:
            section_heading(section_name, level=2)
            current_stock_section = section_name
        fields = {}

        for line in block[1:]:
            line = line.strip()
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.strip()] = value.strip()

        compact_summary = fields.get("Prix", "")
        compact_parts = [x.strip() for x in compact_summary.split("|")]
        compact_price = compact_parts[0] if compact_parts else "N/A"
        compact_technical = technical_items.get(ticker) or {}
        compact_fundamental = fundamental_items.get(ticker) or {}
        compact_valuation = valuation_items.get(ticker) or {}
        compact_technical_score = compact_technical.get("score")
        compact_setup_type = compact_technical.get("setup_type")
        compact_setup_text = (
            f" · Setup {compact_setup_type}"
            if compact_setup_type and compact_setup_type != "AUCUN"
            else ""
        )
        compact_fundamental_score = compact_fundamental.get("score")
        compact_category = compact_fundamental.get("category", "—")
        compact_label = (
            f"{ticker} · {compact_price} · "
            f"Technique {compact_technical_score if compact_technical_score is not None else 'N/A'}/100"
            f"{compact_setup_text} · "
            f"Fondamental {compact_category} ({compact_fundamental_score if compact_fundamental_score is not None else 'N/A'}) · "
            f"Valorisation : {compact_valuation.get('label', 'indisponible')}"
        )
        with st.expander(compact_label):
            summary = fields.get("Prix", "")
            parts = [x.strip() for x in summary.split("|")]
            price = parts[0] if parts else "N/A"
            fundamentals = (
                parts[1].replace("Fondamentaux:", "").strip()
                if len(parts) > 1 else "N/A"
            )
            news = (
                parts[2].replace("News:", "").strip()
                if len(parts) > 2 else "N/A"
            )
            view = fields.get("Verdict", "N/A")
            technical = fields.get("Technique", "N/A")
            rsi14 = fields.get("RSI14", "N/A")
            earnings_item = earnings_items.get(ticker)
            fundamental_item = fundamental_items.get(ticker)
            valuation_item = valuation_items.get(ticker)
            technical_item = technical_items.get(ticker)
            audit_item = audit_items.get(ticker)
            signal_record = signal_state.get(ticker)
            days_until = earnings_days_until(earnings_item or {})
            action, action_style = structured_positioning(
                technical_item,
                fundamental_item,
                valuation_item,
                days_until,
            )

            title_column, price_column = st.columns([4, 1])
            with title_column:
                st.subheader(ticker)
            with price_column:
                st.metric("Prix", price)

            st.caption("POSITIONNEMENT ACTUEL")
            st.markdown(
                f'<div class="positioning-card {action_style}">{action}</div>',
                unsafe_allow_html=True,
            )

            technical_score = (
                technical_item.get("score") if technical_item else None
            )
            timing = technical_setup_label(
                technical_score,
                (technical_item or {}).get("setup_type"),
            )
            event_risk, event_detail = event_risk_summary(days_until)
            quality_column, valuation_column, timing_column, event_column = st.columns(
                [1.05, 0.9, 1.2, 0.9]
            )
            with quality_column:
                with st.container(border=True):
                    st.caption("QUALITÉ FONDAMENTALE")
                    if fundamental_item:
                        category = fundamental_item.get("category", "—")
                        max_exposure = fundamental_item.get("max_exposure_usd", 0)
                        st.markdown(
                            f"### {fundamental_item.get('score', 0)}/100 — "
                            f"CATÉGORIE {category}"
                        )
                        st.caption(
                            (
                                f"Position max indicative : {usd_amount(max_exposure)}"
                                if max_exposure
                                else "Watchlist uniquement"
                            )
                        )
                        fundamental_history = fundamental_score_history.get(ticker, [])
                        if len(fundamental_history) >= 2:
                            st.caption(
                                "Évolution : "
                                + " → ".join(
                                    str(score) for score in fundamental_history[-3:]
                                )
                            )
                    else:
                        st.markdown("### NON ÉVALUÉE")
                        st.caption("Réévaluation fondamentale nécessaire")
            with valuation_column:
                with st.container(border=True):
                    st.caption("VALORISATION")
                    st.markdown(
                        f"### {(valuation_item or {}).get('label', 'INDISPONIBLE')}"
                    )
                    st.caption(valuation_metrics_text(valuation_item))
                    st.caption(valuation_audit_text(valuation_item))
                    st.caption(valuation_transparency_text(valuation_item))
            with timing_column:
                with st.container(border=True):
                    st.caption("TIMING TECHNIQUE")
                    score_text = (
                        f"{technical_score}/100" if technical_score is not None else "N/A"
                    )
                    st.markdown(f"### {score_text} — {timing}")
                    setup_type = (technical_item or {}).get("setup_type")
                    if setup_type and setup_type != "AUCUN":
                        st.caption(f"Type de setup : {setup_type}")
                    invalidation = (technical_item or {}).get("invalidation")
                    if invalidation:
                        st.caption(
                            f"Invalidation : {invalidation.get('level'):.2f} "
                            f"({invalidation.get('distance_pct'):+.1f} %) · "
                            f"{invalidation.get('rule')}"
                        )
                    trend = (technical_item or {}).get(
                        "trend_regime", "INDISPONIBLE"
                    )
                    phase = (technical_item or {}).get("phase", "INDISPONIBLE")
                    st.caption(f"Tendance de fond : {trend} · Phase : {phase}")
                    metrics = (technical_item or {}).get("metrics", {})
                    sma50 = metrics.get("sma50")
                    vs_sma50 = metrics.get("vs_sma50_pct")
                    if sma50 is not None and vs_sma50 is not None:
                        st.caption(
                            f"Support dynamique SMA50 : {sma50:.2f} · "
                            f"cours {vs_sma50:+.1f} % vs SMA50"
                        )
                    st.caption(
                        f"RSI {rsi14} · "
                        f"Support horizontal "
                        f"{level_distance(fields.get('Support'), 'support')} · "
                        f"Résistance "
                        f"{level_distance(fields.get('Resistance'), 'resistance')}"
                    )
                    st.caption("Évolution : " + score_evolution_text(technical_item))
            with event_column:
                with st.container(border=True):
                    st.caption("RISQUE ÉVÉNEMENTIEL")
                    st.markdown(f"### {event_risk}")
                    st.caption(event_detail)
                    st.caption(earnings_timezone_label(earnings_item))

            alerts = critical_alerts(
                fields,
                days_until,
                technical_item,
                audit_item,
                signal_record,
            )
            if alerts:
                st.warning(" · ".join(alerts))

            st.write(
                "**Lecture actuelle :**",
                structured_technical_reading(technical_item),
            )

            with st.expander("Analyse détaillée"):
                st.write("**Verdict du modèle :**", fr(fr(view)))
                if fundamental_item:
                    st.write(
                        "**Score fondamental :**",
                        f"{fundamental_item.get('score', 0)}/100 · "
                        f"catégorie {fundamental_item.get('category', '—')}",
                    )
                    criterion_labels = {
                        "moat": "Moat / position stratégique",
                        "financial_strength": "Solidité financière",
                        "diversification": "Diversification / résilience",
                        "competitive_resilience": "Résilience concurrentielle / technologique",
                        "specific_risk_resilience": "Maîtrise des risques spécifiques",
                    }
                    for name, criterion in fundamental_item.get("criteria", {}).items():
                        st.write(
                            f"**{criterion_labels.get(name, name)} : "
                            f"{criterion.get('score', 0)}/{criterion.get('max', 0)}** — "
                            f"{criterion.get('reason', '')}"
                        )
                    watch_items = fundamental_item.get("watch_items", [])
                    if watch_items:
                        st.caption("Facteurs de réévaluation : " + " · ".join(watch_items))
                if valuation_item:
                    st.write(
                        "**Valorisation :**",
                        valuation_item.get("label", "INDISPONIBLE"),
                        "—",
                        valuation_metrics_text(valuation_item),
                    )
                st.write("**Technique :**", fr(fr(technical)))
                st.write("**RSI14 :**", f"{rsi14} — {rsi_label(rsi14)}")
                st.write("**Actualités :**", fr(news))
                st.write(
                    "**Point de vigilance :**",
                    fr(fr(fields.get("Risque principal", "N/A"))),
                )
                st.write(
                    "**À surveiller :**",
                    fr(fr(fields.get("A surveiller", "N/A"))),
                )

            with st.expander("Sources et méthodologie"):
                st.caption(
                    "Sources actualités : "
                    + fields.get("Sources news", "Yahoo Finance")
                )
                st.caption(
                    fr(fields.get("Statut sources news", "Yahoo Finance=OK"))
                )
                st.caption(earnings_label(earnings_item))
                if audit_item:
                    audit_status = (
                        "VÉRIFIÉES"
                        if audit_item.get("status") == "VERIFIED"
                        else "À VÉRIFIER"
                    )
                    st.caption(
                        f"Données de marché : {audit_status} · "
                        f"{audit_item.get('exchange', 'place inconnue')} · "
                        f"{audit_item.get('currency', 'devise inconnue')} · "
                        f"source {audit_item.get('source', 'inconnue')}"
                    )
                    for note in audit_item.get("notes", []):
                        st.caption(note)

elif not st.session_state.report:
    st.info("Clique sur Mettre à jour l’analyse pour lancer une nouvelle analyse.")
