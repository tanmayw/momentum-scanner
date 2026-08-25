# Option Chain Analysis — Task History

**Version**: 2.5.0 | **Last Updated**: 2026-08-25

---

## Phase 10: NSE Data Source & Theme Defaults ✅
- [x] 10.1 Changed default Streamlit theme to Light Mode in `.streamlit/config.toml`.
- [x] 10.2 Rewrote `fetch_or_simulate_option_chain` to pull data directly from official NSE India APIs instead of `yfinance`.
- [x] 10.3 Added index/equity routing and session cookie acquisition for NSE Option Chains.
- [x] 10.4 Added `NIFTY` to the default F&O universe list in `streamlit_app.py` and `intraday_scanner.py`.
