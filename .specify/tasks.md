# Nifty Momentum, Intraday & Options Scanner — Task History

**Version**: 2.5.0 | **Last Updated**: 2026-08-23

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

- [x] 4.1 **Trend Score 15/12/8/0**: Added `calc_trend_score()` with intermediate grades.
- [x] 4.2 **3M/6M discrete percentile buckets**: Changed from continuous rank to spec's 5 buckets.
- [x] 4.3 **RS scoring discrete buckets**: Added `calc_rs_score()` mapping (>+20%=5 … <0=0).
- [x] 4.4 **Entry Score components**: Price vs EMA20 (15 pts), Breakout/Pullback (15 pts), R:R quality (5 pts).
- [x] 4.5 **Entry Score formula**: Now = Momentum×0.40 + RSI(15) + EMA20(15) + BP(15) + Vol(10) + RR(5) = 100.
- [x] 4.6 **Minimum R:R = 1.5 gate**: Stocks with R:R < 1.5 removed after scoring.
- [x] 4.7 **Benchmark changed to Nifty 500**: `get_benchmark()` tries `^CRSLDX` first, falls back to `^NSEI`.
- [x] 4.8 **Sortable columns & CSV export**: All columns sortable; download dated CSV.

---

## Phase 5: Streamlit Migration & Modern UI Redesign ✅

- [x] 5.1 Migrated application into unified `streamlit_app.py` for direct deployment on Streamlit Cloud & local.
- [x] 5.2 Redesigned UI with dark trading terminal aesthetic:
  - Hero header with animated live pulse dot.
  - 6 KPI summary cards (BUY Signals, Watch, Watchlist, Top Score, Avg R:R, Total Qualified).
  - JetBrains Mono font integration for numbers and tables.
  - Animated idle welcome screen with 4-step workflow guide.

---

## Phase 6: Mobile Responsiveness & Layout Refinement ✅

- [x] 6.1 Moved scanner controls from collapsed sidebar into an always-visible, inline `st.expander`.
- [x] 6.2 Added CSS rules to hide sidebar entirely on all screens for consistent cross-device experience.
- [x] 6.3 Constrained desktop container width to `1040px` centered to prevent ultra-wide distortion.
- [x] 6.4 Added `@media (max-width: 640px)` queries for Android/iOS mobile responsiveness.

---

## Phase 7: Dual-Theme Engine (Dark & Light Mode) ✅

- [x] 7.1 Implemented `st.session_state.theme` toggle button in top navigation bar.
- [x] 7.2 Designed and implemented complete `DARK` and `LIGHT` color palette dictionaries.
- [x] 7.3 Made `style_dataframe(df, theme)` theme-aware:
  - **Dark mode**: Vibrant neon accents (`#00ff88`, `#ffb800`, `#64b5f6`, `#ff5252`).
  - **Light mode**: Deep, high-contrast, eye-friendly tones (Emerald `#15803d`, Bronze `#b45309`, Indigo `#1d4ed8`, Crimson `#b91c1c`, Slate `#0f172a`).
- [x] 7.4 Replaced all hardcoded dark hex colors in Markdown, Idle state, and Legends with dynamic theme variables.

---

## Phase 8: Intraday Multi-Timeframe (MTF) Scanner Integration ✅

- [x] 8.1 Created `intraday_scanner.py` modular calculation engine:
  - Multi-timeframe data fetcher (Daily 2y, Hourly 60d, 15m 30d).
  - Intraday technical indicators: Wilder's RSI, EMA 9/20/50, Daily session VWAP, ATR, Volume Ratio.
  - Composite Intraday Score (0–100 pts) and Signal categorization (`STRONG BUY`, `BUY ON CONFIRMATION`, `WATCH`, `NO TRADE`).
  - Setup tag classification (`BREAKOUT`, `VWAP MOMENTUM`, `PULLBACK / RECLAIM`, `WAIT`).
  - Fixed-fractional position sizing calculator based on capital and 15m ATR stop loss.
  - Preset stock universes (Nifty 50 Liquid, High Momentum/Beta F&O, Bank/Fin, IT/Tech, Auto/Metals).
- [x] 8.2 Integrated Dual-Mode view switcher into top navigation bar of `streamlit_app.py`:
  - `🚀 Swing Momentum (D · W · M)`
  - `⚡ Intraday MTF (Daily · 1h · 15m)`
