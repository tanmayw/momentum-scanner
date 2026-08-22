# Nifty 500 Scanner Specification

**Version**: 2.3.0 | **Last Updated**: 2026-08-22

---

## 1. Problem Statement

Traders and analysts need a fast, reliable, and programmatic way to scan the Nifty 500 index for high-quality momentum-based swing trading opportunities across multiple timeframes, ranked not by simple RSI but by a composite score that reflects both trend quality and entry timing — without relying on expensive SaaS tools.

---

## 2. Target Audience

- Retail swing traders analyzing Indian NSE markets targeting 2–5% monthly moves.
- Quantitative analysts seeking programmatic shortlists using RSI, ADX, EMA structure, relative strength and risk/reward.

---

## 3. Scoring Architecture (Two-Layer Design)

### Layer 1 — Hard Eligibility Filters

All of the following must be true for a stock to be considered:

| Filter | Threshold |
|---|---|
| Monthly RSI (14) | ≥ 60 (configurable) |
| Weekly RSI (14) | ≥ 60 (configurable) |
| Daily RSI (14) | ≥ 50 (configurable) |
| Price > EMA20 > EMA50 > EMA200 | Must hold |
| ADX (14) | ≥ 20 (configurable) |
| Volume / 20-day avg volume | ≥ 1.0 |
| 3-month return | > 0 |
| 6-month return | > 0 |
| Distance from 52-week high | ≤ 10% (configurable) |

### Layer 2 — Composite Scoring

Stocks passing Layer 1 are scored out of 100 across two sub-scores:

#### 2a. Momentum Score (out of 100)

| Factor | Max Points | Scoring Method |
|---|---|---|
| Monthly RSI | 15 | Discrete table: 60–64=10, 65–69=12, 70–74=15, 75–80=12, >80=8 |
| Weekly RSI | 15 | Same table as Monthly RSI |
| Daily RSI | 10 | Discrete table: 50–54=7, 55–59=10, 60–64=9, 65–69=7, 70–75=4, >75=2 |
| Trend Structure | 15 | 15 (full align), 12 (EMA50≈EMA200 within 2%), 8 (above EMA50>EMA200), 0 |
| ADX | 10 | <20=0, 20–24=5, 25–29=7, 30–39=10, 40–50=8, >50=6 |
| 3M Return | 10 | Percentile bucket: top 10%=10, 10–25%=8, 25–50%=6, 50–75%=4, bottom=0 |
| 6M Return | 10 | Same percentile bucket table as 3M |
| Relative Strength vs Nifty | 5 | Discrete: >+20%=5, +10–20%=4, +5–10%=3, 0–5%=1, <0=0 |
| Volume Expansion | 5 | <1.0=0, 1.0–1.2=2, 1.2–1.5=3, 1.5–2.0=4, >2.0=5 |
| Distance from 52W High | 5 | 0–5%=5, 5–10%=4, 10–15%=2, >15%=0 |

#### 2b. Entry Score (out of 100)

| Factor | Max Points | Scoring Method |
|---|---|---|
| Momentum Score contribution | 40 | Momentum Score × 0.40 |
| Daily RSI setup | 15 | 55–64=15, 50–54=12, 65–69=8, else=3 |
| Price vs EMA20 | 15 | 0–3% above=15, 3–8%=12, 8–15%=8, >15%=3, below=0 |
| Breakout / Pullback setup | 15 | Near 52W high + vol≥1.5x=15, pullback to EMA20=12, continuation=8, else=3 |
| Volume confirmation | 10 | ≥1.5x=10, ≥1.2x=7, else=4 |
| Risk / Reward | 5 | R:R≥2.5=5, ≥2.0=4, ≥1.5=3, ≥1.0=1, else=0 |

#### 2c. Final Score

```
Final Score = 0.60 × Momentum Score + 0.40 × Entry Score
```

#### 2d. Minimum R:R Gate

Stocks with **R:R < 1.5** are excluded from output, regardless of score.
(R:R = (Target 5% − Price) / (Price − Stop Loss))

---

## 4. Action Classification

| Final Score | Label |
|---|---|
| ≥ 85 | 🟢 BUY |
| 75–84 | 🟢 WATCH / BUY ON PULLBACK |
| 65–74 | 🟡 WATCHLIST |
| < 65 | 🔴 AVOID |

---

## 5. Risk Management Outputs

Per stock, the scanner calculates:

| Output | Formula |
|---|---|
| Stop Loss | Price − 1.5 × ATR(14) |
| Target 1 (T1) | Price × 1.02 |
| Target 2 (T2) | Price × 1.05 |
| Risk % | (Price − Stop Loss) / Price × 100 |
| R:R Ratio | (T2 − Price) / (Price − Stop Loss) |

---

## 6. Metrics Calculated Per Stock

Monthly RSI(14), Weekly RSI(14), Daily RSI(14), EMA 20/50/200, ADX(14), ATR(14), 20-day avg volume, 3-month return, 6-month return, 52-week high, Relative Strength vs Nifty 500 index (^CRSLDX, fallback ^NSEI).

---

## 7. UI / Output Features

- **Dual-Theme Engine (Dark & Light Mode)**:
  - **Dark Terminal Theme**: Deep navy background (`#050b14`), neon accents, glassmorphism cards, glowing green primary actions.
  - **Light Mode**: Clean slate background (`#f8fafc`), Slate-900 typography, deep Emerald (`#15803d`), warm Amber (`#b45309`), Royal Blue (`#1d4ed8`), and Crimson (`#b91c1c`) adhering to WCAG AAA contrast guidelines for optical comfort.
  - **Seamless Theme Switcher**: Secondary pill toggle in top navigation with instantaneous state persistence (`st.session_state.theme`).
- **Responsive Layout**:
  - Centered max-width container on desktop (`1040px`) to prevent ultra-wide stretching.
  - Seamless full-width adaptation on mobile viewports (Android/iOS).
  - Inline controls expander replacing hidden/collapsed mobile sidebars.
- **KPI Summary Dashboard**: 6 metric cards summarizing BUY Signals, Watch Candidates, Watchlist, Top Score, Average R:R, and Total Qualified Stocks.
- **Idle Welcome State**: Floating visual icon and 4-step interactive workflow guides (Filters → Scan → Signals → Charts).
- **Interactive Results Table**:
  - Symbol tickers formatted as direct clickable TradingView NSE chart links.
  - Custom monospace font (**JetBrains Mono**) for tabular numerical data and prices.
  - Dynamic theme-aware color mapping for Action badges, RSI heat, returns (+/−), and R:R quality.
  - Built-in multi-column sorting.
- **Exporting**: One-click dated CSV download.

---

## 8. Non-Functional Requirements

- **Performance**: Frontend loads instantly. Backend scan < 30 seconds (< 3 seconds if cached).
- **Caching**: Daily OHLCV data cached as `.parquet` in `cache/` directory, keyed by date.
- **Security & Portability**: Fully local execution via Streamlit — zero cloud dependencies or API keys required.
- **Resilience**: 3-URL fallback chain for Nifty 500 constituent list.
