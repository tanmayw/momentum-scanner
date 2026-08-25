# Performance Monitoring Specification

**Version**: 2.5.0 | **Last Updated**: 2026-08-25

---

## 1. Problem Statement

Traders require empirical validation of scanner recommendations to optimize strategies and monitor ongoing trades.

---

## 2. Mode 4: Performance Monitoring & Signal Tracking Specifications

The Performance Tracker evaluates the accuracy and outcomes of scanner recommendations:

### 2.1 Swing Signals Performance Tracking
- **Backfill Window**: Evaluates signals generated over the past 7 trading days.
- **Dynamic Calculation**: Runs daily metrics on sliced historical datasets up to each specific signal date.
- **Performance Cache**: Stores calculated historical signals at `cache/swing_signals_history.json` for sub-second page loads.
- **Outcome Determination**:
  - `Hit Target 5%`: High price reached Target 5% before Low price touched Stop Loss.
  - `Hit Target 2%`: High price reached Target 2% but didn't reach Target 5% before Stop Loss.
  - `Stopped Out`: Low price touched or breached Stop Loss (1.5 * ATR below entry close) before target was achieved.
  - `Active`: Currently trading and has not hit either target or stop loss.

### 2.2 Intraday & Options Performance Tracking
- **Intraday 15m Tracking**: Scans F&O High Momentum universe over the past 5 trading days using 15m historical price action. Tracks if subsequent 15m bars hit Target 1% (+1%), Target 2% (+2%), or Stop Loss (1.5 * ATR below entry price) first.
- **Options Spread Simulation**: Backfills options spreads (Bull Call / Bear Put debit spreads) and calculates estimated payoffs and P&L based on the spot price movements of the underlying assets.

### 2.3 Manual Tracking & Persistent Watchlist
- **Persistent Storage**: Tracks manually added signals inside `cache/tracked_signals.json`.
- **Target Selection**:
  - Swing scanner results page includes a dropdown of qualified signals and a Track button.
  - Intraday deep-dive page contains a `📌 Track [Symbol] for Intraday Performance` button.
- **Evaluation Mechanism**:
  - Swing manual signals evaluate subsequent daily prices.
  - Intraday manual signals evaluate subsequent 15m price bars starting from the trigger timestamp.
- **Watchlist UI**: Shows KPI metrics (Win Rate, average return, active trades), a styled performance table, and a dropdown/button to remove symbols from tracking.

### 2.4 Performance Dashboard UI Elements
- **Performance KPIs**: Total Hits, Win Rate (closed trades), Average Return %, Max Return % Hit, and Active count.
- **Visual Analytics**: Daily hits distribution bar chart and Win/Loss outcomes bar chart.
- **Detailed History Log**: Fully styled dataframe highlighting green for profit/win outcomes and red for loss/stop outcomes, with TradingView links.
- **Exporting**: Instant dated CSV download of performance records.
