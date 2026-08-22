# Nifty 500 Scanner — Implementation Plan

**Version**: 2.0.0 | **Last Updated**: 2026-08-21

---

## 1. Architecture Overview

Unified Streamlit application, fully local, zero cloud dependency.

```
Browser (Streamlit Client)
        ▲
        │ Websocket Connection
        ▼
Streamlit Server (streamlit_app.py) — port 8501
        │
        ├── get_nifty500_symbols()     → NSE CSV (3-URL fallback chain)
        ├── download_prices()          → yfinance batch (80/batch), Parquet cache
        ├── get_benchmark()            → ^CRSLDX / ^NSEI fallback
        ├── calculate_metrics()        → per-stock OHLCV → indicators
        └── score_candidates()         → Momentum + Entry + Final Score
                │
                └── Render styled dataframe in browser
```

---

## 2. Application Controls (`streamlit_app.py`)

The user configures the scanner settings in the sidebar panel.

### 2.1 Scanner Parameters

| Parameter | Default | Description |
|---|---|---|
| `min_m` | 60 | Minimum Monthly RSI |
| `min_w` | 60 | Minimum Weekly RSI |
| `min_d` | 50 | Minimum Daily RSI |
| `min_adx` | 20 | Minimum ADX |
| `max_52w` | 10 | Max % distance from 52W high |
| `top_n` | 20 | Number of results to return |

### 2.3 Indicator Functions

| Function | Description |
|---|---|
| `rsi(s, period=14)` | Wilder's EMA-based RSI |
| `ema(s, period)` | Exponential Moving Average |
| `atr(df, period=14)` | Average True Range |
| `adx(df, period=14)` | True ADX with DM+/DM- |

### 2.4 Scoring Functions

| Function | Spec Section |
|---|---|
| `rsi_score(x, kind)` | §4 — RSI discrete table (monthly/weekly/daily) |
| `calc_trend_score(price, e20, e50, e200)` | §5 — 15/12/8/0 EMA alignment grades |
| `calc_rs_score(rs_decimal)` | §9 — RS discrete bucket (>+20%=5 … <0=0) |
| `calc_price_vs_ema20_score(price, e20)` | §13 Entry — distance above EMA20 |
| `calc_breakout_pullback_score(...)` | §13 Entry — breakout/pullback pattern + volume |
| `calc_rr_score(rr_ratio)` | §13 Entry — R:R quality score |

### 2.5 Data Pipeline

```
get_nifty500_symbols()
    → download_prices()         [cache: cache/prices_YYYY-MM-DD.parquet]
    → get_benchmark()           [^CRSLDX → ^NSEI fallback]
    → calculate_metrics()       [per stock row]
    → Hard Filter (Layer 1)
    → score_candidates()        [Momentum + Entry + Final Score]
    → R:R ≥ 1.5 filter
    → top_n results + Rank column
    → JSON response
```

### 2.6 Output Columns

`Rank, Symbol, Action, Price, Final Score, Momentum Score, Entry Score, Monthly RSI, Weekly RSI, Daily RSI, ADX, Vol Ratio, RR Ratio, Risk %, 3M Return, 6M Return, RS vs Nifty, 52W Distance, Stop Loss, Target 2%, Target 5%`

---

## 3. UI Design (`streamlit_app.py`)

### 3.1 Layout & Controls
- **Sidebar**: Integrates 6 slider controls (Monthly/Weekly/Daily RSI, ADX, 52W distance, Top N rows) and a `Run Scanner` button.
- **Main Panel**: Renders title, subtitle, calculation progress updates, results summary, CSV export download button, and the interactive results table.

### 3.2 Interactive Results Table
- Streamlit's `st.dataframe` renders the data with automatic multi-column sorting capability.
- Symbol tickers are formatted as clickable TradingView chart links.
- Uses pandas `Styler` map rules to apply visual color coding:
  - Action labels (BUY: green, WATCH: yellow, AVOID: red).
  - RSI heat (orange if >= 70, yellow if >= 60).
  - Return +/− (green/red).
  - Risk/Reward ratio quality (green if >= 2.0, yellow if >= 1.5).

---

## 4. Key Design Decisions

| Decision | Rationale |
|---|---|
| Percentile-bucket 3M/6M scoring (not continuous rank×10) | Prevents micro-differences from having outsized impact |
| RS discrete buckets (not rank) | Matches spec's explicit scoring table |
| Trend Score 15/12/8/0 (not binary) | Rewards partial alignment; penalises only sub-EMA200 |
| R:R computed before Entry Score | R:R feeds into Entry Score as a 5-pt component |
| R:R < 1.5 gate applied after scoring | Removes technically good but risk-unattractive setups |
| Nifty 500 benchmark (^CRSLDX → ^NSEI) | RS calculated vs same universe; Nifty 50 as safe fallback |
| Daily Parquet cache keyed by date | Skip 500-ticker download on repeated same-day runs |

---

## 5. Deployment

```bash
# Install dependencies
pip install -r requirements.txt

# Run server
streamlit run streamlit_app.py
# → http://localhost:8501
```

No Docker. No cloud. Fully local.
