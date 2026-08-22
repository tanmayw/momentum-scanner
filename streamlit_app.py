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
#  Dataframe Styling
# ─────────────────────────────────────────────

def style_dataframe(df, theme="dark"):
    is_light = (theme == "light")
    
    # Action badge colors
    c_buy_bg    = "rgba(22, 163, 74, 0.12)" if is_light else "rgba(0, 255, 136, 0.12)"
    c_buy_txt   = "#15803d" if is_light else "#00ff88"
    
    c_watch_bg  = "rgba(217, 119, 6, 0.12)" if is_light else "rgba(255, 184, 0, 0.12)"
    c_watch_txt = "#b45309" if is_light else "#ffb800"
    
    c_list_bg   = "rgba(37, 99, 235, 0.10)" if is_light else "rgba(100, 181, 246, 0.12)"
    c_list_txt  = "#1d4ed8" if is_light else "#64b5f6"
    
    c_avoid_bg  = "rgba(220, 38, 38, 0.10)" if is_light else "rgba(255, 82, 82, 0.12)"
    c_avoid_txt = "#b91c1c" if is_light else "#ff5252"
    
    c_pos_txt   = "#15803d" if is_light else "#00ff88"
    c_neg_txt   = "#b91c1c" if is_light else "#ff5252"
    
    c_rsi_hot_bg  = "rgba(217, 119, 6, 0.12)" if is_light else "rgba(255, 152, 0, 0.15)"
    c_rsi_hot_txt = "#b45309" if is_light else "#ff9800"
    
    c_rsi_warm_bg  = "rgba(234, 179, 8, 0.15)" if is_light else "rgba(255, 235, 59, 0.08)"
    c_rsi_warm_txt = "#854d0e" if is_light else "#ffeb3b"

    def color_action(val):
        if val == "BUY":
            return f"background-color:{c_buy_bg};color:{c_buy_txt};font-weight:700;letter-spacing:0.5px;"
        elif val == "WATCH / PULLBACK":
            return f"background-color:{c_watch_bg};color:{c_watch_txt};font-weight:700;"
        elif val == "WATCHLIST":
            return f"background-color:{c_list_bg};color:{c_list_txt};font-weight:600;"
        else:
            return f"background-color:{c_avoid_bg};color:{c_avoid_txt};font-weight:600;"

    def color_rsi(val):
        if pd.isna(val): return ""
        if val >= 70:
            return f"background-color:{c_rsi_hot_bg};color:{c_rsi_hot_txt};font-weight:bold;"
        elif val >= 60:
            return f"background-color:{c_rsi_warm_bg};color:{c_rsi_warm_txt};font-weight:600;"
        return ""

    def color_rr(val):
        if pd.isna(val): return ""
        if val >= 2.0:
            return f"background-color:{c_buy_bg};color:{c_buy_txt};font-weight:bold;"
        elif val >= 1.5:
            return f"background-color:{c_watch_bg};color:{c_watch_txt};font-weight:600;"
        return ""

    def color_return(val):
        if pd.isna(val): return ""
        return f"color:{c_pos_txt};font-weight:600;" if val >= 0 else f"color:{c_neg_txt};font-weight:600;"

    def color_score(val):
        if pd.isna(val): return ""
        if val >= 85:   return f"color:{c_buy_txt};font-weight:700;"
        elif val >= 75: return f"color:{c_watch_txt};font-weight:600;"
        elif val >= 65: return f"color:{c_list_txt};font-weight:600;"
        return "color:#64748b;" if is_light else "color:#9e9e9e;"

    styled = df.style \
        .map(color_action, subset=["Action"]) \
        .map(color_rsi, subset=["Monthly RSI", "Weekly RSI", "Daily RSI"]) \
        .map(color_rr, subset=["RR Ratio"]) \
        .map(color_return, subset=["3M Return", "6M Return", "RS vs Nifty"]) \
        .map(color_score, subset=["Final Score"])

    styled = styled.format({
        "Price":          "\u20b9{:.2f}",
        "Stop Loss":      "\u20b9{:.2f}",
        "Target 2%":      "\u20b9{:.2f}",
        "Target 5%":      "\u20b9{:.2f}",
        "Final Score":    "{:.1f}",
        "Momentum Score": "{:.1f}",
        "Entry Score":    "{:.1f}",
        "Monthly RSI":    "{:.1f}",
        "Weekly RSI":     "{:.1f}",
        "Daily RSI":      "{:.1f}",
        "ADX":            "{:.1f}",
        "Vol Ratio":      "{:.2f}x",
        "RR Ratio":       "{:.2f}:1",
        "Risk %":         "{:.2f}%",
        "3M Return":      "{:+.2f}%",
        "6M Return":      "{:+.2f}%",
        "RS vs Nifty":    "{:+.2f}%",
        "52W Distance":   "{:.2f}%",
    })
    return styled


