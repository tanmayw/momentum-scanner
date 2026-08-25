# Risk Management — Task History

**Version**: 2.5.0 | **Last Updated**: 2026-08-25

---

## Phase 8.1: Intraday Risk Management ✅
- [x] 8.1.1 Implement ATR-based Stop Loss ($1.5 \times \text{ATR}$) in `intraday_scanner.py`.
- [x] 8.1.2 Implement dynamic fractional position sizing based on account capital and risk percentage:
  `Qty = (Capital * Risk%) / (Price - Stop)`

## Phase 9.1: Options Risk Management ✅
- [x] 9.1.1 Implement Options Risk Budget Gate in `options_engine.py` restricting trades where max loss exceeds capital risk budget.
- [x] 9.1.2 Render warning diagnostic `"Maximum loss exceeds risk budget"` in the Streamlit UI execution card when gating is active.
- [x] 9.1.3 Default strategies to defined-risk spreads (Bull Call Spread, Bear Put Spread) instead of naked single-leg options.
