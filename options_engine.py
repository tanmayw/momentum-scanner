"""
Options Chain Strategy Engine for Indian NSE Equities & Indices
Multi-Timeframe Gated Option Strategy Selection, Pricing, and Risk Management
"""

import math
import numpy as np
import pandas as pd
import yfinance as yf
import requests
from urllib.parse import quote
from datetime import datetime, timedelta

REQUIRED_COLUMNS = {"expiry", "strike", "option_type", "ltp", "bid", "ask", "volume", "oi", "change_oi", "iv"}

# Standard NSE F&O Lot Sizes (Instruments Master fallback)
LOT_SIZES = {
    "NIFTY": 75,
    "BANKNIFTY": 30,
    "FINNIFTY": 65,
    "MIDCPNIFTY": 75,
    "RELIANCE": 250,
    "HDFCBANK": 550,
    "ICICIBANK": 700,
    "SBIN": 750,
    "AXISBANK": 625,
    "KOTAKBANK": 400,
    "INFY": 400,
    "TCS": 175,
    "BHARTIARTL": 475,
    "LT": 175,
    "ITC": 1600,
    "TATAMOTORS": 575,
    "M&M": 350,
    "TRENT": 100,
    "HAL": 150,
    "BEL": 1425,
    "DIXON": 50,
    "POLYCAB": 100,
    "PERSISTENT": 100,
    "COFORGE": 75,
    "MCX": 125,
    "ZOMATO": 2000,
    "BAJFINANCE": 125,
    "MARUTI": 50,
    "SUNPHARMA": 350,
    "TATAPOWER": 1350
}


def get_lot_size(symbol: str) -> int:
    """Get the standard F&O lot size for a symbol, defaulting to 250 if not specified."""
    sym_clean = symbol.strip().upper().replace(".NS", "").replace("^", "")
    return LOT_SIZES.get(sym_clean, 250)


def validate_chain(chain: pd.DataFrame) -> tuple[bool, str]:
    """Validate that the option chain has all mandatory columns and valid contracts."""
    if chain is None or chain.empty:
        return False, "Option chain is empty or unavailable."
    missing = REQUIRED_COLUMNS - set(chain.columns)
    if missing:
        return False, f"Missing required columns: {sorted(missing)}"
    x = chain.copy()
    x["option_type"] = x["option_type"].astype(str).str.upper()
    if x[x.option_type.isin(["CE", "PE"])].empty:
        return False, "No CE/PE contracts available in chain."
    return True, "OK"