# ─────────────────────────────────────────────
#  Page Config
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="Nifty 500 Momentum Scanner",
    page_icon="\U0001f4c8",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─────────────────────────────────────────────
#  Theme State
# ─────────────────────────────────────────────

if "theme" not in st.session_state:
    st.session_state.theme = "dark"

DARK = {
    "app_bg":            "linear-gradient(160deg,#050b14 0%,#080f1d 60%,#050b14 100%)",
    "bg_card":           "#0f1923",
    "border":            "rgba(255,255,255,0.06)",
    "border_hero":       "rgba(0,255,136,0.18)",
    "hero_bg":           "linear-gradient(135deg,rgba(0,255,136,0.04),rgba(100,181,246,0.04),rgba(187,134,252,0.04))",
    "title_grad":        "linear-gradient(130deg,#fff 0%,#a8c8ff 45%,#00ff88 100%)",
    "green":             "#00ff88",
    "amber":             "#ffb800",
    "blue":              "#64b5f6",
    "red":               "#ff5252",
    "purple":            "#bb86fc",
    "txt":               "#dde3ee",
    "txt2":              "#8892a4",
    "txt3":              "#3d4f65",
    "ctrl_bg":           "linear-gradient(135deg,rgba(0,255,136,0.04),rgba(100,181,246,0.04))",
    "ctrl_border":       "rgba(0,255,136,0.18)",
    "legend_bg":         "rgba(255,255,255,0.02)",
    "legend_border":     "rgba(255,255,255,0.05)",
    "rbanner_bg":        "linear-gradient(135deg,rgba(0,255,136,0.06),rgba(100,181,246,0.06))",
    "df_row_border":     "rgba(255,255,255,0.025)",
    "th_bg":             "rgba(0,255,136,0.05)",
    "th_color":          "#00ff88",
    "th_border":         "rgba(0,255,136,0.12)",
    "toggle_bg":         "rgba(255,255,255,0.08)",
    "toggle_bdr":        "rgba(255,255,255,0.15)",
    "toggle_txt":        "#dde3ee",
    "toggle_icon":       "☀️",
    "toggle_label":      "Light Mode",
    "btn_bg":            "linear-gradient(135deg,#00bb5a,#00ff88)",
    "btn_txt":           "#040c12",
    "step_num_color":    "#00ff88",
    "step_hover_border": "rgba(0,255,136,0.3)",
    "hero_badge_bg":     "rgba(0,255,136,0.08)",
    "hero_badge_bdr":    "rgba(0,255,136,0.28)",
    "hero_badge_txt":    "#00ff88",
}
LIGHT = {
    "app_bg":            "linear-gradient(160deg,#f8fafc 0%,#f1f5f9 60%,#e2e8f0 100%)",
    "bg_card":           "#ffffff",
    "border":            "rgba(0,0,0,0.08)",
    "border_hero":       "rgba(0,0,0,0.08)",
    "hero_bg":           "linear-gradient(135deg,#ffffff 0%,#f8fafc 100%)",
    "title_grad":        "linear-gradient(130deg,#0f172a 0%,#1e3a8a 50%,#0369a1 100%)",
    "green":             "#15803d",
    "amber":             "#b45309",
    "blue":              "#1d4ed8",
    "red":               "#b91c1c",
    "purple":            "#6d28d9",
    "txt":               "#0f172a",
    "txt2":              "#334155",
    "txt3":              "#64748b",
    "ctrl_bg":           "#ffffff",
    "ctrl_border":       "rgba(0,0,0,0.09)",
    "legend_bg":         "#ffffff",
    "legend_border":     "rgba(0,0,0,0.08)",
    "rbanner_bg":        "linear-gradient(135deg,#ffffff 0%,#f1f5f9 100%)",
    "df_row_border":     "rgba(0,0,0,0.06)",
    "th_bg":             "#f1f5f9",
    "th_color":          "#1e293b",
    "th_border":         "rgba(0,0,0,0.08)",
    "toggle_bg":         "#ffffff",
    "toggle_bdr":        "rgba(0,0,0,0.12)",
    "toggle_txt":        "#0f172a",
    "toggle_icon":       "🌙",
    "toggle_label":      "Dark Mode",
    "btn_bg":            "linear-gradient(135deg,#16a34a,#15803d)",
    "btn_txt":           "#ffffff",
    "step_num_color":    "#1d4ed8",
    "step_hover_border": "rgba(29,78,216,0.25)",
    "hero_badge_bg":     "rgba(21,128,61,0.08)",
    "hero_badge_bdr":    "rgba(21,128,61,0.25)",
    "hero_badge_txt":    "#15803d",
}

