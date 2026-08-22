# Nifty Momentum & Intraday Scanner — Implementation Plan

**Version**: 2.4.0 | **Last Updated**: 2026-08-22

---

## 1. Architecture Overview

A modular Streamlit application for Indian Equities (NSE), providing both **Swing Momentum (D · W · M)** and **Intraday MTF (Daily · 1h · 15m)** scanning capabilities.

```
Browser (Desktop & Mobile Clients)
        ▲
        │ Websocket Connection
        ▼
Streamlit Controller (streamlit_app.py) — port 8501
        │
        ├── Session State Engine      → st.session_state (theme, app_view, results)
        │
        ├── View 1: Swing Scanner (D · W · M)
        │     ├── get_nifty500_symbols() → NSE CSV 3-URL fallback chain
        │     ├── download_prices()      → yfinance batch (80/batch), daily Parquet cache (<3s)
        │     ├── get_benchmark()        → Nifty 500 (^CRSLDX / ^NSEI fallback)
        │     ├── calculate_metrics()    → Multi-TF RSI, EMA 20/50/200, ADX, ATR, RS
        │     ├── score_candidates()     → Momentum (60%) + Entry (40%), R:R ≥ 1.5 Gate
        │     └── style_dataframe()      → Theme-aware styled dataframe + TV links
        │
        └── View 2: Intraday MTF Scanner (Daily · 1h · 15m) [intraday_scanner.py]
              ├── PRESET_UNIVERSES       → Nifty 50, F&O Beta, Banks, IT, Auto/Metals
              ├── download_intraday_timeframes() → Daily (2y), 1h (60d), 15m (30d)
              ├── evaluate_stock_intraday()      → Multi-TF RSI, Trend, VWAP, Breakout, ATR
              ├── score_intraday_signal()        → 0-100 composite scoring & setup tagging
              ├── calculate_position_size()      → Dynamic fractional share sizing
              ├── style_intraday_dataframe()     → Intraday signal badges & TV links
              └── 15m Price & VWAP Charts        → Deep-dive tab with interactive line chart
```

---

## 2. Component Design & Responsibilities

### 2.1 UI Layer (`streamlit_app.py`)
- **Top Navigation**: Dual-mode selector (`🚀 Swing Momentum` vs `⚡ Intraday MTF`) and theme switcher pill toggle.
- **Hero Headers**: Mode-specific titles, live pulse dot, and market metadata badges.
- **Controls & Expanders**: Inline, mobile-friendly expanders housing threshold sliders, universe selectors, and capital/risk inputs.
- **KPI Summary Grid**: 6 metric cards displaying signal counts, top scores, and risk/reward ratios.
- **Tabular Outputs**: Theme-aware styled dataframes with color-coded Action/Signal badges, JetBrains Mono font, and clickable TradingView chart links.
- **Intraday Deep-Dive Tab**: Real-time stock selector, diagnostic cards, position sizing summaries, and 15-minute price vs VWAP/EMA charts.

### 2.2 Intraday Engine Layer (`intraday_scanner.py`)
- **Indicator Functions**: `rsi()`, `ema()`, `atr()`, `vwap()`, `volume_ratio()`, `prepare_df()`.
- **Position Sizing**: `calculate_position_size(capital, risk_pct, entry, stop)`.
- **Multi-Timeframe Fetcher**: `download_intraday_timeframes(symbol)`.
- **Scoring & Evaluation**: `evaluate_stock_intraday()`, `score_intraday_signal()`.
- **Batch Universe Scanner**: `scan_intraday_universe(symbols, ...)`.

---

## 3. Data Pipelines & Caching Strategy

### 3.1 Swing Scanner Pipeline (Daily Parquet Cache)
```
get_nifty500_symbols()
    → check cache/prices_YYYY-MM-DD.parquet
    → if miss: yfinance batch download (~60s) → save parquet
    → if hit: read parquet (<2s)
    → get_benchmark()
    → calculate_metrics() (500 tickers)
    → Layer 1 Hard Filters
    → Layer 2 Composite Scoring (Momentum + Entry)
    → Minimum R:R ≥ 1.5 Gate
    → Render ranked table + KPIs + TV links
```

### 3.2 Intraday MTF Pipeline (On-Demand Bundles)
```
Select Universe (Preset, Custom, or Swing shortlist)
    → fetch (2y 1d, 60d 1h, 30d 15m) per symbol
    → compute VWAP, ATR(14), EMA 9/20/50, RSI across timeframes
    → evaluate 20-bar 15m breakout & volume surge
    → score 0-100 pts & classify signal / setup
    → compute ATR stop loss & suggested position size
    → Render ranked table + KPIs + TV links + 15m chart
```

---

## 4. Key Design Decisions

| Decision | Rationale |
|---|---|
| Dual-Mode Switcher in Top Nav | Seamlessly unifies multi-day swing screening and active intraday screening in one app |
| Modular `intraday_scanner.py` | Keeps mathematical indicators and multi-timeframe fetching cleanly separated and testable |
| Multi-Timeframe Intraday Alignment (D $\to$ 1h $\to$ 15m) | Drastically reduces false breakout signals by confirming higher timeframe bullish momentum |
| Dynamic Position Sizing | Enforces strict risk management by automatically calculating exact share counts from stop loss |
| Theme-Aware Dataframe Styling | Guarantees accessible WCAG-compliant contrast in both Dark and Light modes |
| Daily Parquet Caching for Swing Mode | Reduces 500-stock swing scan time from ~60–90 seconds to under 3 seconds |

---

## 5. Verification & Testing Strategy

1. **Automated Unit Tests**:
   - `scratch/test_intraday_engine.py`: Validates indicator accuracy (Wilder's RSI, EMA, ATR, session VWAP, volume ratio), scoring boundaries, and position sizing formulas.
2. **Live Data Integration Tests**:
   - `scratch/test_live_intraday_scan.py`: Validates live multi-timeframe downloads and end-to-end signal computation on NSE symbols.
3. **Syntax & Compile Check**:
   - `python -m py_compile streamlit_app.py intraday_scanner.py`