def analyze_option_chain(
    chain: pd.DataFrame,
    spot: float,
    underlying_direction: str = "BULLISH",
    atm_tolerance: float = 0.01
) -> dict:
    """
    Mandatory Gate: Analyze the option chain before any strategy recommendation.
    Computes PCR, ATM IV, ATM Spread %, Net OI bias, and Chain Score (0-100).
    """
    ok, msg = validate_chain(chain)
    if not ok:
        return {"valid": False, "chain_score": 0, "verdict": "NO TRADE", "reason": msg}

    x = chain.copy()
    x["option_type"] = x.option_type.astype(str).str.upper()
    x["expiry"] = pd.to_datetime(x["expiry"])
    x = x.sort_values("expiry")

    expiry = x.expiry.iloc[0]
    x = x[x.expiry == expiry].copy()

    strikes = sorted(x.strike.dropna().unique())
    if not strikes:
        return {"valid": False, "chain_score": 0, "verdict": "NO TRADE", "reason": "No valid strikes found."}

    atm = float(min(strikes, key=lambda s: abs(s - spot)))

    ce = x[x.option_type == "CE"]
    pe = x[x.option_type == "PE"]

    co = float(ce.oi.sum()) if "oi" in ce.columns else 0.0
    po = float(pe.oi.sum()) if "oi" in pe.columns else 0.0

    cc = float(ce.change_oi.sum()) if "change_oi" in ce.columns else 0.0
    pc = float(pe.change_oi.sum()) if "change_oi" in pe.columns else 0.0

    cv = float(ce.volume.sum()) if "volume" in ce.columns else 0.0
    pv = float(pe.volume.sum()) if "volume" in pe.columns else 0.0

    pcr = (po / co) if co > 0 else np.nan

    # ATM Zone Contracts
    near = x[(x.strike >= atm * (1.0 - atm_tolerance)) & (x.strike <= atm * (1.0 + atm_tolerance))]
    sp = ((near.ask - near.bid) / near.ltp.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).dropna()
    avg_sp = float(sp.mean()) if not sp.empty else np.nan

    zone = x.iloc[(x.strike - atm).abs().argsort()[:min(6, len(x))]]
    avg_iv = float(zone.iv.mean()) if not zone.empty and "iv" in zone.columns else np.nan

    score = 0.0
    reasons = []
    d = str(underlying_direction).upper()

    # 1. Total OI Structure (Max 20 pts)
    if d == "BULLISH":
        if po > co and pc > 0:
            score += 20.0
            reasons.append("Put OI & Put writing confirm strong bullish support.")
        elif po > co:
            score += 12.0
            reasons.append("Put OI exceeds Call OI.")
        elif cc < 0:
            score += 8.0
            reasons.append("Call OI unwinding detected.")
    elif d == "BEARISH":
        if co > po and cc > 0:
            score += 20.0
            reasons.append("Call OI & Call writing confirm strong bearish resistance.")
        elif co > po:
            score += 12.0
            reasons.append("Call OI exceeds Put OI.")
        elif pc < 0:
            score += 8.0
            reasons.append("Put OI unwinding detected.")
    else:
        score += 8.0
        reasons.append("Neutral: Option chain evaluated for volatility & strike selection.")

    # 2. Change in OI Confirmation (Max 15 pts)
    if d == "BULLISH" and pc > cc:
        score += 15.0
        reasons.append("Change in OI favors bullish positioning (Put addition > Call addition).")
    elif d == "BEARISH" and cc > pc:
        score += 15.0
        reasons.append("Change in OI favors bearish positioning (Call addition > Put addition).")
    elif abs(pc - cc) > 0:
        score += 7.0

    # 3. Option Volume (Max 10 pts)
    total_vol = cv + pv
    if total_vol > 0:
        score += 10.0
        reasons.append("Active options volume is present.")

    # 4. Implied Volatility (IV) Level (Max 15 pts)
    if pd.notna(avg_iv):
        if avg_iv < 20.0:
            score += 15.0
            reasons.append("ATM IV is attractive / moderate (< 20%).")
        elif avg_iv < 30.0:
            score += 10.0
            reasons.append("ATM IV is moderately elevated (20-30%).")
        elif avg_iv < 40.0:
            score += 5.0
            reasons.append("ATM IV is high; debit spreads favored.")
        else:
            reasons.append("ATM IV is very high; long premium risk.")

    # 5. Bid/Ask Spread Liquidity (Max 15 pts)
    if pd.notna(avg_sp):
        if avg_sp <= 0.02:
            score += 15.0
            reasons.append("ATM bid/ask liquidity is tight (<= 2%).")
        elif avg_sp <= 0.05:
            score += 10.0
            reasons.append("ATM bid/ask liquidity is acceptable (<= 5%).")
        elif avg_sp <= 0.10:
            score += 5.0
            reasons.append("ATM bid/ask spread is wide (<= 10%).")
        else:
            reasons.append("ATM bid/ask spread exceeds 10% threshold.")

    # 6. Put-Call Ratio (PCR) (Max 10 pts)
    if pd.notna(pcr):
        if d == "BULLISH" and 1.0 <= pcr <= 1.5:
            score += 10.0
            reasons.append(f"PCR ({pcr:.2f}) supports bullish continuation.")
        elif d == "BULLISH" and 0.8 <= pcr < 1.0:
            score += 5.0
        elif d == "BEARISH" and 0.6 <= pcr <= 1.0:
            score += 10.0
            reasons.append(f"PCR ({pcr:.2f}) supports bearish continuation.")
        elif d == "BEARISH" and 1.0 < pcr <= 1.3:
            score += 5.0
        elif d == "NEUTRAL" and 0.8 <= pcr <= 1.3:
            score += 10.0
            reasons.append(f"PCR ({pcr:.2f}) is balanced for neutral setups.")

    # 7. ATM Liquidity & Strike Depth (Max 15 pts)
    liquid = near[(near.volume > 0) & (near.oi > 0)]
    if len(liquid) >= 2:
        score += 10.0
        reasons.append("ATM strikes have verified volume and open interest.")
    elif len(liquid) == 1:
        score += 5.0

    if len(strikes) >= 5:
        score += 5.0
        reasons.append("Sufficient strike depth available.")

    score = min(float(score), 100.0)
    liquidity_ok = total_vol > 0 and len(liquid) >= 1 and (pd.isna(avg_sp) or avg_sp <= 0.10)

    if score >= 75.0 and liquidity_ok:
        verdict = "CHAIN SUPPORTS TRADE"
    elif score >= 60.0 and liquidity_ok:
        verdict = "CHAIN PARTIALLY SUPPORTS TRADE"
    else:
        verdict = "NO TRADE"

    return {
        "valid": True,
        "expiry": expiry.strftime("%Y-%m-%d") if hasattr(expiry, "strftime") else str(expiry),
        "atm": atm,
        "pcr": round(pcr, 2) if pd.notna(pcr) else np.nan,
        "call_oi": co,
        "put_oi": po,
        "call_change_oi": cc,
        "put_change_oi": pc,
        "call_volume": cv,
        "put_volume": pv,
        "avg_atm_iv": round(avg_iv, 1) if pd.notna(avg_iv) else np.nan,
        "avg_atm_spread_pct": round(avg_sp * 100, 2) if pd.notna(avg_sp) else np.nan,
        "chain_score": round(score, 1),
        "liquidity_ok": liquidity_ok,
        "verdict": verdict,
        "reasons": reasons,
        "filtered_chain": x
    }


