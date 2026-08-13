#!/bin/bash
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$REPO/simon_stocks/logs/dashboard.log"
if ! lsof -iTCP:8501 -sTCP:LISTEN >/dev/null 2>&1; then
    cd "$REPO"
    nohup "$HOME/.local/bin/poetry" run streamlit run simon_stocks/dashboard.py --server.headless true > "$LOG" 2>&1 &
fi
sleep 2
open "http://localhost:8501"
