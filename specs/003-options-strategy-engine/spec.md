# Options Strategy Engine Specification

**Version**: 2.5.0 | **Last Updated**: 2026-08-25

---

## 1. Problem Statement & Target Audience

Traders need defined-risk options spreads matched to technical bias to prevent catastrophic losses from theta decay and volatility spikes.

- **Target Audience**: Derivatives & Options Traders looking for automated, structured, and liquid spreads (debit spreads and strangles).

---

## 2. Mode 3: Options Strategy Layer

### 2.1 Strategy Selection & Payoff Formulas

| Strategy | Buy Leg | Sell Leg | Net Premium | Max Loss | Max Profit | Breakeven |
|---|---|---|---|---|---|---|
| **Bull Call Spread** | ATM CE | OTM CE ($+3\%$) | $P_{\text{buy}} - P_{\text{sell}}$ | $\text{Net} \times \text{Lot}$ | $(K_2 - K_1 - \text{Net}) \times \text{Lot}$ | $K_1 + \text{Net}$ |
| **Bear Put Spread** | ATM PE | OTM PE ($-3\%$) | $P_{\text{buy}} - P_{\text{sell}}$ | $\text{Net} \times \text{Lot}$ | $(K_1 - K_2 - \text{Net}) \times \text{Lot}$ | $K_1 - \text{Net}$ |
| **Long Strangle** | OTM CE ($+1.5\%$) | OTM PE ($-1.5\%$) | $P_{\text{call}} + P_{\text{put}}$ | $\text{Net} \times \text{Lot}$ | Unlimited | $K_{\text{call}} + \text{Net}$, $K_{\text{put}} - \text{Net}$ |

---

## 3. Options UI & Dashboard Specifications
- **Single Stock Strategy & Payoff Tab**: Parameter controls, 6 KPI cards, execution plan card, selected legs table, interactive payoff diagram at expiry.
- **Options Strategy Screener Tab**: Multi-asset F&O batch screener ranking qualified spreads.