def _get_contract(chain: pd.DataFrame, strike: float, option_type: str) -> pd.Series | None:
    """Retrieve contract row for specified strike and CE/PE."""
    q = chain[(chain.strike == strike) & (chain.option_type.str.upper() == option_type)]
    if q.empty:
        return None
    return q.sort_values(["volume", "oi"], ascending=False).iloc[0]


def select_strikes(
    chain: pd.DataFrame,
    spot: float,
    strategy: str,
    max_distance_pct: float = 0.03
) -> dict | None:
    """
    Select optimal option legs based on strategy and ATM distance.
    """
    x = chain.copy()
    x["option_type"] = x.option_type.astype(str).str.upper()
    strikes = sorted(x.strike.dropna().unique())
    if not strikes:
        return None

    atm = min(strikes, key=lambda s: abs(s - spot))

    if strategy == "BULL_CALL_SPREAD":
        otm_strikes = [s for s in strikes if s > atm and s <= spot * (1.0 + max_distance_pct)]
        if not otm_strikes:
            otm_strikes = [s for s in strikes if s > atm]
        if not otm_strikes:
            return None
        sell_strike = min(otm_strikes)
        buy_c = _get_contract(x, atm, "CE")
        sell_c = _get_contract(x, sell_strike, "CE")
        if buy_c is None or sell_c is None:
            return None
        return {"buy": buy_c, "sell": sell_c}

    if strategy == "BEAR_PUT_SPREAD":
        otm_strikes = [s for s in strikes if s < atm and s >= spot * (1.0 - max_distance_pct)]
        if not otm_strikes:
            otm_strikes = [s for s in strikes if s < atm]
        if not otm_strikes:
            return None
        sell_strike = max(otm_strikes)
        buy_p = _get_contract(x, atm, "PE")
        sell_p = _get_contract(x, sell_strike, "PE")
        if buy_p is None or sell_p is None:
            return None
        return {"buy": buy_p, "sell": sell_p}

    if strategy == "LONG_CALL":
        buy_c = _get_contract(x, atm, "CE")
        return {"buy": buy_c} if buy_c is not None else None

    if strategy == "LONG_PUT":
        buy_p = _get_contract(x, atm, "PE")
        return {"buy": buy_p} if buy_p is not None else None

    if strategy == "LONG_STRANGLE":
        cs = [s for s in strikes if s > atm]
        ps = [s for s in strikes if s < atm]
        if not cs or not ps:
            return None
        call_strike = min(cs, key=lambda s: abs(s - spot * 1.015))
        put_strike = min(ps, key=lambda s: abs(s - spot * 0.985))
        c_leg = _get_contract(x, call_strike, "CE")
        p_leg = _get_contract(x, put_strike, "PE")
        if c_leg is None or p_leg is None:
            return None
        return {"call": c_leg, "put": p_leg}

    return None


