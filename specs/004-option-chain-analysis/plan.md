# Option Chain Analysis — Implementation Plan

**Version**: 2.5.0 | **Last Updated**: 2026-08-25

---

## 1. Component Design & Data Pipelines

### 1.1 Ingestion & Scoring (`options_engine.py`)
- **direct NSE India API Ingestion**: Rewrote `fetch_or_simulate_option_chain` to pull data directly from official NSE India APIs instead of `yfinance`.
- **validation**: Schema validation checking required fields (`expiry`, `strike`, `option_type`, `ltp`, `bid`, `ask`, `volume`, `oi`, `change_oi`, `iv`).
- **scoring engine**: `analyze_option_chain(chain, spot, underlying_direction)` calculates the 0–100 score.

### 1.2 Dashboard views (`streamlit_app.py`)
- **📊 Option Chain Matrix Table Tab**: Integrates with the API fetcher to render the Calls vs Strikes vs Puts matrix table.
- **Index/Equity Routing**: Acquisition of session cookies for NSE Option Chain fetches.
