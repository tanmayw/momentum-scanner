# Intraday Multi-Timeframe Scanner — Implementation Plan

**Version**: 2.5.0 | **Last Updated**: 2026-08-25

---

## 1. Component Design & Responsibilities

### 1.1 Intraday Controller & Indicators (`intraday_scanner.py`)
- **PRESET_UNIVERSES**: Nifty 50, F&O Beta, Banks, IT, Auto/Metals.
- **Data fetcher**: Downloads Daily (2y), Hourly (60d), and 15m (30d) timeframes.
- **Indicator Engine**: Implements Wilder's RSI, EMA 9/20/50, session VWAP, and volume surges.
- **Intraday Scoring**: Evaluates the 0–100 matrix and tags signals.

### 1.2 UI Views (`streamlit_app.py`)
- **🔥 Intraday Scanner Tab**: Setup filters, KPI metrics, dynamic results table.
- **🔍 Stock Deep-Dive Tab**: Interactive ticker select, 15m price vs VWAP / EMA line charts.
- **Cross-Module Handoff**: Supports passing swing shortlists directly into the custom intraday scan.

---

## 2. Verification & Testing Strategy
- **Verification Scripts**:
  - Run `scratch/test_live_intraday_scan.py` to test indicator calculations on live NSE symbols.
  - Run `scratch/test_intraday_engine.py` unit tests.