def price_strategy(legs: dict, strategy: str, lot_size: int = 1) -> dict | None:
    """
    Calculate net premium, max loss, max profit, breakeven points, and Risk/Reward.
    """
    if not legs:
        return None

    if strategy in ("BULL_CALL_SPREAD", "BEAR_PUT_SPREAD"):
        b_ltp = float(legs["buy"].ltp)
        s_ltp = float(legs["sell"].ltp)
        net_premium = max(b_ltp - s_ltp, 0.01)
        width = abs(float(legs["buy"].strike) - float(legs["sell"].strike))
        max_loss = net_premium * lot_size
        max_profit = max(width - net_premium, 0.0) * lot_size
        breakeven = float(legs["buy"].strike) + (net_premium if strategy == "BULL_CALL_SPREAD" else -net_premium)
        rr = (max_profit / max_loss) if max_loss > 0 else np.nan

        return {
            "strategy": strategy,
            "net_premium": round(net_premium, 2),
            "max_loss": round(max_loss, 2),
            "max_profit": round(max_profit, 2),
            "breakeven": round(breakeven, 2),
            "risk_reward": round(rr, 2) if pd.notna(rr) else np.nan,
            "lot_size": lot_size
        }

    if strategy in ("LONG_CALL", "LONG_PUT"):
        p = float(legs["buy"].ltp)
        k = float(legs["buy"].strike)
        max_loss = p * lot_size
        breakeven = k + p if strategy == "LONG_CALL" else k - p

        return {
            "strategy": strategy,
            "net_premium": round(p, 2),
            "max_loss": round(max_loss, 2),
            "max_profit": float("inf"),
            "breakeven": round(breakeven, 2),
            "risk_reward": np.nan,
            "lot_size": lot_size
        }

    if strategy == "LONG_STRANGLE":
        c_ltp = float(legs["call"].ltp)
        p_ltp = float(legs["put"].ltp)
        total_prem = c_ltp + p_ltp
        max_loss = total_prem * lot_size
        upper_be = float(legs["call"].strike) + total_prem
        lower_be = float(legs["put"].strike) - total_prem

        return {
            "strategy": strategy,
            "net_premium": round(total_prem, 2),
            "max_loss": round(max_loss, 2),
            "max_profit": float("inf"),
            "breakeven": round(upper_be, 2),
            "lower_breakeven": round(lower_be, 2),
            "upper_breakeven": round(upper_be, 2),
            "risk_reward": np.nan,
            "lot_size": lot_size
        }

    return None