T = DARK if st.session_state.theme == "dark" else LIGHT

# ─────────────────────────────────────────────
#  Global CSS — Theme-Aware
# ─────────────────────────────────────────────

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;600&display=swap');

html, body, [class*="css"] {{ font-family: 'Inter', sans-serif !important; color: {T['txt']} !important; }}
.stApp {{ background: {T['app_bg']} !important; }}
#MainMenu, footer, header {{ visibility: hidden; }}

/* ── Container Layout (Desktop & Mobile) ── */
.block-container, [data-testid="stMainBlockContainer"], .main .block-container {{
    max-width: 1040px !important;
    margin: 0 auto !important;
    padding-top: 1.2rem !important;
    padding-bottom: 3rem !important;
    padding-left: 1.5rem !important;
    padding-right: 1.5rem !important;
}}

/* ── Top Bar ── */
.top-nav {{
    display: flex;
    justify-content: flex-end;
    align-items: center;
    margin-bottom: 0.6rem;
}}

/* ── Hero ── */
.hero {{
    background: {T['hero_bg']};
    border: 1px solid {T['border_hero']}; border-radius: 20px;
    padding: 2.2rem 2.5rem; margin-bottom: 1.6rem; position: relative; overflow: hidden;
}}
.hero::before {{
    content:''; position:absolute; inset:0;
    background: radial-gradient(ellipse at 20% 50%,rgba(0,255,136,0.04) 0%,transparent 55%),
                radial-gradient(ellipse at 80% 50%,rgba(100,181,246,0.04) 0%,transparent 55%);
    pointer-events:none;
}}
.hero-badge {{
    display:inline-flex; align-items:center; gap:7px;
    background:{T['hero_badge_bg']}; border:1px solid {T['hero_badge_bdr']};
    border-radius:40px; padding:4px 14px;
    font-size:0.68rem; font-weight:600; color:{T['hero_badge_txt']};
    letter-spacing:1.5px; text-transform:uppercase; margin-bottom:0.8rem;
}}
.pulse {{ width:7px; height:7px; border-radius:50%; background:{T['hero_badge_txt']};
    animation:blink 2s ease-in-out infinite; }}
@keyframes blink {{ 0%,100%{{opacity:1;transform:scale(1)}} 50%{{opacity:.3;transform:scale(.65)}} }}
.hero-title {{
    font-size:2.5rem; font-weight:900; line-height:1.1;
    letter-spacing:-1.2px; margin-bottom:.5rem;
    background:{T['title_grad']};
    -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text;
}}
.hero-sub {{ font-size:0.92rem; color:{T['txt2']}; line-height:1.5; }}
.hero-meta {{ display:flex; gap:2.2rem; margin-top:1.4rem; flex-wrap:wrap; }}
.hm-label {{ font-size:.62rem; color:{T['txt3']}; text-transform:uppercase; letter-spacing:1.2px; margin-bottom:2px; font-weight:600; }}
.hm-val   {{ font-size:.88rem; color:{T['txt']}; font-weight:600; font-family:'JetBrains Mono',monospace; }}

