# Risk Management — Implementation Plan

**Version**: 2.5.0 | **Last Updated**: 2026-08-25

---

## 1. Component Design & Implementation

### 1.1 Position Sizing & Stops (`intraday_scanner.py`)
- `evaluate_stock_intraday(...)` calculates Stop Loss using $1.5 \times \text{ATR}$ and target thresholds.
- `calculate_position_size(...)` implements fractional share math based on stop loss distance and user risk parameters.

### 1.2 Options Risk Gating (`options_engine.py` / `streamlit_app.py`)
- Options engine checks lot size and premium costs to calculate max loss.
- Gating logic blocks the recommended strategy execution card if it violates:
  `max_loss > capital * (risk_pct / 100)`

---

## 2. Key Design Decisions
- **Strict Risk Gates**: Hard gates in the UI block executions and scan listings that exceed risk parameters.
- **Preference for Spreads**: The scoring engine favors spreads because they have a fixed, predefined maximum loss.