def recommend_strategy(
    mtf_score: float,
    direction: str,
    chain_analysis: dict,
    capital: float = 100000.0,
    max_risk_pct: float = 0.5,
    prefer_spreads: bool = True
) -> dict:
    """
    Evaluate MTF Score + Option Chain Gate + Risk Budget to recommend an option strategy.
    """
    if not chain_analysis or not chain_analysis.get("valid"):
        return {"recommendation": "NO TRADE", "reason": "Option chain unavailable or invalid."}

    if chain_analysis.get("verdict") != "CHAIN SUPPORTS TRADE":
        return {
            "recommendation": "NO TRADE",
            "reason": f"Option-chain gate not passed ({chain_analysis.get('verdict')}).",
            "chain_score": chain_analysis.get("chain_score", 0)
        }

    if mtf_score < 75.0:
        return {
            "recommendation": "NO TRADE",
            "reason": f"MTF momentum score below minimum required threshold (Score: {mtf_score:.0f} < 75).",
            "chain_score": chain_analysis.get("chain_score", 0)
        }

    d = str(direction).upper()
    if d == "BULLISH":
        st = "BULL_CALL_SPREAD" if prefer_spreads else "LONG_CALL"
    elif d == "BEARISH":
        st = "BEAR_PUT_SPREAD" if prefer_spreads else "LONG_PUT"
    elif d == "NEUTRAL":
        st = "LONG_STRANGLE"
    else:
        return {"recommendation": "NO TRADE", "reason": "Undefined market direction."}

    max_allowed_loss = capital * (max_risk_pct / 100.0)

    return {
        "recommendation": st,
        "chain_score": chain_analysis["chain_score"],
        "mtf_score": mtf_score,
        "direction": d,
        "max_allowed_loss": max_allowed_loss
    }


def run_options_layer(
    option_chain: pd.DataFrame,
    spot: float,
    mtf_score: float,
    direction: str,
    capital: float = 100000.0,
    lot_size: int = 250,
    max_risk_pct: float = 2.0,
    prefer_spreads: bool = True,
    enforce_risk_budget: bool = True
) -> dict:
    """
    Complete end-to-end execution of the options analysis layer.
    """
    chain = analyze_option_chain(option_chain, spot, direction)
    rec = recommend_strategy(mtf_score, direction, chain, capital, max_risk_pct, prefer_spreads)

    if rec["recommendation"] == "NO TRADE":
        return {
            "chain_analysis": chain,
            "recommendation": rec,
            "strategy": "NO TRADE",
            "risk_gate_passed": False,
            "legs": None,
            "payoff": None
        }

    strategy = rec["recommendation"]
    legs = select_strikes(option_chain, spot, strategy)

    if legs is None:
        return {
            "chain_analysis": chain,
            "recommendation": {
                "recommendation": "NO TRADE",
                "strategy_name": strategy,
                "reason": "Suitable liquid strikes not found in the chain."
            },
            "strategy": "NO TRADE",
            "risk_gate_passed": False,
            "legs": None,
            "payoff": None
        }

    payoff = price_strategy(legs, strategy, lot_size)
    risk_passed = True

    if payoff and payoff["max_loss"] > rec["max_allowed_loss"]:
        risk_passed = False
        if enforce_risk_budget:
            rec = {
                "recommendation": "NO TRADE",
                "strategy_name": strategy,
                "reason": f"Maximum loss (₹{payoff['max_loss']:,.2f}) exceeds risk budget (₹{rec['max_allowed_loss']:,.2f}). Increase capital or risk %.",
                "max_loss": payoff["max_loss"],
                "max_allowed_loss": rec["max_allowed_loss"],
                "risk_gate_passed": False
            }
        else:
            rec["risk_gate_passed"] = False
            rec["risk_warning"] = f"Maximum loss (₹{payoff['max_loss']:,.2f}) exceeds risk budget (₹{rec['max_allowed_loss']:,.2f})."
    else:
        rec["risk_gate_passed"] = True

    return {
        "chain_analysis": chain,
        "recommendation": rec,
        "strategy": strategy,
        "risk_gate_passed": risk_passed,
        "legs": legs,
        "payoff": payoff
    }


# ─────────────────────────────────────────────
#  Payoff Curve Generator for Plotting
# ─────────────────────────────────────────────

