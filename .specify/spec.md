# Nifty 500 Scanner Specification

**Version**: 2.0.0 | **Last Updated**: 2026-08-21

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

- **Adjustable sliders**: Monthly RSI min, Weekly RSI min, Daily RSI min, ADX min, Max 52W distance, Rows to display.
- **Results table columns**: Rank, Symbol (TradingView link), Action, Price, Final Score, Momentum Score, Entry Score, M-RSI, W-RSI, D-RSI, ADX, Vol Ratio, R:R, Stop Loss, T1 (2%), T2 (5%), 3M%, 6M%, RS vs Nifty, Risk%.
- **Sortable columns**: Click any column header to sort ascending/descending.
- **CSV export**: One-click download of results as a dated CSV file.
- **Colour coding**: RSI heat (orange/yellow), returns (green/red), R:R quality (green/yellow).

---

## 8. Non-Functional Requirements

- **Performance**: Frontend loads instantly. Backend scan < 30 seconds (< 3 seconds if cached).
- **Caching**: Daily OHLCV data cached as `.parquet` in `cache/` directory, keyed by date.
- **Security**: Fully local — no cloud APIs, no credentials exposed.
- **Resilience**: 3-URL fallback chain for Nifty 500 constituent list.