- [x] 8.3 Built Intraday UI with 2 tabs:
  - **🔥 Intraday Scanner**: Preset & custom universe selector, handoff from swing scan, technical & risk controls, 6 Intraday KPI cards, styled data table with TradingView links, CSV export.
  - **🔍 Stock Deep-Dive & Charts**: Interactive ticker selector, metric cards, risk & execution plan card, 15-minute price vs VWAP/EMA line charts.
- [x] 8.4 Created automated unit tests in `scratch/test_intraday_engine.py` and live scan validation script in `scratch/test_live_intraday_scan.py`.
- [x] 8.5 Updated `README.md`, `.specify/constitution.md`, `.specify/spec.md`, `.specify/plan.md`, and `.specify/tasks.md`.

---

## Phase 9: Options Chain Strategy Layer Integration ✅

- [x] 9.1 Created `options_engine.py` modular calculation & strategy module:
  - Chain validation: `expiry`, `strike`, `option_type`, `ltp`, `bid`, `ask`, `volume`, `oi`, `change_oi`, `iv`.
  - Option Chain Analytics & Scoring (0–100 pts) assessing total OI bias, change in OI, volume, ATM IV, ATM bid/ask spread %, PCR, and strike depth.
  - Strategy recommendation gated by MTF Score ($\ge 75$) + Chain Score ($\ge 75$): `BULL_CALL_SPREAD`, `BEAR_PUT_SPREAD`, `LONG_STRANGLE`.
  - Strike selection (`select_strikes`) for ATM buy legs and OTM sell legs.
  - Pricing & Payoffs (`price_strategy`): Net premium, max loss, max profit, breakevens, and risk-reward ratio.
  - Risk Budget Gate: Restricts trades where max loss exceeds user's capital risk budget.
  - Payoff curve generator (`generate_payoff_curve`) plotting P&L at expiry.
  - Instrument master lot size dictionary (`LOT_SIZES`) and live/synthetic data adapter (`fetch_or_simulate_option_chain`).
- [x] 9.2 Upgraded `streamlit_app.py` top navigation to Tri-Mode Switcher:
  - `🚀 Swing Momentum (D · W · M)`
  - `⚡ Intraday MTF (Daily · 1h · 15m)`
  - `🎯 Options Strategy (MTF + Chain Gate)`
- [x] 9.3 Built 3 Options Dashboard Tabs:
  - **🎯 Single Stock Strategy & Payoff**: Parameter controls, 6 KPI cards, execution plan card, selected legs table, interactive payoff diagram, and diagnostic checklist.
  - **⚡ Options Strategy Screener**: Multi-asset F&O batch screener ranking qualified spreads.
  - **📊 Option Chain Matrix Table**: Real-time formatted Calls vs Strikes vs Puts matrix with ATM indicators.
- [x] 9.4 Created unit test script `scratch/test_options_engine.py` validating all calculations, gating rules, and payoff simulations.
- [x] 9.5 Updated `README.md`, `.specify/constitution.md`, `.specify/spec.md`, `.specify/plan.md`, and `.specify/tasks.md`.

---

## Phase 10: NSE Data Source & Theme Defaults ✅

- [x] 10.1 Changed default Streamlit theme to Light Mode in `.streamlit/config.toml`.
- [x] 10.2 Rewrote `fetch_or_simulate_option_chain` to pull data directly from official NSE India APIs instead of `yfinance`.
- [x] 10.3 Added index/equity routing and session cookie acquisition for NSE Option Chains.
- [x] 10.4 Added `NIFTY` to the default F&O universe list in `streamlit_app.py` and `intraday_scanner.py`.

---

## Backlog / Future Enhancements

- [ ] B1. Greeks calculation (Delta, Gamma, Theta, Vega) using analytical Black-Scholes formulas.
- [ ] B2. Multi-leg custom strategy builder (Iron Condor, Iron Butterfly, Calendar Spreads).
- [ ] B3. Live WebSocket feed integration for real-time NSE options chain updates.
- [ ] B4. Sector/industry filter (show only specific NSE sectors).
- [ ] B5. Watchlist persistence (save/load to local JSON or browser session).
- [ ] B6. Weekly email/Telegram digest of top qualified options setups.