def generate_payoff_curve(
    strategy: str,
    legs: dict,
    spot: float,
    lot_size: int = 1,
    range_pct: float = 0.08,
    steps: int = 100
) -> pd.DataFrame:
    """
    Generate P&L curve across underlying price range at expiry.
    """
    if not legs:
        return pd.DataFrame()

    low_price = spot * (1.0 - range_pct)
    high_price = spot * (1.0 + range_pct)
    prices = np.linspace(low_price, high_price, steps)
    pnl = []

    if strategy == "BULL_CALL_SPREAD":
        k1 = float(legs["buy"].strike)
        k2 = float(legs["sell"].strike)
        p1 = float(legs["buy"].ltp)
        p2 = float(legs["sell"].ltp)
        net_cost = (p1 - p2) * lot_size
        for s in prices:
            val = (max(s - k1, 0) - max(s - k2, 0)) * lot_size - net_cost
            pnl.append(val)

    elif strategy == "BEAR_PUT_SPREAD":
        k1 = float(legs["buy"].strike)
        k2 = float(legs["sell"].strike)
        p1 = float(legs["buy"].ltp)
        p2 = float(legs["sell"].ltp)
        net_cost = (p1 - p2) * lot_size
        for s in prices:
            val = (max(k1 - s, 0) - max(k2 - s, 0)) * lot_size - net_cost
            pnl.append(val)

    elif strategy == "LONG_CALL":
        k = float(legs["buy"].strike)
        p = float(legs["buy"].ltp)
        cost = p * lot_size
        for s in prices:
            val = max(s - k, 0) * lot_size - cost
            pnl.append(val)

    elif strategy == "LONG_PUT":
        k = float(legs["buy"].strike)
        p = float(legs["buy"].ltp)
        cost = p * lot_size
        for s in prices:
            val = max(k - s, 0) * lot_size - cost
            pnl.append(val)

    elif strategy == "LONG_STRANGLE":
        kc = float(legs["call"].strike)
        kp = float(legs["put"].strike)
        pc = float(legs["call"].ltp)
        pp = float(legs["put"].ltp)
        cost = (pc + pp) * lot_size
        for s in prices:
            val = (max(s - kc, 0) + max(kp - s, 0)) * lot_size - cost
            pnl.append(val)

    return pd.DataFrame({"Spot_at_Expiry": prices, "PnL": pnl})


# ─────────────────────────────────────────────
#  Option Chain Data Ingestion & Simulation Adapter
# ─────────────────────────────────────────────

def _black_scholes_approx(spot, strike, t_days, r=0.07, iv=0.20, option_type="CE"):
    """Black-Scholes analytical approximation for pricing and synthetic chain generation."""
    t = max(t_days / 365.0, 0.001)
    d1 = (math.log(spot / strike) + (r + 0.5 * iv ** 2) * t) / (iv * math.sqrt(t))
    d2 = d1 - iv * math.sqrt(t)

    # Standard normal cumulative distribution approximation
    def cdf(z):
        return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))

    if option_type == "CE":
        price = spot * cdf(d1) - strike * math.exp(-r * t) * cdf(d2)
    else:
        price = strike * math.exp(-r * t) * cdf(-d2) - spot * cdf(-d1)
    return max(round(price, 2), 0.05)


def calculate_next_expiry(symbol: str) -> str:
    """
    Calculate the next valid option expiry date for NSE indices (weekly) and stocks (monthly).
    MIDCPNIFTY = Monday (0), FINNIFTY = Tuesday (1), BANKNIFTY = Wednesday (2), NIFTY/SENSEX = Thursday (3).
    Stocks expire on the last Thursday of the month.
    """
    clean_sym = symbol.strip().upper().replace(".NS", "").replace("^", "")
    now = datetime.now()
    
    expiry_weekday_map = {"MIDCPNIFTY": 0, "FINNIFTY": 1, "BANKNIFTY": 2, "NIFTY": 3, "SENSEX": 3}
    
    if clean_sym in expiry_weekday_map:
        # Index option (weekly expiry)
        target_w = expiry_weekday_map[clean_sym]
        days_to_target = (target_w - now.weekday()) % 7
        if days_to_target == 0:
            # If today is expiry day and past 15:30 (market close), use next week's expiry
            if now.hour > 15 or (now.hour == 15 and now.minute >= 30):
                days_to_target = 7
        candidate = now + timedelta(days=days_to_target)
        return candidate.strftime("%Y-%m-%d")
    else:
        # Stock option (monthly expiry - last Thursday of the month)
        def last_thursday_of_month(year, month):
            if month == 12:
                last_day = datetime(year + 1, 1, 1) - timedelta(days=1)
            else:
                last_day = datetime(year, month + 1, 1) - timedelta(days=1)
            offset = (last_day.weekday() - 3) % 7
            return last_day - timedelta(days=offset)
            
        curr_month_thurs = last_thursday_of_month(now.year, now.month)
        
        has_passed = False
        if now.date() > curr_month_thurs.date():
            has_passed = True
        elif now.date() == curr_month_thurs.date():
            if now.hour > 15 or (now.hour == 15 and now.minute >= 30):
                has_passed = True
                
        if has_passed:
            if now.month == 12:
                candidate = last_thursday_of_month(now.year + 1, 1)
            else:
                candidate = last_thursday_of_month(now.year, now.month + 1)
        else:
            candidate = curr_month_thurs
            
        return candidate.strftime("%Y-%m-%d")


