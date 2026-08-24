"""
Performance Monitoring and Signal Tracking Engine
Backfills historical recommendations and evaluates their subsequent performance metrics.
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import yfinance as yf

from intraday_scanner import download_ticker_data

# Cache file paths
SWING_HISTORY_PATH = Path("cache/swing_signals_history.json")
Path("cache").mkdir(exist_ok=True)

# ─────────────────────────────────────────────
# Technical Indicators (Independent Copy)
# ─────────────────────────────────────────────

def rsi(s: pd.Series, period: int = 14) -> pd.Series:
    d = s.diff()
    gain = d.clip(lower=0)
    loss = -d.clip(upper=0)
    ag = gain.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    al = loss.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    rs_val = ag / al.replace(0, np.nan)
    return 100 - (100 / (1 + rs_val))

def ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False, min_periods=period).mean()

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False, min_periods=period).mean()

def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up = df["High"].diff()
    down = -df["Low"].diff()
    
    pdm = np.where((up > down) & (up > 0), up, 0.0)
    ndm = np.where((down > up) & (down > 0), down, 0.0)
    
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift(1)).abs(),
        (df["Low"] - df["Close"].shift(1)).abs()
    ], axis=1).max(axis=1)
    
    atr_val = tr.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    pdi = 100 * pd.Series(pdm).ewm(alpha=1/period, adjust=False, min_periods=period).mean() / atr_val.replace(0, np.nan)
    ndi = 100 * pd.Series(ndm).ewm(alpha=1/period, adjust=False, min_periods=period).mean() / atr_val.replace(0, np.nan)
    
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    return dx.ewm(alpha=1/period, adjust=False, min_periods=period).mean()

# ─────────────────────────────────────────────
# Scoring Logic Helpers (Matching streamlit_app)
# ─────────────────────────────────────────────

def rsi_score(x, kind):
    if kind == "monthly":
        return 15 if x >= 60 else 10 if x >= 50 else 0
    elif kind == "weekly":
        return 15 if x >= 60 else 10 if x >= 50 else 0
    else:  # daily
        return 10 if x >= 60 else 7 if x >= 50 else 0

def calc_trend_score(price, e20, e50, e200):
    if price > e20 > e50 > e200:
        return 15
    elif price > e20 > e50:
        return 12
    elif price > e20:
        return 8
    return 0

def calc_rs_score(rs_decimal):
    if pd.isna(rs_decimal):
        return 0
    p = rs_decimal * 100.0
    return 5 if p >= 20 else 4 if p >= 10 else 3 if p >= 5 else 2 if p >= 0 else 0

def calc_price_vs_ema20_score(price, e20):
    pct = (price - e20) / e20 if e20 else 99
    return 15 if 0.01 <= pct <= 0.03 else 12 if 0.0 < pct < 0.01 else 8 if 0.03 < pct <= 0.06 else 3

def calc_breakout_pullback_score(price, e20, high52, vol_ratio):
    is_bo = (high52 - price) / high52 <= 0.02 and vol_ratio >= 1.5
    is_pb = 0.0 < (price - e20) / e20 <= 0.015 and vol_ratio >= 0.8
    return 15 if is_bo else 12 if is_pb else 5

def calc_rr_score(rr_ratio):
    return 5 if rr_ratio >= 2.5 else 4 if rr_ratio >= 2.0 else 3 if rr_ratio >= 1.5 else 0

# ─────────────────────────────────────────────
# Swing Performance Calculations
# ─────────────────────────────────────────────

def calculate_metrics_for_date(symbol, d, benchmark, date_t):
    """Calculate swing metrics as of a specific date in the past."""
    d_slice = d.loc[:date_t]
    if len(d_slice) < 260:
        return None
    
    # Resample weekly/monthly using the sliced data
    w = d_slice.resample("W-FRI").agg({"Close": "last"}).dropna()
    m = d_slice.resample("ME").agg({"Close": "last"}).dropna()
    if len(w) < 30 or len(m) < 18:
        return None
        
    close = d_slice["Close"]
    current = float(close.iloc[-1])
    m_rsi = float(rsi(m["Close"]).iloc[-1])
    w_rsi = float(rsi(w["Close"]).iloc[-1])
    d_rsi = float(rsi(close).iloc[-1])
    
    e20 = float(ema(close, 20).iloc[-1])
    e50 = float(ema(close, 50).iloc[-1])
    e200 = float(ema(close, 200).iloc[-1])
    adxv = float(adx(d_slice).iloc[-1])
    atrv = float(atr(d_slice).iloc[-1])
    
    vol20 = float(d_slice["Volume"].rolling(20).mean().iloc[-1])
    vol_ratio = float(d_slice["Volume"].iloc[-1] / vol20) if vol20 else np.nan
    high52 = float(close.tail(252).max())
    dist52 = (high52 - current) / high52
    
    ret3 = float(close.iloc[-1] / close.iloc[-64] - 1) if len(close) >= 64 else np.nan
    ret6 = float(close.iloc[-1] / close.iloc[-126] - 1) if len(close) >= 126 else np.nan
    
    b_slice = benchmark.loc[:date_t]
    rs6 = np.nan
    if len(b_slice) >= 126 and not pd.isna(ret6):
        br = float(b_slice.iloc[-1] / b_slice.iloc[-126] - 1)
        rs6 = ret6 - br
        
    hard = (
        m_rsi >= 60 and w_rsi >= 60 and d_rsi >= 50 and
        current > e20 > e50 > e200 and
        adxv >= 20 and vol_ratio >= 1.0 and
        ret3 > 0 and ret6 > 0 and dist52 <= 0.10
    )
    
    return {
        "Symbol": symbol,
        "Price": current,
        "Monthly RSI": m_rsi,
        "Weekly RSI": w_rsi,
        "Daily RSI": d_rsi,
        "EMA20": e20,
        "EMA50": e50,
        "EMA200": e200,
        "ADX": adxv,
        "ATR": atrv,
        "Vol Ratio": vol_ratio,
        "3M Return": ret3,
        "6M Return": ret6,
        "RS vs Nifty": rs6,
        "52W High": high52,
        "52W Distance": dist52,
        "Hard Filter": hard
    }

def score_candidates_for_date(df):
    """Replicates scoring candidates for historical dataframe."""
    out = df.copy()
    if out.empty:
        return out
        
    out["M RSI Score"] = out["Monthly RSI"].apply(lambda x: rsi_score(x, "monthly"))
    out["W RSI Score"] = out["Weekly RSI"].apply(lambda x: rsi_score(x, "weekly"))
    out["D RSI Score"] = out["Daily RSI"].apply(lambda x: rsi_score(x, "daily"))
    out["Trend Score"] = out.apply(lambda r: calc_trend_score(r["Price"], r["EMA20"], r["EMA50"], r["EMA200"]), axis=1)
    out["ADX Score"] = out["ADX"].apply(lambda x: 0 if x < 20 else 5 if x < 25 else 7 if x < 30 else 10 if x < 40 else 8 if x < 50 else 6)
    
    ret3_rank = out["3M Return"].rank(pct=True)
    out["3M Score"] = ret3_rank.apply(lambda p: 10 if p >= 0.90 else 8 if p >= 0.75 else 6 if p >= 0.50 else 4 if p >= 0.25 else 0)
    
    ret6_rank = out["6M Return"].rank(pct=True)
    out["6M Score"] = ret6_rank.apply(lambda p: 10 if p >= 0.90 else 8 if p >= 0.75 else 6 if p >= 0.50 else 4 if p >= 0.25 else 0)
    
    out["RS Score"] = out["RS vs Nifty"].apply(calc_rs_score)
    out["Volume Score"] = out["Vol Ratio"].apply(lambda x: 0 if x < 1 else 2 if x < 1.2 else 3 if x < 1.5 else 4 if x < 2 else 5)
    out["52W Score"] = out["52W Distance"].apply(lambda x: 5 if x <= 0.05 else 4 if x <= 0.10 else 2 if x <= 0.15 else 0)
    
    score_cols = ["M RSI Score", "W RSI Score", "D RSI Score", "Trend Score", "ADX Score", "3M Score", "6M Score", "RS Score", "Volume Score", "52W Score"]
    out["Momentum Score"] = out[score_cols].sum(axis=1).round(1)
    
    out["Stop Loss"] = (out["Price"] - 1.5 * out["ATR"]).round(2)
    out["Target 2%"] = (out["Price"] * 1.02).round(2)
    out["Target 5%"] = (out["Price"] * 1.05).round(2)
    out["Risk Amt"] = (out["Price"] - out["Stop Loss"]).clip(lower=0.01)
    out["RR Ratio"] = ((out["Target 5%"] - out["Price"]) / out["Risk Amt"]).replace([np.inf, -np.inf], np.nan).round(2)
    
    # Filter by R:R Gate
    out = out[out["RR Ratio"] >= 1.5].copy()
    if out.empty:
        return out
        
    out["Entry RSI Score"] = out["Daily RSI"].apply(lambda x: 15 if 55 <= x < 65 else 12 if 50 <= x < 55 else 8 if 65 <= x < 70 else 3)
    out["Entry EMA20 Score"] = out.apply(lambda r: calc_price_vs_ema20_score(r["Price"], r["EMA20"]), axis=1)
    out["Entry BP Score"] = out.apply(lambda r: calc_breakout_pullback_score(r["Price"], r["EMA20"], r["52W High"], r["Vol Ratio"]), axis=1)
    out["Entry Vol Score"] = out["Vol Ratio"].apply(lambda x: 10 if x >= 1.5 else 7 if x >= 1.2 else 4)
    out["Entry RR Score"] = out["RR Ratio"].apply(calc_rr_score)
    
    out["Entry Score"] = (
        out["Momentum Score"] * 0.40
        + out["Entry RSI Score"]
        + out["Entry EMA20 Score"]
        + out["Entry BP Score"]
        + out["Entry Vol Score"]
        + out["Entry RR Score"]
    ).clip(upper=100).round(1)
    
    out["Final Score"] = (0.60 * out["Momentum Score"] + 0.40 * out["Entry Score"]).round(1)
    out["Action"] = np.select(
        [out["Final Score"] >= 85, out["Final Score"] >= 75, out["Final Score"] >= 65],
        ["BUY", "WATCH / PULLBACK", "WATCHLIST"],
        default="AVOID"
    )
    return out

def backfill_swing_signals(data_map, benchmark, days=7, force=False):
    """Backfills and caches swing recommendations generated in the last N trading days."""
    # Find last N trading days in benchmark
    bench_dates = benchmark.index.sort_values()
    last_dates = [d.strftime("%Y-%m-%d") for d in bench_dates[-days:]]
    
    # Load existing history
    history = []
    if SWING_HISTORY_PATH.exists() and not force:
        try:
            with open(SWING_HISTORY_PATH, "r") as f:
                history = json.load(f)
        except Exception:
            history = []
            
    existing_dates = {s["signal_date"] for s in history}
    
    # Compute signals for missing dates
    new_signals = []
    for dt_str in last_dates:
        if dt_str in existing_dates:
            continue
            
        # Run scan for this historical date
        rows = []
        for symbol, d in data_map.items():
            try:
                res = calculate_metrics_for_date(symbol, d, benchmark, dt_str)
                if res and res["Hard Filter"]:
                    rows.append(res)
            except Exception:
                continue
                
        if rows:
            df = pd.DataFrame(rows)
            scored = score_candidates_for_date(df)
            qualified = scored[scored["Action"].isin(["BUY", "WATCH / PULLBACK"])]
            
            for _, row in qualified.iterrows():
                new_signals.append({
                    "symbol": str(row["Symbol"]),
                    "signal_date": dt_str,
                    "entry_price": float(row["Price"]),
                    "stop_loss": float(row["Stop Loss"]),
                    "target_2": float(row["Target 2%"]),
                    "target_5": float(row["Target 5%"]),
                    "score": float(row["Final Score"]),
                    "action": str(row["Action"])
                })
                
    if new_signals:
        history.extend(new_signals)
        # Keep history sorted by date
        history.sort(key=lambda s: s["signal_date"], reverse=True)
        with open(SWING_HISTORY_PATH, "w") as f:
            json.dump(history, f, indent=2)
            
    # Filter history to return only signals within the requested window
    filtered_history = [s for s in history if s["signal_date"] in last_dates]
    return filtered_history

def evaluate_swing_performance(signals, data_map):
    """Evaluates the subsequent performance of generated swing signals."""
    rows = []
    for sig in signals:
        sym = sig["symbol"]
        sig_date = pd.to_datetime(sig["signal_date"])
        entry = sig["entry_price"]
        sl = sig["stop_loss"]
        t2 = sig["target_2"]
        t5 = sig["target_5"]
        
        if sym not in data_map:
            continue
            
        d = data_map[sym]
        post_sig = d.loc[d.index > sig_date]
        
        if post_sig.empty:
            # No data after signal date, check if today is signal date
            current_close = entry
            max_high = entry
            outcome = "Active"
        else:
            # Check price action day by day to see what is hit first
            outcome = "Active"
            current_close = float(post_sig["Close"].iloc[-1])
            max_high = float(post_sig["High"].max())
            
            for idx, bar in post_sig.iterrows():
                high = float(bar["High"])
                low = float(bar["Low"])
                
                # Check hits
                hit_sl = low <= sl
                hit_t5 = high >= t5
                hit_t2 = high >= t2
                
                if hit_sl and (hit_t5 or hit_t2):
                    # Conservatively assume stop loss hit first
                    outcome = "Stopped Out"
                    break
                elif hit_sl:
                    outcome = "Stopped Out"
                    break
                elif hit_t5:
                    outcome = "Hit Target 5%"
                    break
                elif hit_t2:
                    # Upgrade to Hit Target 2% if not hit 5% yet
                    outcome = "Hit Target 2%"
                    # Don't break, keep looking if it eventually hits Target 5% before Stop Loss
            
        curr_return = ((current_close - entry) / entry) * 100.0
        max_return = ((max_high - entry) / entry) * 100.0
        
        rows.append({
            "Symbol": sym,
            "Signal Date": sig["signal_date"],
            "Entry Price": entry,
            "Stop Loss": sl,
            "Target 2%": t2,
            "Target 5%": t5,
            "Score": sig["score"],
            "Action": sig["action"],
            "Current Price": current_close,
            "Current Return %": round(curr_return, 2),
            "Max Return %": round(max_return, 2),
            "Outcome": outcome
        })
        
    return pd.DataFrame(rows)

# ─────────────────────────────────────────────
# Intraday & Options Performance Calculations
# ─────────────────────────────────────────────

def backfill_and_evaluate_intraday(universe, days=5):
    """
    Simulates Intraday MTF signals over the last N days using 15m historical data.
    Evaluates whether each trigger hit its Target 1 (+1%), Target 2 (+2%), or ATR Stop Loss first.
    """
    rows = []
    
    for symbol in universe:
        try:
            # Index formatting mapping
            _INDEX_YF_MAP = {
                "NIFTY": "^NSEI",
                "BANKNIFTY": "^NSEBANK",
                "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
                "MIDCPNIFTY": "^CNXMIDCAP",
                "SENSEX": "^BSESN",
            }
            yf_sym = _INDEX_YF_MAP.get(symbol, symbol)
            
            # Download daily, hourly and 15m data
            d_df = download_ticker_data(yf_sym, "2y", "1d")
            h_df = download_ticker_data(yf_sym, "60d", "1h")
            m_df = download_ticker_data(yf_sym, "30d", "15m")
            
            if min(len(d_df), len(h_df), len(m_df)) < 50:
                continue
                
            # Filter 15m to last N days
            cutoff_date = datetime.now() - timedelta(days=days + 3) # Buffer for weekends
            m_df_window = m_df[m_df.index >= cutoff_date]
            unique_days = sorted(pd.Series(m_df_window.index.date).unique())[-days:]
            
            for target_date in unique_days:
                # Get the 15m bars for that day
                day_bars = m_df[m_df.index.date == target_date]
                if day_bars.empty:
                    continue
                    
                # To calculate indicators at any bar on target_date, slice the dataframe up to that bar.
                # To speed up, we look at each bar in target_date
                for bar_idx in range(len(day_bars)):
                    bar_time = day_bars.index[bar_idx]
                    
                    # Core MTF indicator slice
                    d_slice = d_df[d_df.index.date < target_date]
                    h_slice = h_df[h_df.index < bar_time]
                    m_slice = m_df[m_df.index <= bar_time]
                    
                    if len(d_slice) < 20 or len(h_slice) < 20 or len(m_slice) < 20:
                        continue
                        
                    # Calculate indicators as of this bar_time
                    dr = float(rsi(d_df["Close"].loc[:target_date]).iloc[-1]) if not d_df["Close"].loc[:target_date].empty else 50
                    hr = float(rsi(h_df["Close"].loc[:bar_time]).iloc[-1]) if not h_df["Close"].loc[:bar_time].empty else 50
                    mr = float(rsi(m_df["Close"].loc[:bar_time]).iloc[-1]) if not m_df["Close"].loc[:bar_time].empty else 50
                    
                    d20 = float(ema(d_df["Close"].loc[:target_date], 20).iloc[-1])
                    d50 = float(ema(d_df["Close"].loc[:target_date], 50).iloc[-1])
                    d_curr = float(d_df["Close"].loc[:target_date].iloc[-1])
                    dt = bool(d_curr > d20 > d50)
                    
                    h20 = float(ema(h_df["Close"].loc[:bar_time], 20).iloc[-1])
                    h50 = float(ema(h_df["Close"].loc[:bar_time], 50).iloc[-1])
                    h_curr = float(h_df["Close"].loc[:bar_time].iloc[-1])
                    ht = bool(h_curr > h20 > h50)
                    
                    m9 = float(ema(m_df["Close"].loc[:bar_time], 9).iloc[-1])
                    m20 = float(ema(m_df["Close"].loc[:bar_time], 20).iloc[-1])
                    price = float(m_df["Close"].loc[:bar_time].iloc[-1])
                    
                    # VWAP calculation
                    tp = (m_df["High"] + m_df["Low"] + m_df["Close"]) / 3.0
                    day_group = m_df.index.date
                    cum_vol = m_df["Volume"].groupby(day_group).cumsum()
                    cum_tp_vol = (tp * m_df["Volume"]).groupby(day_group).cumsum()
                    vwap_series = cum_tp_vol / cum_vol.replace(0, np.nan)
                    vw = float(vwap_series.loc[bar_time]) if bar_time in vwap_series.index else price
                    
                    avw = bool(price >= vw)
                    
                    # Check alignment filters
                    hard_alignment = (dr >= 55 and hr >= 55 and mr >= 50 and dt and ht and avw)
                    
                    if hard_alignment:
                        # Compute ATR Stop and targets
                        atrv = float(atr(m_df.loc[:bar_time], 14).iloc[-1])
                        sl = round(price - 1.5 * atrv, 2)
                        t1 = round(price * 1.01, 2)
                        t2 = round(price * 1.02, 2)
                        
                        # Evaluate subsequent bars in this session (day)
                        post_bars = day_bars.iloc[bar_idx + 1:]
                        outcome = "Active"
                        current_p = price
                        max_gain = 0.0
                        
                        for _, post_bar in post_bars.iterrows():
                            high = float(post_bar["High"])
                            low = float(post_bar["Low"])
                            current_p = float(post_bar["Close"])
                            max_gain = max(max_gain, ((high - price) / price) * 100)
                            
                            hit_sl = low <= sl
                            hit_t2 = high >= t2
                            hit_t1 = high >= t1
                            
                            if hit_sl and (hit_t2 or hit_t1):
                                outcome = "Stopped Out"
                                break
                            elif hit_sl:
                                outcome = "Stopped Out"
                                break
                            elif hit_t2:
                                outcome = "Hit Target 2%"
                                break
                            elif hit_t1:
                                outcome = "Hit Target 1%"
                                # Continue checking if it hits Target 2% before Stop Loss
                                
                        ret = ((current_p - price) / price) * 100.0
                        
                        rows.append({
                            "Symbol": symbol,
                            "Signal Time": bar_time.strftime("%Y-%m-%d %H:%M"),
                            "Entry Price": price,
                            "Stop Loss": sl,
                            "Target 1%": t1,
                            "Target 2%": t2,
                            "Current Price": current_p,
                            "Return %": round(ret, 2),
                            "Max Gain %": round(max_gain, 2),
                            "Outcome": outcome
                        })
                        
                        # Only take the first trigger bar of the day to prevent overlapping signals
                        break
        except Exception:
            continue
            
    if not rows:
        return pd.DataFrame()
        
    df = pd.DataFrame(rows)
    df = df.sort_values("Signal Time", ascending=False)
    return df

def evaluate_options_performance(signals, data_map):
    """
    Simulates options strategy performance by calculating estimated payoff P&L
    based on subsequent spot price movements of the underlying assets.
    """
    rows = []
    
    for sig in signals:
        # Check if the signal has a valid recommended options strategy
        symbol = sig["Symbol"]
        sig_date = pd.to_datetime(sig["Signal Date"])
        entry_price = sig["Entry Price"]
        outcome = sig["Outcome"]
        strategy = "BULL_CALL_SPREAD" if sig["Action"] == "BUY" else "BEAR_PUT_SPREAD"
        
        if symbol not in data_map:
            continue
            
        d = data_map[symbol]
        current_price = float(d["Close"].iloc[-1])
        
        # Estimate Lot Size
        LOT_SIZES = {
            "NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 65, "MIDCPNIFTY": 75,
            "RELIANCE": 250, "HDFCBANK": 550, "ICICIBANK": 700, "SBIN": 750,
            "AXISBANK": 625, "KOTAKBANK": 400, "INFY": 400, "TCS": 175,
            "BHARTIARTL": 475, "LT": 175, "ITC": 1600, "TATAMOTORS": 575,
            "M&M": 350, "TRENT": 100, "HAL": 150, "BEL": 1425, "DIXON": 50,
            "POLYCAB": 100, "PERSISTENT": 100, "COFORGE": 75, "MCX": 125,
            "ZOMATO": 2000, "BAJFINANCE": 125, "MARUTI": 50, "SUNPHARMA": 350,
            "TATAPOWER": 1350
        }
        lot_size = LOT_SIZES.get(symbol.upper(), 250)
        
        # Estimate ATM option strike and pricing
        step = 50 if entry_price > 2000 else (20 if entry_price > 800 else (10 if entry_price > 250 else 5))
        atm_strike = round(entry_price / step) * step
        
        # Simulating Buy ATM, Sell OTM spreads (+3% for Bull, -3% for Bear)
        if strategy == "BULL_CALL_SPREAD":
            sell_strike = round((entry_price * 1.03) / step) * step
            buy_premium = entry_price * 0.02 # ATM CE approx 2% of spot
            sell_premium = entry_price * 0.008 # OTM CE approx 0.8% of spot
            net_premium = buy_premium - sell_premium
            
            # Current P&L at Expiry simulation
            val_entry_strike_exp = max(current_price - atm_strike, 0)
            val_sell_strike_exp = max(current_price - sell_strike, 0)
            current_value = val_entry_strike_exp - val_sell_strike_exp
            pnl_per_share = current_value - net_premium
            pnl = pnl_per_share * lot_size
            max_loss = net_premium * lot_size
            max_profit = (sell_strike - atm_strike - net_premium) * lot_size
            
        else: # BEAR_PUT_SPREAD
            sell_strike = round((entry_price * 0.97) / step) * step
            buy_premium = entry_price * 0.02 # ATM PE approx 2% of spot
            sell_premium = entry_price * 0.008 # OTM PE approx 0.8% of spot
            net_premium = buy_premium - sell_premium
            
            # Current P&L at Expiry simulation
            val_entry_strike_exp = max(atm_strike - current_price, 0)
            val_sell_strike_exp = max(sell_strike - current_price, 0)
            current_value = val_entry_strike_exp - val_sell_strike_exp
            pnl_per_share = current_value - net_premium
            pnl = pnl_per_share * lot_size
            max_loss = net_premium * lot_size
            max_profit = (atm_strike - sell_strike - net_premium) * lot_size
            
        rows.append({
            "Symbol": symbol,
            "Strategy": strategy,
            "Signal Date": sig["Signal Date"],
            "Entry Spot": entry_price,
            "Current Spot": current_price,
            "ATM Strike": atm_strike,
            "OTM Strike": sell_strike,
            "Net Premium": round(net_premium, 2),
            "Max Loss": round(max_loss, 2),
            "Max Profit": round(max_profit, 2),
            "Estimated P&L": round(pnl, 2),
            "Status": outcome
        })
        
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────
# Manually Tracked Signals & Watchlist Helpers
# ─────────────────────────────────────────────

TRACKED_SIGNALS_PATH = Path("cache/tracked_signals.json")

def load_tracked_signals():
    if TRACKED_SIGNALS_PATH.exists():
        try:
            with open(TRACKED_SIGNALS_PATH, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_tracked_signals(signals):
    with open(TRACKED_SIGNALS_PATH, "w") as f:
        json.dump(signals, f, indent=2)

def add_tracked_signal(symbol, sig_type, entry_price, stop_loss, target_1=None, target_2=None, target_5=None, score=None, action="BUY"):
    signals = load_tracked_signals()
    now = datetime.now()
    sig_date = now.strftime("%Y-%m-%d")
    sig_time = now.strftime("%Y-%m-%d %H:%M")
    
    # Check if duplicate exists
    for s in signals:
        if s["symbol"].upper() == symbol.upper() and s["type"] == sig_type and s["signal_date"] == sig_date:
            return False, f"Symbol {symbol} is already being tracked for {sig_type} on {sig_date}."
            
    signals.append({
        "symbol": symbol.upper(),
        "type": sig_type,
        "signal_date": sig_date,
        "signal_time": sig_time,
        "entry_price": float(entry_price),
        "stop_loss": float(stop_loss),
        "target_1": float(target_1) if target_1 is not None else None,
        "target_2": float(target_2) if target_2 is not None else None,
        "target_5": float(target_5) if target_5 is not None else None,
        "score": float(score) if score is not None else None,
        "action": action
    })
    save_tracked_signals(signals)
    return True, f"Successfully added {symbol} to tracked signals."

def evaluate_tracked_signals_performance():
    signals = load_tracked_signals()
    if not signals:
        return pd.DataFrame()
        
    rows = []
    for sig in signals:
        sym = sig["symbol"]
        sig_type = sig["type"]
        entry = sig["entry_price"]
        sl = sig["stop_loss"]
        t1 = sig.get("target_1")
        t2 = sig.get("target_2")
        t5 = sig.get("target_5")
        sig_date_str = sig["signal_date"]
        sig_time_str = sig["signal_time"]
        
        # Format index symbol
        _INDEX_YF_MAP = {
            "NIFTY": "^NSEI",
            "BANKNIFTY": "^NSEBANK",
            "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
            "MIDCPNIFTY": "^CNXMIDCAP",
            "SENSEX": "^BSESN",
        }
        yf_sym = _INDEX_YF_MAP.get(sym, sym)
        
        try:
            if sig_type == "Swing":
                # Fetch recent daily data
                d = download_ticker_data(yf_sym, "1mo", "1d")
                if d.empty:
                    continue
                # Remove timezone info if any
                if d.index.tz is not None:
                    d.index = d.index.tz_localize(None)
                # Slice from signal date
                post_sig = d.loc[d.index >= pd.to_datetime(sig_date_str)]
                if post_sig.empty:
                    current_close = entry
                    max_high = entry
                    outcome = "Active"
                else:
                    current_close = float(post_sig["Close"].iloc[-1])
                    max_high = float(post_sig["High"].max())
                    outcome = "Active"
                    for _, bar in post_sig.iterrows():
                        high = float(bar["High"])
                        low = float(bar["Low"])
                        
                        hit_sl = low <= sl
                        hit_t5 = t5 is not None and high >= t5
                        hit_t2 = t2 is not None and high >= t2
                        
                        if hit_sl and (hit_t5 or hit_t2):
                            outcome = "Stopped Out"
                            break
                        elif hit_sl:
                            outcome = "Stopped Out"
                            break
                        elif hit_t5:
                            outcome = "Hit Target 5%"
                            break
                        elif hit_t2:
                            outcome = "Hit Target 2%"
                            
            else: # Intraday
                # Fetch recent 15m data
                d = download_ticker_data(yf_sym, "5d", "15m")
                if d.empty:
                    continue
                # Remove timezone info if any
                if d.index.tz is not None:
                    d.index = d.index.tz_localize(None)
                # Slice from signal time
                post_sig = d.loc[d.index >= pd.to_datetime(sig_time_str)]
                if post_sig.empty:
                    current_close = entry
                    max_high = entry
                    outcome = "Active"
                else:
                    current_close = float(post_sig["Close"].iloc[-1])
                    max_high = float(post_sig["High"].max())
                    outcome = "Active"
                    for _, bar in post_sig.iterrows():
                        high = float(bar["High"])
                        low = float(bar["Low"])
                        
                        hit_sl = low <= sl
                        hit_t2 = t2 is not None and high >= t2
                        hit_t1 = t1 is not None and high >= t1
                        
                        if hit_sl and (hit_t2 or hit_t1):
                            outcome = "Stopped Out"
                            break
                        elif hit_sl:
                            outcome = "Stopped Out"
                            break
                        elif hit_t2:
                            outcome = "Hit Target 2%"
                            break
                        elif hit_t1:
                            outcome = "Hit Target 1%"
                            
            curr_return = ((current_close - entry) / entry) * 100.0
            max_return = ((max_high - entry) / entry) * 100.0
            
            rows.append({
                "Symbol": sym,
                "Type": sig_type,
                "Signal Date/Time": sig_time_str if sig_type == "Intraday" else sig_date_str,
                "Entry Price": entry,
                "Stop Loss": sl,
                "Target 1%": t1 if t1 is not None else np.nan,
                "Target 2%": t2 if t2 is not None else np.nan,
                "Target 5%": t5 if t5 is not None else np.nan,
                "Current Price": current_close,
                "Return %": round(curr_return, 2),
                "Max Gain %": round(max_return, 2),
                "Outcome": outcome
            })
        except Exception:
            continue
            
    return pd.DataFrame(rows)
