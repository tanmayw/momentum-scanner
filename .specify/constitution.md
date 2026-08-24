# Nifty Momentum, Intraday & Options Scanner Constitution

**Version**: 2.5.0 | **Ratified**: 2026-08-23

---

## Core Principles

### I. Simplicity, Performance & Tri-Mode Architecture
The application is a pure, self-contained Python & Streamlit application (`streamlit_app.py`, `intraday_scanner.py`, `options_engine.py`) providing three synchronized trading modes:
1. **Swing Momentum Scanner** (Daily · Weekly · Monthly across all Nifty 500 stocks).
2. **Intraday MTF Scanner** (Daily · Hourly · 15-Minute real-time execution with VWAP & ATR risk controls).
3. **Options Chain Strategy Layer** (Multi-Timeframe Gated Strategy Selection: Bull Call Spreads, Bear Put Spreads, Strangles, and Payoff Visualizations).
Zero third-party SaaS dependencies or paid data subscriptions are required.

### II. Local-First Caching & Fast Data Pipeline
- Daily OHLCV data for the Nifty 500 universe is cached on local disk (`cache/` directory, Parquet format, keyed by date) running in **< 3 seconds**.
- Intraday & Options scans fetch lightweight multi-timeframe bundles (`2y 1d`, `60d 1h`, `30d 15m`) and normalized option chains on-demand for targeted liquid universes.

### III. Spec-Driven Technical Engines
- **Swing Engine**: Strictly preserves the two-layer scoring architecture: Momentum Score (60%) + Entry Score (40%) = Final Score (100) mapped to discrete scoring tables defined in `spec.md`.
- **Intraday Engine**: Strictly implements Multi-Timeframe alignment (Daily & Hourly trend structure + 15m RSI, VWAP, EMA 9/20, volume surge, and 20-bar breakout).
- **Options Strategy Engine**: Strictly follows the mandatory flow: **MTF Direction/Score $\to$ Option Chain Analysis $\to$ Chain Gate ($\ge 75$) $\to$ Strategy Selection $\to$ Strike Selection $\to$ Risk Gate $\to$ Execution Recommendation**.

### IV. Aesthetic Excellence & Dual-Theme Consistency
- Dual-theme engine (Light Mode by default & Accessible Dark Terminal) is standard across all views.
- Monospace typography (`JetBrains Mono`) for financial figures, custom KPI cards, responsive layout (`1060px` desktop container, mobile-first expanders), and interactive TradingView deep links.

### V. Risk-First Output & Dynamic Position Sizing
- **Swing Mode**: Setups with Risk/Reward < 1.5 are strictly excluded from output.
- **Intraday Mode**: Every candidate computes an automated 15m ATR Stop Loss, Target 1 (+1%), Target 2 (+2%), and a fractional position size calculated from user capital and risk %.
- **Options Mode**: Fixed-risk debit spreads are prioritized over naked options; trades where Max Loss exceeds the user's defined risk budget are gated out (`"Maximum loss exceeds risk budget"`).

### VI. Universe Flexibility & Cross-Module Handoff
- Swing mode always operates on the full Nifty 500 constituent list.
- Intraday & Options modes support liquid presets (Nifty 50, F&O High Beta, Banks, IT, Auto/Metals), custom symbol watchlists, and direct 1-click handoff between modules.

---

## Technology Stack

- **Framework**: Streamlit (`>=1.30.0`)
- **Data Engine**: Pandas (`>=2.2`), NumPy (`>=1.26`), PyArrow (`>=15.0.0`), yfinance (`>=0.2.50`), Requests (`>=2.31`) (for NSE API)
- **Port**: 8501 (default Streamlit port, local/cloud deployment)