def generate_synthetic_option_chain(symbol: str, spot: float) -> pd.DataFrame:
    """
    Generate realistic, normalized option chain for NSE ticker.
    Ensures testing is always functional even outside exchange trading hours.
    """
    next_expiry = calculate_next_expiry(symbol)
    
    # Calculate actual days to expiry for pricing
    expiry_dt = datetime.strptime(next_expiry, "%Y-%m-%d")
    t_days = max((expiry_dt.date() - datetime.now().date()).days, 1)

    # Determine step size based on price
    step = 50 if spot > 2000 else (20 if spot > 800 else (10 if spot > 250 else 5))
    atm_base = round(spot / step) * step

    strikes = [atm_base + i * step for i in range(-10, 11)]
    rows = []

    np.random.seed(int(spot * 10) % 1000)

    for k in strikes:
        dist = abs(k - spot) / spot
        base_iv = 18.0 + dist * 30.0 + np.random.uniform(-1.0, 2.0)
        iv_dec = base_iv / 100.0

        # CE Contract
        ce_price = _black_scholes_approx(spot, k, t_days, iv=iv_dec, option_type="CE")
        ce_bid = round(ce_price * 0.985, 2)
        ce_ask = round(ce_price * 1.015, 2)
        ce_oi = int(max(100000 - abs(k - spot) * 80 + np.random.randint(-5000, 15000), 5000))
        ce_chg_oi = int(np.random.randint(-10000, 25000))
        ce_vol = int(ce_oi * np.random.uniform(0.1, 0.4))

        rows.append({
            "expiry": next_expiry,
            "strike": float(k),
            "option_type": "CE",
            "ltp": ce_price,
            "bid": ce_bid,
            "ask": ce_ask,
            "volume": ce_vol,
            "oi": ce_oi,
            "change_oi": ce_chg_oi,
            "iv": round(base_iv, 1)
        })

        # PE Contract
        pe_price = _black_scholes_approx(spot, k, t_days, iv=iv_dec, option_type="PE")
        pe_bid = round(pe_price * 0.985, 2)
        pe_ask = round(pe_price * 1.015, 2)
        pe_oi = int(max(100000 - abs(k - spot) * 80 + np.random.randint(-5000, 15000), 5000))
        pe_chg_oi = int(np.random.randint(-10000, 25000))
        pe_vol = int(pe_oi * np.random.uniform(0.1, 0.4))

        rows.append({
            "expiry": next_expiry,
            "strike": float(k),
            "option_type": "PE",
            "ltp": pe_price,
            "bid": pe_bid,
            "ask": pe_ask,
            "volume": pe_vol,
            "oi": pe_oi,
            "change_oi": pe_chg_oi,
            "iv": round(base_iv, 1)
        })

    return pd.DataFrame(rows)


