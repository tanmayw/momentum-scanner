# Swing Momentum Scanner Specification

**Version**: 2.5.0 | **Last Updated**: 2026-08-25

---

## 1. Problem Statement & Target Audience

Traders and quantitative analysts need a fast, reliable, and programmatic swing trading screener for Indian NSE equities that provides swing trading shortlists across all Nifty 500 stocks based on multi-timeframe momentum alignment (Daily, Weekly, Monthly) and entry timing.

- **Target Audience**: Swing Traders scanning the full Nifty 500 universe post-market for high-probability 2–5% multi-day swing setups.

---

## 2. Mode 1: Swing Momentum Scanner (D · W · M)

### 2.1 Architecture Overview

```mermaid
flowchart TD
    Universe["Nifty 500 Constituents (~500 stocks)"] --> L1{"Layer 1: Hard Filters\n• Multi-TF RSI: M≥60, W≥60, D≥50\n• Trend: Price > EMA20 > EMA50 > EMA200\n• Trend Strength: ADX(14) ≥ 20\n• Volume: Vol/20D Avg ≥ 1.0\n• Returns: 3M > 0 & 6M > 0\n• Proximity: 52W Distance ≤ 10%"}

    L1 -- "Pass (~10–40 stocks)" --> L2A["Momentum Score (out of 100)\n• Multi-TF RSI (40 pts)\n• Trend Alignment (15 pts)\n• ADX (10 pts)\n• 3M & 6M Returns (20 pts)\n• RS vs Nifty 500 (5 pts)\n• Volume Expansion (5 pts)\n• 52W Proximity (5 pts)"]
    L1 -- "Fail" --> Out["Excluded"]

    L2A --> L2B["Entry Score (out of 100)\n• Momentum Base (40 pts)\n• Daily RSI Sweet Spot 55–64 (15 pts)\n• Price vs EMA20 Support (15 pts)\n• Breakout / Pullback Setup (15 pts)\n• Volume Confirmation (10 pts)\n• Risk/Reward Ratio (5 pts)"]

    L2B --> FinalScore["Final Score Calculation\nFinal Score = 0.60 × Momentum + 0.40 × Entry"]

    FinalScore --> RRGate{"Risk/Reward Gate\nR:R ≥ 1.5"}
    RRGate -- "Pass" --> Action{"Action Classification"}
    RRGate -- "Fail (R:R < 1.5)" --> Out

    Action --> Buy["🟢 BUY (Score ≥ 85)"]
    Action --> Watch["🟢 WATCH / PULLBACK (Score 75–84)"]
    Action --> Watchlist["🟡 WATCHLIST (Score 65–74)"]
    Action --> Avoid["🔴 AVOID (Score < 65)"]
```

### 2.2 Layer 1 — Hard Filters
- Monthly RSI(14) $\ge 60$, Weekly RSI(14) $\ge 60$, Daily RSI(14) $\ge 50$.
- Price > EMA20 > EMA50 > EMA200.
- ADX(14) $\ge 20$.
- Volume / 20-day avg volume $\ge 1.0$.
- 3-Month & 6-Month Returns $> 0$.
- Distance from 52-Week High $\le 10\%$.

### 2.3 Layer 2 — Composite Scoring
- **Momentum Score (100 pts)**: Monthly RSI (15), Weekly RSI (15), Daily RSI (10), Trend Structure (15), ADX (10), 3M Return (10), 6M Return (10), RS vs Nifty 500 (5), Volume Ratio (5), 52W Distance (5).
- **Entry Score (100 pts)**: Momentum Base (40 pts), Daily RSI setup (15), Price vs EMA20 (15), Breakout/Pullback (15), Volume confirmation (10), Risk/Reward (5).
- **Final Score**: `0.60 × Momentum Score + 0.40 × Entry Score`.
- **R:R Gate**: Setups with R:R $< 1.5$ excluded.

---

## 3. UI & Presentation Specifications
- **Dual-Theme Engine**: Default Light Mode (`#f8fafc`) & Dark Terminal (`#050b14`).
- **3-Mode Switcher**: Radio selector (`🚀 Swing Momentum`, `⚡ Intraday MTF`, `📊 Performance Monitor`).
- **Exporting**: One-click dated CSV download.
- **TV Links**: Direct deep links to TradingView.
