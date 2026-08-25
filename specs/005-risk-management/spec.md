# Risk Management Specification

**Version**: 2.5.0 | **Last Updated**: 2026-08-25

---

## 1. Problem Statement

Trading without predefined risk gates and dynamic position sizing exposes capital to catastrophic tail risks. This module establishes a strict risk-first framework across swing, intraday, and options trading modes.

---

## 2. Risk Management Specifications

### 2.1 Intraday Position Sizing
- Stop Loss: $1.5 \times \text{ATR}(14)$ below the entry close.
- Targets: Target 1 at $+1\%$, Target 2 at $+2\%$ from entry price.
- Fractional Position Sizing formula:
$$\text{Quantity} = \left\lfloor \frac{\text{Capital} \times (\text{Risk \%} / 100)}{\text{Price} - \text{Stop Loss}} \right\rfloor$$

### 2.2 Swing Scanner Risk Gate
- Setups with a Risk/Reward (R:R) ratio $< 1.5$ are strictly excluded from scanner outputs.

### 2.3 Options Risk Budget Gate
- Restricts recommendable strategies where the maximum potential loss exceeds the user's defined risk budget:
$$\text{Max Loss} \le \text{Capital} \times (\text{Max Risk \%} / 100)$$
- If the Max Loss of a recommended spread exceeds this budget, the system gates the trade out with a `"Maximum loss exceeds risk budget"` status.
- Preference for defined-risk debit spreads (e.g. Bull Call Spread, Bear Put Spread) over naked single-leg options.
