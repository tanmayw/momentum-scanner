# Nifty 500 Momentum Scanner

A **local, FastAPI-powered** stock screener that scans all Nifty 500 constituents using a two-layer momentum scoring system — hard eligibility filters followed by a composite Momentum + Entry quality score — to surface the best swing trading setups every evening.

> **Tech stack**: Python · FastAPI · Pandas · yfinance · Vanilla HTML/CSS/JS

---

## Quick Start

```bash
# 1. Create and activate a virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the scanner
python app.py
```

Open your browser at **http://localhost:8502**

---

## How It Works

The scanner runs in two layers:

### Layer 1 — Hard Eligibility Filters
Reduces Nifty 500 → ~10–40 candidates by requiring:

| Filter | Default Threshold |
|---|---|
| Monthly RSI (14) | ≥ 60 |
| Weekly RSI (14) | ≥ 60 |
| Daily RSI (14) | ≥ 50 |
| Trend structure | Price > EMA20 > EMA50 > EMA200 |
| ADX (14) | ≥ 20 |
| Volume ratio | ≥ 1.0× (20-day avg) |
| 3-month return | > 0 |
| 6-month return | > 0 |
| Distance from 52W high | ≤ 10% |

All thresholds are adjustable via UI sliders.

### Layer 2 — Composite Scoring

| Sub-score | Components | Max |
|---|---|---|
| **Momentum Score** | M-RSI + W-RSI + D-RSI + Trend + ADX + 3M + 6M + RS + Volume + 52W | 100 |
| **Entry Score** | Momentum×0.40 + RSI setup + Price vs EMA20 + Breakout/Pullback + Volume + R:R | 100 |
| **Final Score** | `0.60 × Momentum + 0.40 × Entry` | 100 |

### Action Labels

| Score | Label |
|---|---|
| ≥ 85 | 🟢 BUY |
| 75–84 | 🟢 WATCH / BUY ON PULLBACK |
| 65–74 | 🟡 WATCHLIST |
| < 65 | 🔴 AVOID |

> Stocks with **R:R < 1.5** are excluded from output regardless of score.

---

## Output Columns

`Rank · Symbol · Action · Price · Final Score · Momentum Score · Entry Score · M-RSI · W-RSI · D-RSI · ADX · Vol Ratio · R:R · Stop Loss · T1 (2%) · T2 (5%) · 3M% · 6M% · RS vs Nifty · Risk%`

- **Symbol** — clickable link to the TradingView NSE chart
- **Column sorting** — click any header to sort ascending/descending
- **CSV export** — one-click download of results

---

## Project Structure

```
my-scanner/
├── app.py                  # FastAPI backend — all indicators, scoring, API
├── requirements.txt
├── cache/                  # Daily Parquet cache (auto-created)
├── static/
│   ├── index.html          # UI — sliders + results table
│   ├── style.css           # Dark glassmorphism theme
│   └── script.js           # Fetch, render, sort, CSV export
└── .specify/               # 📚 Project spec kit (see below)
    ├── spec.md             # Full scoring specification
    ├── plan.md             # Architecture & implementation plan
    ├── tasks.md            # Task history & backlog
    └── constitution.md     # Core design principles
```

---

## 📚 Specification Kit (`.specify/`)

The `.specify/` directory is the single source of truth for this project's design and implementation rules. Always consult these before making changes.

| File | Purpose |
|---|---|
| [`.specify/spec.md`](.specify/spec.md) | Complete scoring specification — every filter, scoring table, formula and output column defined |
| [`.specify/plan.md`](.specify/plan.md) | Architecture overview, data pipeline, component design, and key design decisions |
| [`.specify/tasks.md`](.specify/tasks.md) | Completed task history by phase + future backlog |
| [`.specify/constitution.md`](.specify/constitution.md) | Non-negotiable design principles (spec-driven scoring, risk-first output, local-first caching) |

> **Rule**: Any change to scoring weights, thresholds, or formula must update `spec.md` first.

---

## Caching

On first run each day, the app downloads 3 years of daily OHLCV data for all ~500 stocks via `yfinance` (takes ~60–90 seconds). Results are cached as a `.parquet` file in `cache/`. Subsequent runs that day are **fast** (< 5 seconds).

---

## Data Notes

- **Constituent list**: Fetched from Nifty Indices / NSE with a GitHub fallback. Verify before live use.
- **Price data**: Yahoo Finance via `yfinance`. Suitable for research — not exchange-grade real-time.
- **Benchmark**: Relative Strength calculated vs Nifty 500 index (`^CRSLDX`), falling back to Nifty 50 (`^NSEI`).
- **Higher-timeframe RSI**: Calculated from resampled weekly/monthly bars. A proper backtest must use point-in-time Nifty 500 membership to avoid survivorship bias.
