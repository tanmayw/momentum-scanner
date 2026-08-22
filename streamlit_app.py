import os
import io
import time
import requests
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from pathlib import Path
import streamlit as st

NSE_CSV_URLS = [
    "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
    "https://www.nseindia.com/content/indices/ind_nifty500list.csv",
]
FALLBACK_CSV_URL = "https://raw.githubusercontent.com/ganeshbiyer/Nse_Historical_Data/main/nifty500_symbols.csv"

def get_nifty500_symbols():
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/csv,*/*"}
    for url in NSE_CSV_URLS:
        try:
            r = requests.get(url, headers=headers, timeout=20)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            symbol_col = next((c for c in df.columns if c.strip().lower() == "symbol"), None)
            if symbol_col:
                syms = df[symbol_col].astype(str).str.strip().tolist()
                syms = [s for s in syms if s and s.lower() != "nan"]
                if len(syms) >= 450:
                    return sorted(set(syms)), "NSE/Nifty Indices"
        except Exception:
            pass

    r = requests.get(FALLBACK_CSV_URL, timeout=20)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    col = next((c for c in df.columns if c.lower() in ["symbol", "ticker"]), None)
    if col:
        syms = df[col].astype(str).str.strip().tolist()
        return sorted(set(syms)), "GitHub fallback"
    raise RuntimeError("Could not load Nifty 500 constituents")


# ─────────────────────────────────────────────
#  Technical indicator helpers
# ─────────────────────────────────────────────

def rsi(s, period=14):
    delta = s.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def ema(s, period):
    return s.ewm(span=period, adjust=False, min_periods=period).mean()

def atr(df, period=14):
    prev = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev).abs(),
        (df["Low"] - prev).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False, min_periods=period).mean()

def adx(df, period=14):
    high, low, close = df["High"], df["Low"], df["Close"]
    up = high.diff()
    down = -low.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    prev = close.shift(1)
    tr = pd.concat([(high-low), (high-prev).abs(), (low-prev).abs()], axis=1).max(axis=1)
    atrv = tr.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1/period, adjust=False, min_periods=period).mean() / atrv
    minus_di = 100 * minus_dm.ewm(alpha=1/period, adjust=False, min_periods=period).mean() / atrv
    dx = 100 * (plus_di-minus_di).abs() / (plus_di+minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1/period, adjust=False, min_periods=period).mean()


# ─────────────────────────────────────────────
#  Caching & data download
# ─────────────────────────────────────────────

CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

def download_prices(symbols):
    today_str = datetime.now().strftime("%Y-%m-%d")
    cache_file = CACHE_DIR / f"prices_{today_str}.parquet"

    if cache_file.exists():
        df = pd.read_parquet(cache_file)
        tickers = df.index.get_level_values(0).unique()
        all_data = {ticker: df.xs(ticker, level=0) for ticker in tickers}
        return all_data

    tickers = [s.replace("&", "-").replace(" ", "") + ".NS" for s in symbols]
    all_data = {}
    for start in range(0, len(tickers), 80):
        batch = tickers[start:start+80]
        raw = yf.download(
            batch, period="3y", interval="1d", auto_adjust=True,
            group_by="ticker", progress=False, threads=True
        )
        if raw.empty:
            continue
        for ticker in batch:
            try:
                d = raw[ticker].dropna(how="all").copy()
                if len(d) >= 260:
                    all_data[ticker.replace(".NS", "")] = d
            except Exception:
                continue

    if all_data:
        combined = pd.concat(all_data.values(), keys=all_data.keys(), names=["Ticker", "Date"])
        combined.to_parquet(cache_file)

    return all_data

def get_benchmark():
    """
    Download benchmark index for relative-strength calculation.
    Tries Nifty 500 (^CRSLDX) first, falls back to Nifty 50 (^NSEI).
    """
    for ticker in ["^CRSLDX", "^NSEI"]:
        try:
            raw = yf.download(ticker, period="3y", interval="1d",
                              auto_adjust=True, progress=False)
            if raw.empty:
                continue
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            if "Close" in raw.columns and len(raw) >= 126:
                return raw["Close"]
        except Exception:
            continue
    return pd.Series(dtype=float)


# ─────────────────────────────────────────────
#  Scoring helpers — exactly as per spec
# ─────────────────────────────────────────────

def rsi_score(x, kind):
    """RSI scoring tables from spec (monthly/weekly: 15 pts, daily: 10 pts)."""
    if pd.isna(x):
        return 0
    if kind in ("monthly", "weekly"):
        bins = [(60, 65, 10), (65, 70, 12), (70, 75, 15), (75, 80, 12), (80, 101, 8)]
    else:  # daily
        bins = [(50, 55, 7), (55, 60, 10), (60, 65, 9), (65, 70, 7), (70, 75, 4), (75, 101, 2)]
    for lo, hi, pts in bins:
        if lo <= x < hi:
            return pts
    return 0


def calc_trend_score(price, e20, e50, e200):
    """
    Spec §5 — Trend Score (15 pts):
      15 → Close > EMA20 > EMA50 > EMA200   (full alignment)
      12 → Close > EMA20 > EMA50, EMA50 ≈ EMA200 (within 2%)
       8 → Close > EMA50 > EMA200
       0 → anything else
    """
    if any(pd.isna(v) for v in [price, e20, e50, e200]):
        return 0
    if price > e20 and e20 > e50 and e50 > e200:
        return 15
    if price > e20 and e20 > e50 and e200 != 0 and abs(e50 - e200) / e200 <= 0.02:
        return 12
    if price > e50 and e50 > e200:
        return 8
    return 0


def calc_rs_score(rs_decimal):
    """
    Spec §9 — Relative Strength score (5 pts).
    rs_decimal = stock_6M_return - benchmark_6M_return  (as a decimal, e.g. 0.18)
    """
    if pd.isna(rs_decimal):
        return 0
    rs = rs_decimal * 100  # convert to percentage points
    if rs > 20:  return 5
    if rs > 10:  return 4
    if rs > 5:   return 3
    if rs > 0:   return 1
    return 0


def calc_price_vs_ema20_score(price, e20):
    """
    Spec §13 Entry Score — Price vs EMA20 (15 pts).
    Sweet spot = just pulled back to EMA20 (0–3% above).
    More extended → lower score.
    """
    if pd.isna(price) or pd.isna(e20) or e20 == 0:
        return 0
    pct_above = (price - e20) / e20 * 100
    if pct_above < 0:    return 0   # below EMA20
    if pct_above <= 3:   return 15  # ideal pullback zone
    if pct_above <= 8:   return 12  # mild extension
    if pct_above <= 15:  return 8   # notable extension
    return 3                         # very extended


def calc_breakout_pullback_score(price, e20, high52, vol_ratio):
    """
    Spec §13 Entry Score — Breakout / Pullback setup (15 pts).
    Combines price pattern with volume confirmation so volume alone
    on a falling stock does NOT score well.
      15 → Price within 2% of 52W high AND volume >= 1.5× avg  (breakout)
      12 → Price has pulled back to EMA20 (within 2%) from above (pullback to support)
       8 → Price above EMA20 with decent volume (continuation)
       3 → Default / unclear setup
    """
    if any(pd.isna(v) for v in [price, e20, high52, vol_ratio]) or high52 == 0:
        return 3
    dist_from_high = (high52 - price) / high52
    pct_above_ema20 = (price - e20) / e20 if e20 != 0 else 0

    # Breakout: near all-time/52W high with strong volume
    if dist_from_high <= 0.02 and vol_ratio >= 1.5:
        return 15
    # Pullback to EMA20: clean entry at dynamic support
    if 0 <= pct_above_ema20 <= 0.02:
        return 12
    # Continuation move above EMA20 with above-average volume
    if price > e20 and vol_ratio >= 1.0:
        return 8
    return 3


def calc_rr_score(rr_ratio):
    """
    Spec §13 Entry Score — Risk/Reward component (5 pts).
    """
    if pd.isna(rr_ratio) or rr_ratio <= 0:
        return 0
    if rr_ratio >= 2.5: return 5
    if rr_ratio >= 2.0: return 4
    if rr_ratio >= 1.5: return 3
    if rr_ratio >= 1.0: return 1
    return 0


# ─────────────────────────────────────────────
#  Per-stock metric calculation
# ─────────────────────────────────────────────

def calculate_metrics(symbol, d, benchmark):
    d = d[["Open", "High", "Low", "Close", "Volume"]].dropna().copy()
    if len(d) < 260:
        return None

    w = d.resample("W-FRI").agg({"Close": "last"}).dropna()
    m = d.resample("ME").agg({"Close": "last"}).dropna()
    if len(w) < 30 or len(m) < 18:
        return None

    close = d["Close"]
    current  = float(close.iloc[-1])
    m_rsi    = float(rsi(m["Close"]).iloc[-1])
    w_rsi    = float(rsi(w["Close"]).iloc[-1])
    d_rsi    = float(rsi(close).iloc[-1])

    e20  = float(ema(close, 20).iloc[-1])
    e50  = float(ema(close, 50).iloc[-1])
    e200 = float(ema(close, 200).iloc[-1])
    adxv = float(adx(d).iloc[-1])
    atrv = float(atr(d).iloc[-1])

    vol20      = float(d["Volume"].rolling(20).mean().iloc[-1])
    vol_ratio  = float(d["Volume"].iloc[-1] / vol20) if vol20 else np.nan
    high52     = float(close.tail(252).max())
    dist52     = (high52 - current) / high52

    ret3 = float(close.iloc[-1] / close.iloc[-64]  - 1) if len(close) >= 64  else np.nan
    ret6 = float(close.iloc[-1] / close.iloc[-126] - 1) if len(close) >= 126 else np.nan

    # Relative strength vs benchmark (Nifty 500 or Nifty 50)
    b = benchmark.dropna()
    rs6 = np.nan
    if len(b) >= 126 and not pd.isna(ret6):
        br  = float(b.iloc[-1] / b.iloc[-126] - 1)
        rs6 = ret6 - br

    hard = (
        m_rsi >= 60 and w_rsi >= 60 and d_rsi >= 50 and
        current > e20 > e50 > e200 and
        adxv >= 20 and vol_ratio >= 1.0 and
        ret3 > 0 and ret6 > 0 and dist52 <= 0.10
    )

    return {
        "Symbol":       symbol,
        "Price":        current,
        "Monthly RSI":  m_rsi,
        "Weekly RSI":   w_rsi,
        "Daily RSI":    d_rsi,
        "EMA20":        e20,
        "EMA50":        e50,
        "EMA200":       e200,
        "ADX":          adxv,
        "ATR":          atrv,
        "Vol Ratio":    vol_ratio,
        "3M Return":    ret3,
        "6M Return":    ret6,
        "RS vs Nifty":  rs6,
        "52W High":     high52,
        "52W Distance": dist52,
        "Hard Filter":  hard,
    }


# ─────────────────────────────────────────────
#  Composite scoring (spec §3–§13)
# ─────────────────────────────────────────────

def score_candidates(df):
    out = df.copy()

    # ── Momentum Score components ──────────────────────────────────

    # RSI scores (spec §4)
    out["M RSI Score"] = out["Monthly RSI"].apply(lambda x: rsi_score(x, "monthly"))
    out["W RSI Score"] = out["Weekly RSI"].apply(lambda x: rsi_score(x, "weekly"))
    out["D RSI Score"] = out["Daily RSI"].apply(lambda x: rsi_score(x, "daily"))

    # Trend Score with 15/12/8/0 grading (spec §5)
    out["Trend Score"] = out.apply(
        lambda r: calc_trend_score(r["Price"], r["EMA20"], r["EMA50"], r["EMA200"]), axis=1
    )

    # ADX Score (spec §6)
    out["ADX Score"] = out["ADX"].apply(
        lambda x: 0 if x < 20 else 5 if x < 25 else 7 if x < 30 else 10 if x < 40 else 8 if x < 50 else 6
    )

    # 3M momentum — discrete percentile buckets (spec §7)
    ret3_rank = out["3M Return"].rank(pct=True)
    out["3M Score"] = ret3_rank.apply(
        lambda p: 10 if p >= 0.90 else 8 if p >= 0.75 else 6 if p >= 0.50 else 4 if p >= 0.25 else 0
    )

    # 6M momentum — discrete percentile buckets (spec §8)
    ret6_rank = out["6M Return"].rank(pct=True)
    out["6M Score"] = ret6_rank.apply(
        lambda p: 10 if p >= 0.90 else 8 if p >= 0.75 else 6 if p >= 0.50 else 4 if p >= 0.25 else 0
    )

    # Relative Strength — discrete bucket table (spec §9)
    out["RS Score"] = out["RS vs Nifty"].apply(calc_rs_score)

    # Volume Score (spec §10)
    out["Volume Score"] = out["Vol Ratio"].apply(
        lambda x: 0 if x < 1 else 2 if x < 1.2 else 3 if x < 1.5 else 4 if x < 2 else 5
    )

    # 52W Distance Score (spec §11)
    out["52W Score"] = out["52W Distance"].apply(
        lambda x: 5 if x <= 0.05 else 4 if x <= 0.10 else 2 if x <= 0.15 else 0
    )

    score_cols = [
        "M RSI Score", "W RSI Score", "D RSI Score", "Trend Score", "ADX Score",
        "3M Score", "6M Score", "RS Score", "Volume Score", "52W Score"
    ]
    out["Momentum Score"] = out[score_cols].sum(axis=1).round(1)

    # ── Risk / Reward (needed before Entry Score) ──────────────────
    out["Stop Loss"]  = (out["Price"] - 1.5 * out["ATR"]).round(2)
    out["Target 2%"]  = (out["Price"] * 1.02).round(2)
    out["Target 5%"]  = (out["Price"] * 1.05).round(2)
    out["Risk Amt"]   = (out["Price"] - out["Stop Loss"]).clip(lower=0.01)
    out["RR Ratio"]   = ((out["Target 5%"] - out["Price"]) / out["Risk Amt"]).replace(
                            [np.inf, -np.inf], np.nan).round(2)
    out["Risk %"]     = (out["Risk Amt"] / out["Price"] * 100).round(2)

    # ── Filter: remove setups with R:R < 1.5 (spec §15) ──────────
    out = out[out["RR Ratio"] >= 1.5].copy()
    if out.empty:
        return out

    # ── Entry Score components (spec §13) ─────────────────────────

    # 1. Daily RSI setup — 15 pts
    out["Entry RSI Score"] = out["Daily RSI"].apply(
        lambda x: 15 if 55 <= x < 65 else 12 if 50 <= x < 55 else 8 if 65 <= x < 70 else 3
    )

    # 2. Price vs EMA20 — 15 pts
    out["Entry EMA20 Score"] = out.apply(
        lambda r: calc_price_vs_ema20_score(r["Price"], r["EMA20"]), axis=1
    )

    # 3. Breakout / Pullback detection — 15 pts
    out["Entry BP Score"] = out.apply(
        lambda r: calc_breakout_pullback_score(
            r["Price"], r["EMA20"], r["52W High"], r["Vol Ratio"]
        ), axis=1
    )

    # 4. Volume confirmation — 10 pts
    out["Entry Vol Score"] = out["Vol Ratio"].apply(
        lambda x: 10 if x >= 1.5 else 7 if x >= 1.2 else 4
    )

    # 5. Risk/Reward — 5 pts
    out["Entry RR Score"] = out["RR Ratio"].apply(calc_rr_score)

    # Entry Score = Momentum(40%) + RSI(15) + EMA20(15) + BP(15) + Vol(10) + RR(5) = 100
    out["Entry Score"] = (
        out["Momentum Score"] * 0.40
        + out["Entry RSI Score"]
        + out["Entry EMA20 Score"]
        + out["Entry BP Score"]
        + out["Entry Vol Score"]
        + out["Entry RR Score"]
    ).clip(upper=100).round(1)

    # Final Score (spec §13)
    out["Final Score"] = (0.60 * out["Momentum Score"] + 0.40 * out["Entry Score"]).round(1)

    # Action labels (spec §14)
    out["Action"] = np.select(
        [out["Final Score"] >= 85, out["Final Score"] >= 75, out["Final Score"] >= 65],
        ["BUY", "WATCH / PULLBACK", "WATCHLIST"],
        default="AVOID"
    )

    return out.sort_values(["Final Score", "Momentum Score"], ascending=False)


# ─────────────────────────────────────────────
#  Streamlit Interface & Styling
# ─────────────────────────────────────────────

def style_dataframe(df):
    def color_action(val):
        if val == "BUY":
            return "background-color: rgba(46, 204, 113, 0.15); color: #2ecc71; font-weight: bold;"
        elif val == "WATCH / PULLBACK":
            return "background-color: rgba(241, 196, 15, 0.15); color: #f1c40f; font-weight: bold;"
        elif val == "WATCHLIST":
            return "background-color: rgba(52, 152, 219, 0.15); color: #3498db;"
        else:
            return "background-color: rgba(231, 76, 60, 0.15); color: #e74c3c;"

    def color_rsi(val):
        if pd.isna(val): return ""
        if val >= 70:
            return "background-color: rgba(230, 126, 34, 0.2); color: #e67e22; font-weight: bold;"
        elif val >= 60:
            return "background-color: rgba(241, 196, 15, 0.15); color: #f1c40f;"
        return ""

    def color_rr(val):
        if pd.isna(val): return ""
        if val >= 2.0:
            return "background-color: rgba(46, 204, 113, 0.15); color: #2ecc71; font-weight: bold;"
        elif val >= 1.5:
            return "background-color: rgba(241, 196, 15, 0.15); color: #f1c40f;"
        return ""

    def color_return(val):
        if pd.isna(val): return ""
        return "color: #2ecc71;" if val >= 0 else "color: #e74c3c;"

    styled = df.style.map(color_action, subset=["Action"]) \
                     .map(color_rsi, subset=["Monthly RSI", "Weekly RSI", "Daily RSI"]) \
                     .map(color_rr, subset=["RR Ratio"]) \
                     .map(color_return, subset=["3M Return", "6M Return", "RS vs Nifty"])
    
    styled = styled.format({
        "Price": "₹{:.2f}",
        "Stop Loss": "₹{:.2f}",
        "Target 2%": "₹{:.2f}",
        "Target 5%": "₹{:.2f}",
        "Final Score": "{:.1f}",
        "Momentum Score": "{:.1f}",
        "Entry Score": "{:.1f}",
        "Monthly RSI": "{:.1f}",
        "Weekly RSI": "{:.1f}",
        "Daily RSI": "{:.1f}",
        "ADX": "{:.1f}",
        "Vol Ratio": "{:.2f}",
        "RR Ratio": "{:.2f}",
        "Risk %": "{:.2f}%",
        "3M Return": "{:.2f}%",
        "6M Return": "{:.2f}%",
        "RS vs Nifty": "{:.2f}%",
        "52W Distance": "{:.2f}%"
    })
    return styled

st.set_page_config(
    page_title="Nifty 500 Momentum Scanner",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom header styling
st.markdown("""
    <style>
    .main-title {
        font-family: 'Inter', sans-serif;
        font-weight: 700;
        margin-bottom: 0px;
    }
    .sub-title {
        font-family: 'Inter', sans-serif;
        color: #a0aec0;
        margin-top: 0px;
        margin-bottom: 25px;
    }
    </style>
""", unsafe_allow_html=True)

st.markdown("<h1 class='main-title'>📈 Nifty 500 Momentum Scanner</h1>", unsafe_allow_html=True)
st.markdown("<p class='sub-title'>Multi-Timeframe Momentum Analysis & Entry Quality Scoring</p>", unsafe_allow_html=True)

# Sidebar configurations
st.sidebar.header("Scanner Controls")

min_m = st.sidebar.slider("Monthly RSI Minimum", min_value=50, max_value=75, value=60)
min_w = st.sidebar.slider("Weekly RSI Minimum", min_value=50, max_value=75, value=60)
min_d = st.sidebar.slider("Daily RSI Minimum", min_value=40, max_value=70, value=50)
min_adx = st.sidebar.slider("ADX Minimum", min_value=10, max_value=40, value=20)
max_52w = st.sidebar.slider("Max distance from 52W high %", min_value=5, max_value=25, value=10)
top_n = st.sidebar.slider("Rows to display", min_value=5, max_value=50, value=20)

run_button = st.sidebar.button("🚀 Run Scanner", use_container_width=True)

if run_button:
    status_box = st.empty()
    
    with status_box.container():
        st.info("Step 1/4: Fetching Nifty 500 symbols list...")
    
    try:
        symbols, source = get_nifty500_symbols()
    except Exception as e:
        status_box.error(f"Error fetching symbols: {e}")
        st.stop()
        
    with status_box.container():
        st.info(f"Step 2/4: Loading historical data for {len(symbols)} tickers (Yahoo Finance/Cache)...")
        
    try:
        data_map = download_prices(symbols)
    except Exception as e:
        status_box.error(f"Error downloading prices: {e}")
        st.stop()
        
    with status_box.container():
        st.info("Step 3/4: Fetching index benchmark...")
        
    try:
        benchmark = get_benchmark()
    except Exception as e:
        status_box.error(f"Error fetching benchmark: {e}")
        st.stop()
        
    with status_box.container():
        st.info("Step 4/4: Calculating indicators and scoring...")
        
    rows = []
    progress_bar = st.progress(0.0)
    total_symbols = len(data_map)
    
    for idx, (sym, d) in enumerate(data_map.items()):
        try:
            row = calculate_metrics(sym, d, benchmark)
            if row:
                rows.append(row)
        except Exception:
            continue
        progress_bar.progress((idx + 1) / total_symbols)
        
    progress_bar.empty()
    status_box.empty()
    
    raw = pd.DataFrame(rows)
    if raw.empty:
        st.error("No valid stock data could be calculated.")
    else:
        # Apply Layer 1 hard filters
        eligible = raw[
            (raw["Monthly RSI"] >= min_m) &
            (raw["Weekly RSI"]  >= min_w) &
            (raw["Daily RSI"]   >= min_d) &
            (raw["ADX"]         >= min_adx) &
            (raw["52W Distance"] <= max_52w / 100) &
            (raw["Hard Filter"])
        ].copy()
        
        if eligible.empty:
            st.warning("No stocks passed the initial filter criteria.")
        else:
            # Score
            scored = score_candidates(eligible)
            
            if scored.empty:
                st.warning("No stocks passed the Risk/Reward threshold (R:R >= 1.5).")
            else:
                scored.insert(0, "Rank", range(1, len(scored) + 1))
                
                display_cols = [
                    "Rank", "Symbol", "Action", "Price",
                    "Final Score", "Momentum Score", "Entry Score",
                    "Monthly RSI", "Weekly RSI", "Daily RSI",
                    "ADX", "Vol Ratio", "RR Ratio", "Risk %",
                    "3M Return", "6M Return", "RS vs Nifty", "52W Distance",
                    "Stop Loss", "Target 2%", "Target 5%",
                ]
                
                view = scored[display_cols].head(top_n).copy()
                
                # Convert ratios to percentages for display columns
                for c in ["3M Return", "6M Return", "RS vs Nifty", "52W Distance"]:
                    view[c] = (view[c] * 100).round(2)
                
                st.success(f"Scan complete! Found {len(view)} results.")
                
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**Source**: {source} | **Benchmark**: Relative strength compared vs Nifty 500 index")
                with col2:
                    csv = view.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="⬇ Export CSV",
                        data=csv,
                        file_name=f"nifty500_scan_{datetime.now().strftime('%Y-%m-%d')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                
                # Replace Symbol with TradingView link format
                view["Symbol"] = view["Symbol"].apply(lambda s: f"https://in.tradingview.com/chart/?symbol=NSE:{s}")
                
                styled_view = style_dataframe(view)
                
                st.dataframe(
                    styled_view,
                    column_config={
                        "Symbol": st.column_config.LinkColumn(
                            "Symbol",
                            help="Click to view charts on TradingView",
                            display_text=r"https://in\.tradingview\.com/chart/\?symbol=NSE:(.*)"
                        )
                    },
                    use_container_width=True,
                    hide_index=True
                )
else:
    st.info("Click '🚀 Run Scanner' in the sidebar to start scanning the Nifty 500 index.")
