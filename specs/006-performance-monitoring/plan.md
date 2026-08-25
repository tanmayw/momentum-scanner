# Performance Monitoring — Implementation Plan

**Version**: 2.5.0 | **Last Updated**: 2026-08-25

---

## 1. Component Design & Implementation

### 1.1 Performance Engine (`performance_monitor.py`)
- **backfill & caching**: Logic to scan the past 7 days of daily price action and store outcomes in `cache/swing_signals_history.json`.
- **manual watchlist persistence**: Helper functions `load_tracked_signals()`, `save_tracked_signals()`, `add_tracked_signal()`, and `evaluate_tracked_signals_performance()` utilizing `cache/tracked_signals.json`.
- **intraday backtester**: Logic to load 15-minute historical bars for F&O High Momentum stocks and check outcome flags.
- **options simulator**: Estimates debit spread payoffs based on spot price movement.

### 1.2 Dashboard UI Views (`streamlit_app.py`)
- **📊 Performance Monitor Tab**: Renders Win/Loss bar charts, KPI summary cards, dated CSV download button, and detailed signal tables.
- **📌 Track watchlist UI**: Displays active manually-tracked trades and provides an "Untrack" button to remove entries.
