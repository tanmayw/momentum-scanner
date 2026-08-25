# Swing Momentum Scanner — Implementation Plan

**Version**: 2.5.0 | **Last Updated**: 2026-08-25

---

## 1. Architecture Overview

A modular Streamlit application for Indian Equities (NSE) with local-first yfinance caching.

```
Browser (Desktop & Mobile Clients)
        ▲
        │ Websocket Connection
        ▼
Streamlit Controller (streamlit_app.py) — port 8501
        │
        ├── Session State Engine      → st.session_state (theme, app_view, results)
        │
        └── View 1: Swing Scanner (D · W · M)
              ├── get_nifty500_symbols() → NSE CSV 3-URL fallback chain
              ├── download_prices()      → yfinance batch, daily Parquet cache (<3s)
              ├── calculate_metrics()    → Multi-TF RSI, EMA 20/50/200, ADX, ATR, RS
              ├── score_candidates()     → Momentum (60%) + Entry (40%), R:R ≥ 1.5 Gate
              └── style_dataframe()      → Theme-aware styled dataframe + TV links
```

---

## 2. Component Design & Responsibilities

### 2.1 UI Layer (`streamlit_app.py`)
- **Top Navigation**: Tri-mode selector (`🚀 Swing Momentum`, `⚡ Intraday MTF`, `🎯 Options Strategy`) and theme switcher pill toggle.
- **Hero Headers**: Mode-specific titles, live pulse dot, and market metadata badges.
- **Dynamic styled dataframe**: Displays sorted candidates with TradingView deep links.

---

## 3. Data Pipelines & Caching Strategy
- **Swing Scanner yfinance cache**: Daily OHLCV data for the Nifty 500 universe is cached on local disk (`cache/` directory, Parquet format, keyed by date) running in **< 3 seconds**.

---

## 4. Key Design Decisions
- **Tri-Mode Switcher in Top Nav**: Unifies swing screening, active intraday trading, and options execution into a single app.
- **Local Parquet Caching**: Speeds up swing scan load times from >30s to <3s.

---

## 5. Verification & Testing Strategy
- **Live Python Compilation**:
  - `python -m py_compile streamlit_app.py`
