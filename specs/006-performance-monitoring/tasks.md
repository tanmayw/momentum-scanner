# Performance Monitoring — Task History

**Version**: 2.5.0 | **Last Updated**: 2026-08-25

---

## Phase 11: Performance Monitoring & Signal Tracking ✅
- [x] 11.1 Create modular `performance_monitor.py` for signal backfilling, performance evaluation, caching, and outcome logic.
- [x] 11.2 Re-enabled `🎯 Options Strategy` tri-mode navigation in `streamlit_app.py`.
- [x] 11.3 Added `📊 Performance Monitor` mode as the fourth radio button in navigation.
- [x] 11.4 Build performance tabs: Swing report (caching historical signals in `swing_signals_history.json`, outcome logic, win rate, return stats) and Intraday/Options report (15m evaluation of F&O universe, options spread P&L simulation).
- [x] 11.5 Integrated charts (daily signal counts and Win/Loss outcome distribution) and generic performance table styling.
- [x] 11.6 Added dated CSV downloads for signal logs.

---

## Phase 12: Manual Signal Tracking & Watchlist ✅
- [x] 12.1 Added manual tracking backend helpers (`load_tracked_signals`, `save_tracked_signals`, `add_tracked_signal`, `evaluate_tracked_signals_performance`) in `performance_monitor.py`.
- [x] 12.2 Integrated `📌 Track Signal` button and symbol selector below Swing scan results.
- [x] 12.3 Integrated `📌 Track [Symbol] for Intraday Performance` button in Intraday Stock Deep-Dive.
- [x] 12.4 Added `📌 Tracked Watchlist (Manual)` tab under Performance Monitor to evaluate returns, P&L, targets, and stops of tracked setups in real-time.
- [x] 12.5 Added Untrack action allowing users to delete signals from the JSON watchlist.
- [x] 12.6 Create and pass unit tests in `test_performance_engine.py`.
- [x] 12.7 Update specifications (`spec.md`) and tasks (`tasks.md`) documentation.