def _normalize_expiry(date_str: str) -> str:
    """
    Normalize NSE expiry date strings (e.g., '28-Aug-2025' or '2025-08-28') to
    consistent ISO format 'YYYY-MM-DD' for reliable display and parsing.
    """
    if not date_str or not isinstance(date_str, str):
        return date_str
    # NSE API returns dates like '28-Aug-2025'
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str  # Return as-is if no format matched


def fetch_or_simulate_option_chain(symbol: str, spot: float) -> pd.DataFrame:
    """
    Fetch option chain from NSE India (https://www.nseindia.com/option-chain)
    or fall back to high-fidelity synthetic model.
    Expiry dates are normalized to ISO format 'YYYY-MM-DD'.
    """
    clean_sym = symbol.strip().upper().replace(".NS", "").replace("^", "")
    indices = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"}

    try:
        session = requests.Session()
        # Full browser headers to pass NSE's bot protection
        base_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "DNT": "1",
        }
        session.headers.update(base_headers)

        # Step 1: Hit NSE homepage to acquire session cookies
        session.get(
            "https://www.nseindia.com",
            headers={**base_headers, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
            timeout=12,
        )
        # Step 2: Visit option-chain page to get additional CSRF/session cookies
        session.get(
            "https://www.nseindia.com/option-chain",
            headers={**base_headers, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                     "Referer": "https://www.nseindia.com/"},
            timeout=12,
        )

        # Step 3: Fetch option chain API
        if clean_sym in indices:
            url = f"https://www.nseindia.com/api/option-chain-indices?symbol={clean_sym}"
        else:
            safe_sym = quote(clean_sym)
            url = f"https://www.nseindia.com/api/option-chain-equities?symbol={safe_sym}"

        api_headers = {
            **base_headers,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": "https://www.nseindia.com/option-chain",
            "X-Requested-With": "XMLHttpRequest",
        }
        resp = session.get(url, headers=api_headers, timeout=15)

        if resp.status_code == 200:
            data = resp.json()
            records = data.get("records", {})
            expiry_dates = records.get("expiryDates", [])

            if expiry_dates and records.get("data"):
                # Use the nearest (first) expiry
                nearest_exp_raw = expiry_dates[0]
                nearest_exp = _normalize_expiry(nearest_exp_raw)
                rows = []

                for item in records["data"]:
                    item_expiry_raw = item.get("expiryDate", "")
                    item_expiry = _normalize_expiry(item_expiry_raw)
                    if item_expiry != nearest_exp:
                        continue

                    strike = float(item["strikePrice"])

                    if "CE" in item:
                        ce = item["CE"]
                        rows.append({
                            "expiry": nearest_exp,
                            "strike": strike,
                            "option_type": "CE",
                            "ltp": float(ce.get("lastPrice", 0.0)),
                            "bid": float(ce.get("bidprice", 0.0)),
                            "ask": float(ce.get("askPrice", 0.0)),
                            "volume": int(ce.get("totalTradedVolume", 0)),
                            "oi": int(ce.get("openInterest", 0)),
                            "change_oi": int(ce.get("changeinOpenInterest", 0)),
                            "iv": float(ce.get("impliedVolatility", 0.0)),
                        })

                    if "PE" in item:
                        pe = item["PE"]
                        rows.append({
                            "expiry": nearest_exp,
                            "strike": strike,
                            "option_type": "PE",
                            "ltp": float(pe.get("lastPrice", 0.0)),
                            "bid": float(pe.get("bidprice", 0.0)),
                            "ask": float(pe.get("askPrice", 0.0)),
                            "volume": int(pe.get("totalTradedVolume", 0)),
                            "oi": int(pe.get("openInterest", 0)),
                            "change_oi": int(pe.get("changeinOpenInterest", 0)),
                            "iv": float(pe.get("impliedVolatility", 0.0)),
                        })

                df = pd.DataFrame(rows)
                ok, _ = validate_chain(df)
                if ok:
                    return df
    except Exception as e:
        print(f"NSE API fetch failed for {clean_sym}: {e}")

    # Fallback to realistic synthetic model
    return generate_synthetic_option_chain(symbol, spot)
