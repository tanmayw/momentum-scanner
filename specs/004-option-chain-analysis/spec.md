# Option Chain Analysis Specification

**Version**: 2.5.0 | **Last Updated**: 2026-08-25

---

## 1. Problem Statement & Target Audience

Traders require quick assessment of option chain liquidity, open interest (OI) clustering, and implied volatility (IV) levels to identify liquid instruments and trade gating.

---

## 2. Option Chain Scoring & Gating

### 2.1 Option Chain Scoring Matrix (0–100 pts)

| Factor | Points | Evaluation Rule |
|---|---|---|
| **Total OI Structure** | 20 / 12 / 8 | Bullish: Put OI > Call OI & Put chg > 0 $\to$ 20. Bearish: Call OI > Put OI & Call chg > 0 $\to$ 20. |
| **Change in OI** | 15 / 7 | Bullish: Put Chg > Call Chg $\to$ 15. Bearish: Call Chg > Put Chg $\to$ 15. |
| **Volume Presence** | 10 | Total Option Volume $> 0 \to 10$. |
| **ATM Implied Volatility (IV)** | 15 / 10 / 5 | $< 20\% \to 15$, $20-30\% \to 10$, $30-40\% \to 5$, $\ge 40\% \to 0$. |
| **Bid/Ask Spread Liquidity** | 15 / 10 / 5 | $\le 2\% \to 15$, $\le 5\% \to 10$, $\le 10\% \to 5$, $> 10\% \to 0$. |
| **Put-Call Ratio (PCR)** | 10 / 5 | Bullish: $1.0 \le \text{PCR} \le 1.5 \to 10$. Bearish: $0.6 \le \text{PCR} \le 1.0 \to 10$. Neutral: $0.8 \le \text{PCR} \le 1.3 \to 10$. |
| **ATM Strike Liquidity** | 10 / 5 | $\ge 2$ active ATM strikes with verified volume & OI $\to 10$. |
| **Strike Depth** | 5 | $\ge 5$ available strikes $\to 5$. |

---

## 3. Option Chain Matrix UI Specifications
- **Option Chain Matrix Tab**: Real-time formatted Calls vs Strikes vs Puts matrix table with ATM highlighted indicators, displaying bid, ask, volume, and IV.
