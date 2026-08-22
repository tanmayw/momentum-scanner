# Nifty 500 Scanner — Task History

**Version**: 2.0.0 | **Last Updated**: 2026-08-21

---

## Phase 1: Environment & Tooling Setup ✅

- [x] 1.1 Update `requirements.txt` with `fastapi`, `uvicorn`, `pyarrow`, `pandas`, `yfinance`.
- [x] 1.2 Remove legacy Streamlit, Firebase, and Docker config files.
- [x] 1.3 Ensure local Python environment available.

---

## Phase 2: Backend v1 — Basic Scanner ✅

- [x] 2.1 Scaffold FastAPI app, mount `static/` directory.
- [x] 2.2 Define `ScanRequest` Pydantic model.
- [x] 2.3 Implement `rsi()`, `ema()`, `atr()`, `adx()` indicator functions.
- [x] 2.4 Implement daily Parquet caching in `download_prices()`.
- [x] 2.5 Implement `calculate_metrics()` (per-stock row builder).
- [x] 2.6 Implement `score_candidates()` (basic scoring + action labels).
- [x] 2.7 Expose `POST /api/scan` endpoint.

---

## Phase 3: Frontend v1 ✅

- [x] 3.1 Create `static/index.html` — slider controls + results table skeleton.
- [x] 3.2 Create `static/style.css` — dark glassmorphism theme.
- [x] 3.3 Create `static/script.js` — slider sync, fetch, DOM table render.
- [x] 3.4 Symbol cells render as TradingView links (`https://in.tradingview.com/chart/?symbol=NSE:<SYMBOL>`).

---

## Phase 4: Spec Alignment (ChatGPT Scoring Spec) ✅

Implemented all requirements from the two-layer momentum scoring specification.

### 4.1 Backend Scoring Fixes

- [x] **Trend Score 15/12/8/0**: Added `calc_trend_score()` with intermediate grades — 12 (EMA50 ≈ EMA200 within 2%), 8 (above EMA50>EMA200), 0 otherwise. Previously was binary 15/0.
- [x] **3M/6M discrete percentile buckets**: Changed from `rank(pct=True)*10` to spec's 5 buckets (top 10%=10, 10–25%=8, 25–50%=6, 50–75%=4, bottom=0).
- [x] **RS scoring discrete buckets**: Added `calc_rs_score()` mapping >+20%=5, +10–20%=4, +5–10%=3, 0–5%=1, <0=0. Previously used continuous rank.
- [x] **Entry Score: Price vs EMA20 (15 pts)**: Added `calc_price_vs_ema20_score()` — 0–3% above=15, 3–8%=12, 8–15%=8, >15%=3, below=0.
- [x] **Entry Score: Breakout/Pullback (15 pts)**: Added `calc_breakout_pullback_score()` combining price pattern + volume confirmation.
- [x] **Entry Score: R:R component (5 pts)**: Added `calc_rr_score()` — ≥2.5=5, ≥2.0=4, ≥1.5=3, ≥1.0=1, else=0.
- [x] **Entry Score formula corrected**: Now = Momentum×0.40 + RSI(15) + EMA20(15) + BP(15) + Vol(10) + RR(5) = 100.
- [x] **Minimum R:R = 1.5 gate**: Stocks with R:R < 1.5 removed after scoring.
- [x] **RR Ratio in output**: Added to API response and display columns.
- [x] **Benchmark changed to Nifty 500**: `get_benchmark()` tries `^CRSLDX` first, falls back to `^NSEI`.
- [x] **Rank column**: Added as first column in output.

### 4.2 Frontend Fixes

- [x] **All required columns visible**: Added Rank, Entry Score, T1 (2%), T2 (5%), R:R Ratio, 3M%, 6M%, RS vs Nifty, Risk% to results table.
- [x] **Sortable columns**: All 20 table headers are clickable — sort ascending/descending with ↑/↓ indicator.
- [x] **CSV export**: "⬇ Export CSV" button downloads dated CSV with all columns.
- [x] **Colour coding**: RSI heat (orange=≥70, yellow=≥60), returns (green/red), R:R (green≥2.0, yellow≥1.5).

---

## Phase 5: Infrastructure ✅

- [x] 5.1 Set up `.specify/` GitHub Spec Kit (spec.md, plan.md, tasks.md, constitution.md).
- [x] 5.2 Updated all spec kit files to reflect v2.0.0 implementation.

---

## Backlog / Future Enhancements

- [ ] B1. Backtest scoring rules over 5–10 years to validate the 2–5% monthly objective.
- [ ] B2. Sector/industry filter (show only specific NSE sectors).
- [ ] B3. Watchlist persistence (save/load to local JSON).
- [ ] B4. Progress streaming during scan (SSE or websocket for live status).
- [ ] B5. Market cap filter.
- [ ] B6. Weekly email/Telegram digest of top BUY candidates.
- [ ] B7. Chart thumbnails inline in the results table.
