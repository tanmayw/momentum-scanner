# Nifty Momentum & Intraday Scanner Constitution

**Version**: 2.4.0 | **Ratified**: 2026-08-22

---

## Core Principles

### I. Simplicity, Performance & Dual-Mode Architecture
The application is a pure, self-contained Python & Streamlit application (`streamlit_app.py` + `intraday_scanner.py`) providing two distinct trading modes:
1. **Swing Momentum Scanner** (Daily · Weekly · Monthly across all Nifty 500 stocks).
2. **Intraday MTF Scanner** (Daily · Hourly · 15-Minute real-time execution with VWAP & ATR risk controls).
Zero third-party SaaS dependencies or paid data subscriptions are required.

### II. Local-First Caching & Fast Data Pipeline
- Daily OHLCV data for the Nifty 500 universe is cached on local disk (`cache/` directory, Parquet format, keyed by date).
- Subsequent swing scans execute in **< 3 seconds**.
- Intraday scans fetch lightweight multi-timeframe bundles (`2y 1d`, `60d 1h`, `30d 15m`) on-demand for targeted liquid universes.

### III. Spec-Driven Technical Engines
- **Swing Engine**: Strictly preserves the two-layer scoring architecture: Momentum Score (60%) + Entry Score (40%) = Final Score (100) mapped to discrete scoring tables defined in `spec.md`.
- **Intraday Engine**: Strictly implements Multi-Timeframe alignment (Daily & Hourly trend structure + 15m RSI, VWAP, EMA 9/20, volume surge, and 20-bar breakout).

### IV. Aesthetic Excellence & Dual-Theme Consistency
- Dual-theme engine (Dark Terminal & Accessible Light Mode) is standard across all views.
- Monospace typography (`JetBrains Mono`) for financial figures, custom KPI cards, responsive layout (`1060px` desktop container, mobile-first expanders), and interactive TradingView deep links.

### V. Risk-First Output & Dynamic Position Sizing
- **Swing Mode**: Setups with Risk/Reward < 1.5 are strictly excluded from output.
- **Intraday Mode**: Every candidate computes an automated 15m ATR Stop Loss, Target 1 (+1%), Target 2 (+2%), and a fractional position size (exact share quantity) calculated from user capital and risk %.

### VI. Universe Flexibility with Seamless Handoff
- Swing mode always operates on the full Nifty 500 constituent list.
- Intraday mode supports liquid presets (Nifty 50, F&O High Beta, Banks, IT, Auto/Metals), custom symbol watchlists, and direct 1-click handoff of top qualified swing candidates.

---

## Technology Stack

- **Framework**: Streamlit (`>=1.30.0`)
- **Data Engine**: Pandas (`>=2.2`), NumPy (`>=1.26`), PyArrow (`>=15.0.0`), yfinance (`>=0.2.50`), Requests (`>=2.31`)
- **Port**: 8501 (default Streamlit port, local/cloud deployment)
