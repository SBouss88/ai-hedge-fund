import subprocess
import sys
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent

def fr(text):
    replacements = {
        "VERIFY - HIGH UNCERTAINTY": "À VÉRIFIER - FORTE INCERTITUDE",
        "WAIT - BETTER ENTRY": "ATTENDRE - MEILLEURE ENTRÉE",
        "WAIT FOR BETTER ENTRY": "ATTENDRE UNE MEILLEURE ENTRÉE",
        "WATCH - VERIFY FUNDAMENTALS": "À SURVEILLER - VÉRIFIER LES FONDAMENTAUX",
        "OVERHEATED - DO NOT CHASE": "SURCHAUFFE - NE PAS POURSUIVRE LA HAUSSE",
        "POSITIVE MOMENTUM": "DYNAMIQUE HAUSSIÈRE",
        "WATCH - PULLBACK": "À SURVEILLER - REPLI",
        "PULLBACK OPPORTUNITY": "OPPORTUNITÉ SUR REPLI",
        "CAUTION - NEGATIVE NEWS": "PRUDENCE - ACTUALITÉS NÉGATIVES",
        "CAUTION - WEAK FUNDAMENTALS": "PRUDENCE - FONDAMENTAUX FAIBLES",
        "CAUTION - WEAK TECHNICALS": "PRUDENCE - TECHNIQUE FAIBLE",
        "WAIT FOR COOLING": "ATTENDRE UN REFROIDISSEMENT",
        "ATTRACTIVE SETUP": "CONFIGURATION ATTRACTIVE",
        "— ATTRACTIVE": "— ATTRACTIF",
        "INCOMPLETE": "INCOMPLET",
        "POSITIVE": "POSITIVES",
        "NEGATIVE": "NÉGATIVES",
        "MIXED": "MITIGÉES",
        "STRONG": "FORT",
        "WEAK": "FAIBLE",
        "NEARBY": "PROCHE",
        "DISTANT": "ÉLOIGNÉ",
        "HIGH": "ÉLEVÉE",
        "MEDIUM": "MOYENNE",
        "LOW": "FAIBLE",
        "WATCH": "À SURVEILLER",
        "away": "d’écart",
        "touches": "contacts",
    }
    result = str(text)
    for old, new in replacements.items():
        result = result.replace(old, new)
    return result

st.set_page_config(
    page_title="Simon AI Stock Watchlist",
    page_icon="📈",
    layout="wide",
)

st.title("📈 Simon AI — Suivi des actions")
st.caption("Tableau de bord d’aide à l’analyse boursière par IA")

if "report" not in st.session_state:
    history_dir = HERE / "history"
    reports = sorted(history_dir.glob("report_*.txt"), reverse=True)
    st.session_state.report = (
        reports[0].read_text(encoding="utf-8") if reports else None
    )

if st.button("🔄 Mettre à jour l’analyse", type="primary"):
    with st.spinner("Analyse des actions en cours..."):
        result = subprocess.run(
            [sys.executable, str(HERE / "run_and_save.py")],
            capture_output=True,
            text=True,
        )

    if result.returncode == 0:
        st.session_state.report = result.stdout.split("\nSaved:", 1)[0].rstrip()
        st.success("Analyse terminée")
    else:
        st.error("Erreur pendant l analyse")
        st.code(result.stderr, language=None)

balance_path = HERE / "history" / "openai_balance_start.txt"
spent_path = HERE / "history" / "openai_spent.txt"

start_balance = float(balance_path.read_text().strip()) if balance_path.exists() else 0.0
spent = float(spent_path.read_text().strip()) if spent_path.exists() else 0.0
remaining = max(start_balance - spent, 0.0)

b1, b2, b3 = st.columns(3)
b1.metric("💳 Solde de départ", f"${start_balance:.2f}")
b2.metric("💸 Dépensé par l outil", f"${spent:.4f}")
b3.metric("💰 Solde estimé", f"${remaining:.2f}")
st.caption("Solde estimé localement à partir du dernier solde OpenAI renseigné.")

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

    for block in blocks:
        header = block[0]
        fields = {}

        for line in block[1:]:
            line = line.strip()
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.strip()] = value.strip()

        with st.container(border=True):
            st.subheader(fr(header))

            c1, c2, c3 = st.columns(3)

            summary = fields.get("Prix", "")
            parts = [x.strip() for x in summary.split("|")]

            with c1:
                st.metric("Prix", parts[0] if parts else "N/A")
            with c2:
                st.caption("Fondamentaux")
                st.markdown(
                    "### " + (
                        fr(fr(parts[1].replace("Fondamentaux:", "").strip()))
                        if len(parts) > 1 else "N/A"
                    )
                )
            with c3:
                st.caption("Actualités")
                st.markdown(
                    "### " + (
                        fr(parts[2].replace("News:", "").strip())
                        if len(parts) > 2 else "N/A"
                    )
                )

            st.write("**Technique :**", fr(fr(fields.get("Technique", "N/A"))))

            c1, c2 = st.columns(2)
            with c1:
                st.write("**Support :**", fr(fr(fields.get("Support", "N/A"))))
            with c2:
                st.write("**Résistance :**", fr(fr(fields.get("Resistance", "N/A"))))

            st.markdown("**Verdict :** " + fr(fr(fields.get("Verdict", "N/A"))))
            st.write("**Pourquoi :**", fr(fr(fields.get("Pourquoi", "N/A"))))
            st.warning("⚠️ " + fr(fr(fields.get("Risque principal", "N/A"))))
            st.info("👀 " + fr(fr(fields.get("A surveiller", "N/A"))))

elif not st.session_state.report:
    st.info("Clique sur Mettre à jour l’analyse pour lancer une nouvelle analyse.")
