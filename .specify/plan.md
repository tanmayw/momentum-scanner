# Nifty Momentum, Intraday & Options Scanner — Implementation Plan

**Version**: 2.5.0 | **Last Updated**: 2026-08-23

---

## 1. Architecture Overview

A modular Streamlit application for Indian Equities (NSE), providing **Swing Momentum (D · W · M)**, **Intraday MTF (Daily · 1h · 15m)**, and **Options Chain Strategy Layer (MTF + Chain Gate)** capabilities.

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
        │     ├── download_prices()      → yfinance batch, daily Parquet cache (<3s)
        │     ├── calculate_metrics()    → Multi-TF RSI, EMA 20/50/200, ADX, ATR, RS
        │     ├── score_candidates()     → Momentum (60%) + Entry (40%), R:R ≥ 1.5 Gate
        │     └── style_dataframe()      → Theme-aware styled dataframe + TV links
        │
        ├── View 2: Intraday MTF Scanner (Daily · 1h · 15m) [intraday_scanner.py]
        │     ├── PRESET_UNIVERSES       → Nifty 50, F&O Beta, Banks, IT, Auto/Metals
        │     ├── download_intraday_timeframes() → Daily (2y), 1h (60d), 15m (30d)
        │     ├── evaluate_stock_intraday()      → Multi-TF RSI, Trend, VWAP, Breakout, ATR
        │     ├── calculate_position_size()      → Dynamic fractional share sizing
        │     └── 15m Price & VWAP Charts        → Deep-dive tab with interactive line chart
        │
        └── View 3: Options Strategy Layer (MTF + Chain Gate) [options_engine.py]
              ├── LOT_SIZES               → Instrument master lot size dictionary
              ├── fetch_or_simulate_option_chain() → Live & synthetic chain adapter
              ├── analyze_option_chain()  → Total OI, PCR, ATM IV, ATM Spread, 0-100 Score
              ├── recommend_strategy()    → Gated strategy selection (MTF ≥ 75 & Chain ≥ 75)
              ├── select_strikes()        → ATM & OTM leg pairing
              ├── price_strategy()        → Net premium, max profit, max loss, breakevens
              ├── generate_payoff_curve() → P&L curve across underlying price range
              └── Options Screener & Matrix → Batch strategy scanner & chain matrix table
```

---

## 2. Component Design & Responsibilities

### 2.1 UI Layer (`streamlit_app.py`)
- **Top Navigation**: Tri-mode selector (`🚀 Swing Momentum`, `⚡ Intraday MTF`, `🎯 Options Strategy`) and theme switcher pill toggle.
- **Hero Headers**: Mode-specific titles, live pulse dot, and market metadata badges.
- **Options Strategy Tab 1**: Single stock selector, MTF score/direction inputs, risk budget, strategy execution card, and visual payoff diagram.
- **Options Strategy Tab 2**: Batch Options Strategy Screener across F&O constituents.
- **Options Strategy Tab 3**: Full Option Chain Matrix table with formatted Calls vs Strikes vs Puts.

### 2.2 Options Engine Layer (`options_engine.py`)
- **Schema Validation**: `validate_chain(chain)`.
- **Chain Analytics**: `analyze_option_chain(chain, spot, underlying_direction)`.
- **Strategy & Strike Selection**: `select_strikes(chain, spot, strategy)`.
- **Pricing & Risk Gate**: `price_strategy(legs, strategy, lot_size)`, `recommend_strategy(...)`, `run_options_layer(...)`.
- **Payoff Simulation**: `generate_payoff_curve(strategy, legs, spot, lot_size)`.

---

## 3. Data Pipelines & Caching Strategy

### 3.1 Options Strategy Pipeline
```
Select Symbol & Input MTF Direction/Score
    → Fetch Option Chain (live yfinance or synthetic model)
    → Validate Columns (expiry, strike, option_type, ltp, bid, ask, vol, oi, chg_oi, iv)
    → Analyze Chain: PCR, Total OI, ATM IV, ATM Spread %, Chain Score (0-100)
    → Evaluate Gate: Chain Score ≥ 75 & MTF Score ≥ 75?
    → If Yes: Select Strikes (ATM + OTM) & Price Strategy (Net Prem, Max Loss, Max Profit, BE)
    → Evaluate Risk Gate: Max Loss ≤ Capital × Max Risk %?
    → If Passed: Render Execution Plan + Interactive Payoff Diagram + TV Link
```

---

## 4. Key Design Decisions

| Decision | Rationale |
|---|---|
| Tri-Mode Switcher in Top Nav | Unifies swing screening, active intraday trading, and options execution into a single app |
| Modular `options_engine.py` | Encapsulates Black-Scholes math, options scoring, and payoff curves in an independent tested module |
| Mandatory Dual-Gate Rule | Prevents options trading unless both underlying technicals (MTF $\ge 75$) and option chain liquidity/OI ($\ge 75$) align |
| Defined-Risk Spread Preference | Mitigates theta decay and vega risk compared to naked single-leg options |
| Visual Payoff Simulator | Provides immediate clarity on maximum risk, breakeven thresholds, and potential profit at expiry |

---

## 5. Verification & Testing Strategy

1. **Automated Unit Tests**:
   - `scratch/test_options_engine.py`: Validates schema validation, PCR math, chain scoring, strike selection, payoff math, and gating.
2. **Live Python Compilation**:
   - `python -m py_compile streamlit_app.py intraday_scanner.py options_engine.py`
