import subprocess
import sys
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent

st.set_page_config(page_title="Simon AI Stock Watchlist", page_icon="📈", layout="wide")

st.title("📈 Simon AI Stock Watchlist")
st.caption("AI-assisted stock research dashboard")

if st.button("🔄 Update analysis", type="primary"):
    with st.spinner("Analyse des actions en cours..."):
        result = subprocess.run(
            [sys.executable, str(HERE / "final_report.py")],
            capture_output=True,
            text=True,
        )

    if result.returncode == 0:
        st.success("Analyse terminée")
        st.code(result.stdout, language=None)
    else:
        st.error("Erreur pendant l analyse")
        st.code(result.stderr, language=None)
else:
    st.info("Clique sur Update analysis pour lancer une nouvelle analyse.")
