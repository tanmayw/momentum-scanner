# Nifty 500 Scanner Constitution

**Version**: 2.0.0 | **Ratified**: 2026-08-21

---

## Core Principles

### I. Simplicity & Speed
The application must remain lightweight and fast. FastAPI + pandas for the backend. Vanilla HTML/CSS/JS for the frontend — no heavy frameworks. Any new feature must not introduce a new runtime dependency without explicit justification.

### II. Local-First Caching
All data caching is handled on local disk (`cache/` directory, Parquet format, keyed by date). The app must function without internet after the first daily download. No cloud credentials, no SaaS dependencies.

### III. Spec-Driven Scoring
Every scoring component must map 1:1 to the defined specification (`spec.md`). Ad-hoc changes to scoring weights or thresholds are not permitted without updating `spec.md` first. The scoring system has two explicit layers (Momentum Score + Entry Score) and a Final Score formula — this structure must be preserved.

### IV. Aesthetic Excellence
Dark-mode glassmorphism is the UI standard. Colour coding, hover states, and sortable tables are non-negotiable baseline features. Any new data column added to the backend must also be surfaced in the UI.

### V. Risk-First Output
Every result row must include Stop Loss, T1, T2, R:R Ratio, and Risk %. Stocks that do not meet the minimum R:R threshold (≥ 1.5) must be excluded from output — not just ranked lower. The scanner is a trading tool and must not present setups with poor risk/reward.

### VI. Benchmark Consistency
Relative Strength is always calculated vs the Nifty 500 index (`^CRSLDX`), with Nifty 50 (`^NSEI`) as fallback. The stock universe is always the Nifty 500 constituents. These two things are independent — the universe never changes.

---

## Technology Stack

- **Frontend & Backend**: Streamlit, Pandas, NumPy, yfinance, PyArrow, Pydantic.
- **Port**: 8501 (default Streamlit port, local only).