/* ── KPI ── */
.kpi-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:0.85rem; margin-bottom:1.8rem; }}
.kpi {{ background:{T['bg_card']}; border:1px solid {T['border']}; border-radius:14px; padding:1rem 1.2rem; position:relative; overflow:hidden; }}
.kpi::before {{ content:''; position:absolute; top:0; left:0; width:100%; height:2.5px; border-radius:14px 14px 0 0; }}
.kpi.g::before {{ background:linear-gradient(90deg,{T['green']},transparent); }}
.kpi.a::before {{ background:linear-gradient(90deg,{T['amber']},transparent); }}
.kpi.b::before {{ background:linear-gradient(90deg,{T['blue']},transparent); }}
.kpi.p::before {{ background:linear-gradient(90deg,{T['purple']},transparent); }}
.kpi-ico {{ font-size:1.3rem; margin-bottom:.25rem; }}
.kpi-val {{ font-size:1.65rem; font-weight:800; line-height:1; font-family:'JetBrains Mono',monospace; margin-bottom:.15rem; }}
.kpi-lbl {{ font-size:.66rem; color:{T['txt2']}; text-transform:uppercase; letter-spacing:.8px; font-weight:500; }}
.kpi.g .kpi-val {{ color:{T['green']}; }} .kpi.a .kpi-val {{ color:{T['amber']}; }}
.kpi.b .kpi-val {{ color:{T['blue']};  }} .kpi.p .kpi-val {{ color:{T['purple']}; }}

/* ── Hide sidebar ── */
[data-testid="stSidebar"] {{ display:none !important; }}
[data-testid="collapsedControl"] {{ display:none !important; }}

/* ── Primary Run Button ── */
button[kind="primary"], .stButton > button[kind="primary"] {{
    background:{T['btn_bg']} !important;
    color:{T['btn_txt']} !important; font-weight:800 !important; font-size:.95rem !important;
    border:none !important; border-radius:12px !important; padding:.75rem !important;
    box-shadow:0 4px 22px rgba(0,200,100,.25) !important; transition:all .25s ease !important;
}}
button[kind="primary"]:hover, .stButton > button[kind="primary"]:hover {{
    transform:translateY(-2px) scale(1.01) !important;
    box-shadow:0 8px 32px rgba(0,200,100,.4) !important;
}}

/* ── Secondary / Theme Toggle Button ── */
button[kind="secondary"], .stButton > button[kind="secondary"] {{
    background: {T['toggle_bg']} !important;
    color: {T['toggle_txt']} !important;
    border: 1px solid {T['toggle_bdr']} !important;
    border-radius: 40px !important;
    padding: 0.35rem 1rem !important;
    font-size: 0.8rem !important;
    font-weight: 600 !important;
    box-shadow: none !important;
    transition: all 0.2s ease !important;
}}
button[kind="secondary"]:hover, .stButton > button[kind="secondary"]:hover {{
    border-color: {T['green']} !important;
    color: {T['green']} !important;
    transform: translateY(-1px) !important;
}}

/* ── Download Button ── */
.stDownloadButton > button {{
    background:rgba(100,181,246,.07) !important; color:{T['blue']} !important;
    border:1px solid rgba(100,181,246,.28) !important; border-radius:10px !important;
    font-weight:600 !important; transition:all .2s !important;
}}
.stDownloadButton > button:hover {{ background:rgba(100,181,246,.14) !important; }}

