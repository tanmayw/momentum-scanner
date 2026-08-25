# Options Strategy Engine — Implementation Plan

**Version**: 2.5.0 | **Last Updated**: 2026-08-25

---

## 1. Architecture Overview & Components

```
Options Strategy Layer (MTF + Chain Gate) [options_engine.py]
      ├── LOT_SIZES               → Instrument master lot size dictionary
      ├── recommend_strategy()    → Gated strategy selection (MTF ≥ 75 & Chain ≥ 75)
      ├── select_strikes()        → ATM & OTM leg pairing
      ├── price_strategy()        → Net premium, max profit, max loss, breakevens
      ├── generate_payoff_curve() → P&L curve across underlying price range
      └── Options Screener & Matrix → Batch strategy scanner & chain matrix table
```

---

## 2. Key Design Decisions
- **Defined-Risk Spreads**: Prioritizes spreads over naked positions to cap risk.
- **Visual Payoff Simulator**: Uses Streamlit charts to display payoff calculations at expiration.

---

## 3. Verification & Testing Strategy
- **Unit Tests**:
  - Run `scratch/test_options_engine.py` to validate strategy scoring, strike pairings, and payoff math.