/* ── Progress ── */
.stProgress > div > div {{ background:linear-gradient(90deg,{T['green']},#00b4ff) !important; border-radius:40px !important; }}

/* ── Dataframe ── */
[data-testid="stDataFrame"] {{ border:1px solid {T['border']} !important; border-radius:14px !important; overflow:hidden !important; }}
[data-testid="stDataFrame"] thead th {{
    background:{T['th_bg']} !important; color:{T['th_color']} !important;
    font-size:.65rem !important; font-weight:700 !important; text-transform:uppercase !important;
    letter-spacing:.9px !important; border-bottom:1px solid {T['th_border']} !important;
}}
[data-testid="stDataFrame"] tbody td {{ font-family:'JetBrains Mono',monospace !important; font-size:.78rem !important; border-bottom:1px solid {T['df_row_border']} !important; }}

/* ── Expander Styling (Dark & Light) ── */
[data-testid="stExpander"] {{
    background: {T['bg_card']} !important;
    border: 1px solid {T['ctrl_border']} !important;
    border-radius: 16px !important;
    overflow: hidden !important;
    margin-bottom: 1.5rem !important;
}}
[data-testid="stExpander"] details {{
    background: transparent !important;
    border: none !important;
}}
[data-testid="stExpander"] summary {{
    background: {T['ctrl_bg']} !important;
    color: {T['txt']} !important;
    font-weight: 700 !important;
    font-size: 0.95rem !important;
    padding: 0.9rem 1.4rem !important;
}}
[data-testid="stExpander"] summary:hover {{
    color: {T['green']} !important;
}}
[data-testid="stExpander"] [data-testid="stExpanderDetails"] {{
    background: {T['bg_card']} !important;
    padding: 1.2rem 1.5rem !important;
    border-top: 1px solid {T['border']} !important;
}}

.ctrl-section-title {{
    font-size:.68rem; font-weight:700; color:{T['txt3']};
    text-transform:uppercase; letter-spacing:1.3px; margin:0.8rem 0 .3rem;
}}

/* ── Results Banner ── */
.rbanner {{
    background:{T['rbanner_bg']};
    border:1px solid {T['border_hero']}; border-radius:14px;
    padding:1rem 1.5rem; margin-bottom:1.4rem;
    display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:1rem;
}}
.rb-count {{ font-size:1.35rem; font-weight:800; color:{T['green']}; font-family:'JetBrains Mono',monospace; }}
.rb-label {{ font-size:.75rem; color:{T['txt2']}; margin-top:2px; }}
.rb-meta  {{ font-size:.7rem; color:{T['txt3']}; font-family:'JetBrains Mono',monospace; }}

/* ── Legend ── */
.legend {{ display:flex; gap:2rem; flex-wrap:wrap; align-items:center;
    padding:.85rem 1.4rem; background:{T['legend_bg']};
    border:1px solid {T['legend_border']}; border-radius:12px; margin-top:1.2rem; }}
.leg-item {{ display:flex; align-items:center; gap:7px; }}
.leg-dot  {{ width:8px; height:8px; border-radius:50%; flex-shrink:0; }}
.leg-txt  {{ font-size:.72rem; color:{T['txt2']}; }}
.leg-tip  {{ margin-left:auto; font-size:.68rem; color:{T['txt3']}; font-style:italic; }}

/* ── Idle ── */
.idle {{ display:flex; flex-direction:column; align-items:center; justify-content:center; padding:4rem 2rem; text-align:center; }}
.idle-ico {{ font-size:4.5rem; margin-bottom:1.2rem; animation:float 3s ease-in-out infinite; }}
@keyframes float {{ 0%,100%{{transform:translateY(0)}} 50%{{transform:translateY(-14px)}} }}
.idle-h {{ font-size:1.6rem; font-weight:700; color:{T['txt']}; margin-bottom:.5rem; }}
.idle-p {{ font-size:.92rem; color:{T['txt2']}; max-width:440px; line-height:1.7; }}
.idle-steps {{ display:flex; gap:1.2rem; margin-top:2.2rem; flex-wrap:wrap; justify-content:center; }}
.step {{ background:{T['bg_card']}; border:1px solid {T['border']}; border-radius:13px;
    padding:1rem 1.2rem; width:145px; text-align:left; transition:border-color .25s; }}
.step:hover {{ border-color:{T['step_hover_border']}; }}
.step-n {{ font-size:1.3rem; font-weight:800; color:{T['step_num_color']}; font-family:'JetBrains Mono',monospace; margin-bottom:.3rem; }}
.step-t {{ font-size:.78rem; font-weight:600; color:{T['txt']}; margin-bottom:.15rem; }}
.step-d {{ font-size:.68rem; color:{T['txt3']}; line-height:1.4; }}
[data-testid="stSlider"] label {{ font-size:.76rem !important; color:{T['txt2']} !important; }}

/* ── Mobile responsive ── */
@media (max-width: 640px) {{
    .block-container, [data-testid="stMainBlockContainer"], .main .block-container {{
        max-width: 100% !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }}
    .hero {{ padding: 1.5rem 1.2rem; }}
    .hero-title {{ font-size: 1.9rem; }}
    .hero-sub {{ font-size: .82rem; }}
    .hero-meta {{ gap: 1rem; }}
    .kpi-grid {{ grid-template-columns: repeat(3, 1fr); gap: .5rem; }}
    .kpi-val  {{ font-size: 1.35rem; }}
    .idle-steps {{ gap: .8rem; }}
    .step {{ width: 130px; }}
    .rbanner {{ flex-direction: column; gap: .5rem; }}
    .legend {{ gap: 1rem; }}
    .leg-tip {{ display: none; }}
}}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
#  Top Nav Bar (Theme Switcher)
# ─────────────────────────────────────────────

top_col_space, top_col_btn = st.columns([8, 2])
with top_col_btn:
    if st.button(f"{T['toggle_icon']} {T['toggle_label']}", key="theme_toggle", type="secondary", use_container_width=True):
        st.session_state.theme = "light" if st.session_state.theme == "dark" else "dark"
        st.rerun()

# ─────────────────────────────────────────────
#  Hero Header
# ─────────────────────────────────────────────

now_str = datetime.now().strftime("%d %b %Y, %H:%M IST")

st.markdown(f"""
<div class="hero">
    <div class="hero-badge"><span class="pulse"></span>Live Scanner &bull; Nifty 500</div>
    <div class="hero-title">Momentum Scanner</div>
    <div class="hero-sub">Multi-Timeframe RSI &nbsp;&middot;&nbsp; EMA Trend Alignment &nbsp;&middot;&nbsp; ADX Strength &nbsp;&middot;&nbsp; Relative Power vs Nifty &nbsp;&middot;&nbsp; Entry Quality Score</div>
    <div class="hero-meta">
        <div><div class="hm-label">Universe</div><div class="hm-val">Nifty 500</div></div>
        <div><div class="hm-label">Timeframes</div><div class="hm-val">D &bull; W &bull; M</div></div>
        <div><div class="hm-label">Benchmark</div><div class="hm-val">Nifty 500</div></div>
        <div><div class="hm-label">As of</div><div class="hm-val">{now_str}</div></div>
    </div>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
#  Inline Scanner Controls (mobile-friendly)
# ─────────────────────────────────────────────

with st.expander("⚙️ Scanner Controls & Filters", expanded=True):
    st.markdown('<div class="ctrl-section-title">&#128202; RSI Thresholds</div>', unsafe_allow_html=True)
    col_r1, col_r2, col_r3 = st.columns(3)
    with col_r1:
        min_m = st.slider("Monthly RSI >=", min_value=50, max_value=75, value=60)
    with col_r2:
        min_w = st.slider("Weekly RSI >=",  min_value=50, max_value=75, value=60)
    with col_r3:
        min_d = st.slider("Daily RSI >=",   min_value=40, max_value=70, value=50)

    st.markdown('<div class="ctrl-section-title">&#128200; Trend, Proximity &amp; Display</div>', unsafe_allow_html=True)
    col_t1, col_t2, col_t3 = st.columns(3)
    with col_t1:
        min_adx = st.slider("ADX Minimum",       min_value=10, max_value=40, value=20)
    with col_t2:
        max_52w = st.slider("Max 52W Distance %", min_value=5,  max_value=25, value=10)
    with col_t3:
        top_n   = st.slider("Top Results",        min_value=5,  max_value=50, value=20)

    st.markdown("<br>", unsafe_allow_html=True)
    run_button = st.button("\U0001f680 Run Full Scan", use_container_width=True, type="primary")


# ─────────────────────────────────────────────
#  Main Content
# ─────────────────────────────────────────────

if run_button:
    status_box     = st.empty()
    prog_container = st.empty()

    with status_box.container():
        st.info("**Step 1/4** — Fetching Nifty 500 constituent symbols...")
    try:
        symbols, source = get_nifty500_symbols()
    except Exception as e:
        status_box.error(f"Error fetching symbols: {e}")
        st.stop()

    with status_box.container():
        st.info(f"**Step 2/4** — Loading 3-year history for **{len(symbols)}** tickers...")
    try:
        data_map = download_prices(symbols)
    except Exception as e:
        status_box.error(f"Error downloading prices: {e}")
        st.stop()

    with status_box.container():
        st.info("**Step 3/4** — Fetching benchmark (Nifty 500 / Nifty 50)...")
    try:
        benchmark = get_benchmark()
    except Exception as e:
        status_box.error(f"Error fetching benchmark: {e}")
        st.stop()

    with status_box.container():
        st.info("**Step 4/4** — Computing indicators & scoring all stocks...")

    rows = []
    with prog_container:
        progress_bar = st.progress(0.0, text="Scanning universe...")
    total_symbols = len(data_map)

    for idx, (sym, d) in enumerate(data_map.items()):
        try:
            row = calculate_metrics(sym, d, benchmark)
            if row:
                rows.append(row)
        except Exception:
            continue
        pct = (idx + 1) / total_symbols
        progress_bar.progress(pct, text=f"Scanning {sym}... ({idx+1}/{total_symbols})")

    prog_container.empty()
    status_box.empty()

    raw = pd.DataFrame(rows)
    if raw.empty:
        st.error("No valid stock data could be calculated.")
    else:
        eligible = raw[
            (raw["Monthly RSI"] >= min_m) &
            (raw["Weekly RSI"]  >= min_w) &
            (raw["Daily RSI"]   >= min_d) &
            (raw["ADX"]         >= min_adx) &
            (raw["52W Distance"] <= max_52w / 100) &
            (raw["Hard Filter"])
        ].copy()

        if eligible.empty:
            st.warning("No stocks passed the filter criteria. Try loosening the thresholds.")
        else:
            scored = score_candidates(eligible)
            if scored.empty:
                st.warning("No stocks passed the Risk/Reward threshold (R:R >= 1.5).")
            else:
                scored.insert(0, "Rank", range(1, len(scored) + 1))

                n_buy       = int((scored["Action"] == "BUY").sum())
                n_watch     = int((scored["Action"] == "WATCH / PULLBACK").sum())
                n_watchlist = int((scored["Action"] == "WATCHLIST").sum())
                top_score   = float(scored["Final Score"].max())
                avg_rr      = float(scored["RR Ratio"].mean())
                total_q     = len(scored)

                st.markdown(f"""
                <div class="kpi-grid">
                    <div class="kpi g"><div class="kpi-ico">&#9989;</div>
                        <div class="kpi-val">{n_buy}</div><div class="kpi-lbl">BUY Signals</div></div>
                    <div class="kpi a"><div class="kpi-ico">&#128064;</div>
                        <div class="kpi-val">{n_watch}</div><div class="kpi-lbl">Watch / Pullback</div></div>
                    <div class="kpi b"><div class="kpi-ico">&#128203;</div>
                        <div class="kpi-val">{n_watchlist}</div><div class="kpi-lbl">Watchlist</div></div>
                    <div class="kpi p"><div class="kpi-ico">&#127942;</div>
                        <div class="kpi-val">{top_score:.0f}</div><div class="kpi-lbl">Top Score</div></div>
                    <div class="kpi a"><div class="kpi-ico">&#9878;&#65039;</div>
                        <div class="kpi-val">{avg_rr:.1f}:1</div><div class="kpi-lbl">Avg R:R</div></div>
                    <div class="kpi g"><div class="kpi-ico">&#128269;</div>
                        <div class="kpi-val">{total_q}</div><div class="kpi-lbl">Total Qualified</div></div>
                </div>
                """, unsafe_allow_html=True)

                display_cols = [
                    "Rank", "Symbol", "Action", "Price",
                    "Final Score", "Momentum Score", "Entry Score",
                    "Monthly RSI", "Weekly RSI", "Daily RSI",
                    "ADX", "Vol Ratio", "RR Ratio", "Risk %",
                    "3M Return", "6M Return", "RS vs Nifty", "52W Distance",
                    "Stop Loss", "Target 2%", "Target 5%",
                ]
                view = scored[display_cols].head(top_n).copy()
                for c in ["3M Return", "6M Return", "RS vs Nifty", "52W Distance"]:
                    view[c] = (view[c] * 100).round(2)

                st.markdown(f"""
                <div class="rbanner">
                    <div>
                        <div class="rb-count">{len(view)} Results</div>
                        <div class="rb-label">Ranked by Final Score &bull; {datetime.now().strftime('%d %b %Y, %H:%M')}</div>
                    </div>
                    <div class="rb-meta">Source: {source} &nbsp;|&nbsp; Benchmark: Nifty 500</div>
                </div>
                """, unsafe_allow_html=True)

                _, col_dl = st.columns([6, 1])
                with col_dl:
                    csv = view.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        label="Export CSV",
                        data=csv,
                        file_name=f"nifty500_scan_{datetime.now().strftime('%Y-%m-%d')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )

                view["Symbol"] = view["Symbol"].apply(
                    lambda s: f"https://in.tradingview.com/chart/?symbol=NSE:{s}"
                )
                styled_view = style_dataframe(view, theme=st.session_state.theme)
                st.dataframe(
                    styled_view,
                    column_config={
                        "Symbol": st.column_config.LinkColumn(
                            "Symbol",
                            help="Click to open chart on TradingView",
                            display_text=r"https://in\.tradingview\.com/chart/\?symbol=NSE:(.*)"
                        )
                    },
                    use_container_width=True,
                    hide_index=True
                )

                st.markdown(f"""
                <div class="legend">
                    <div class="leg-item"><span class="leg-dot" style="background:{T['green']}"></span>
                        <span class="leg-txt">BUY &mdash; Score &ge; 85</span></div>
                    <div class="leg-item"><span class="leg-dot" style="background:{T['amber']}"></span>
                        <span class="leg-txt">WATCH / PULLBACK &mdash; Score &ge; 75</span></div>
                    <div class="leg-item"><span class="leg-dot" style="background:{T['blue']}"></span>
                        <span class="leg-txt">WATCHLIST &mdash; Score &ge; 65</span></div>
                    <div class="leg-item"><span class="leg-dot" style="background:{T['red']}"></span>
                        <span class="leg-txt">AVOID &mdash; Score &lt; 65</span></div>
                    <div class="leg-tip">Click any symbol to open TradingView chart &rarr;</div>
                </div>
                """, unsafe_allow_html=True)

else:
    st.markdown(f"""
    <div class="idle">
        <div class="idle-ico">&#128200;</div>
        <div class="idle-h">Ready to Scan the Market</div>
        <div class="idle-p">
            Expand the <strong style="color:{T['txt']};">Scanner Controls</strong> above,
            tune your filters, then hit <strong style="color:{T['green']};">&#128640; Run Full Scan</strong>
            to identify momentum breakout candidates across the entire Nifty 500 universe.
        </div>
        <div class="idle-steps">
            <div class="step">
                <div class="step-n">01</div><div class="step-t">Set Filters</div>
                <div class="step-d">Tune RSI, ADX &amp; 52W distance thresholds</div>
            </div>
            <div class="step">
                <div class="step-n">02</div><div class="step-t">Run Scan</div>
                <div class="step-d">All 500 stocks analysed in real-time</div>
            </div>
            <div class="step">
                <div class="step-n">03</div><div class="step-t">Review Signals</div>
                <div class="step-d">BUY &bull; WATCH &bull; AVOID action ratings</div>
            </div>
            <div class="step">
                <div class="step-n">04</div><div class="step-t">Open Charts</div>
                <div class="step-d">One-click TradingView deep links</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
