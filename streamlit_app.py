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

from intraday_scanner import (
    PRESET_UNIVERSES,
    download_ticker_data,
    download_intraday_timeframes,
    evaluate_stock_intraday,
    scan_intraday_universe,
    calculate_position_size,
    rsi as intraday_rsi,
    ema as intraday_ema,
    vwap as intraday_vwap,
    atr as intraday_atr,
    volume_ratio as intraday_volume_ratio
)

from options_engine import (
    analyze_option_chain,
    select_strikes,
    price_strategy,
    recommend_strategy,
    run_options_layer,
    generate_payoff_curve,
    fetch_or_simulate_option_chain,
    get_lot_size,
    LOT_SIZES
)

from performance_monitor import (
    backfill_swing_signals,
    evaluate_swing_performance,
    backfill_and_evaluate_intraday,
    evaluate_options_performance,
    load_tracked_signals,
    save_tracked_signals,
    add_tracked_signal,
    evaluate_tracked_signals_performance
)

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
#  Technical indicator helpers (Swing Scanner)
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
#  Caching & data download (Swing Scanner)
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
    for ticker in ["^NSEI", "^CRSLDX"]:
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
#  Scoring helpers (Swing Scanner)
# ─────────────────────────────────────────────

def rsi_score(x, kind):
    if pd.isna(x):
        return 0
    if kind in ("monthly", "weekly"):
        bins = [(60, 65, 10), (65, 70, 12), (70, 75, 15), (75, 80, 12), (80, 101, 8)]
    else:
        bins = [(50, 55, 7), (55, 60, 10), (60, 65, 9), (65, 70, 7), (70, 75, 4), (75, 101, 2)]
    for lo, hi, pts in bins:
        if lo <= x < hi:
            return pts
    return 0

def calc_trend_score(price, e20, e50, e200):
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
    if pd.isna(rs_decimal):
        return 0
    rs = rs_decimal * 100
    if rs > 20:  return 5
    if rs > 10:  return 4
    if rs > 5:   return 3
    if rs > 0:   return 1
    return 0

def calc_price_vs_ema20_score(price, e20):
    if pd.isna(price) or pd.isna(e20) or e20 == 0:
        return 0
    pct_above = (price - e20) / e20 * 100
    if pct_above < 0:    return 0
    if pct_above <= 3:   return 15
    if pct_above <= 8:   return 12
    if pct_above <= 15:  return 8
    return 3

def calc_breakout_pullback_score(price, e20, high52, vol_ratio):
    if any(pd.isna(v) for v in [price, e20, high52, vol_ratio]) or high52 == 0:
        return 3
    dist_from_high = (high52 - price) / high52
    pct_above_ema20 = (price - e20) / e20 if e20 != 0 else 0

    if dist_from_high <= 0.02 and vol_ratio >= 1.5:
        return 15
    if 0 <= pct_above_ema20 <= 0.02:
        return 12
    if price > e20 and vol_ratio >= 1.0:
        return 8
    return 3

def calc_rr_score(rr_ratio):
    if pd.isna(rr_ratio) or rr_ratio <= 0:
        return 0
    if rr_ratio >= 2.5: return 5
    if rr_ratio >= 2.0: return 4
    if rr_ratio >= 1.5: return 3
    if rr_ratio >= 1.0: return 1
    return 0

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

def score_candidates(df):
    out = df.copy()

    out["M RSI Score"] = out["Monthly RSI"].apply(lambda x: rsi_score(x, "monthly"))
    out["W RSI Score"] = out["Weekly RSI"].apply(lambda x: rsi_score(x, "weekly"))
    out["D RSI Score"] = out["Daily RSI"].apply(lambda x: rsi_score(x, "daily"))

    out["Trend Score"] = out.apply(
        lambda r: calc_trend_score(r["Price"], r["EMA20"], r["EMA50"], r["EMA200"]), axis=1
    )

    out["ADX Score"] = out["ADX"].apply(
        lambda x: 0 if x < 20 else 5 if x < 25 else 7 if x < 30 else 10 if x < 40 else 8 if x < 50 else 6
    )

    ret3_rank = out["3M Return"].rank(pct=True)
    out["3M Score"] = ret3_rank.apply(
        lambda p: 10 if p >= 0.90 else 8 if p >= 0.75 else 6 if p >= 0.50 else 4 if p >= 0.25 else 0
    )

    ret6_rank = out["6M Return"].rank(pct=True)
    out["6M Score"] = ret6_rank.apply(
        lambda p: 10 if p >= 0.90 else 8 if p >= 0.75 else 6 if p >= 0.50 else 4 if p >= 0.25 else 0
    )

    out["RS Score"] = out["RS vs Nifty"].apply(calc_rs_score)

    out["Volume Score"] = out["Vol Ratio"].apply(
        lambda x: 0 if x < 1 else 2 if x < 1.2 else 3 if x < 1.5 else 4 if x < 2 else 5
    )

    out["52W Score"] = out["52W Distance"].apply(
        lambda x: 5 if x <= 0.05 else 4 if x <= 0.10 else 2 if x <= 0.15 else 0
    )

    score_cols = [
        "M RSI Score", "W RSI Score", "D RSI Score", "Trend Score", "ADX Score",
        "3M Score", "6M Score", "RS Score", "Volume Score", "52W Score"
    ]
    out["Momentum Score"] = out[score_cols].sum(axis=1).round(1)

    out["Stop Loss"]  = (out["Price"] - 1.5 * out["ATR"]).round(2)
    out["Target 2%"]  = (out["Price"] * 1.02).round(2)
    out["Target 5%"]  = (out["Price"] * 1.05).round(2)
    out["Risk Amt"]   = (out["Price"] - out["Stop Loss"]).clip(lower=0.01)
    out["RR Ratio"]   = ((out["Target 5%"] - out["Price"]) / out["Risk Amt"]).replace(
                            [np.inf, -np.inf], np.nan).round(2)
    out["Risk %"]     = (out["Risk Amt"] / out["Price"] * 100).round(2)

    out = out[out["RR Ratio"] >= 1.5].copy()
    if out.empty:
        return out

    out["Entry RSI Score"] = out["Daily RSI"].apply(
        lambda x: 15 if 55 <= x < 65 else 12 if 50 <= x < 55 else 8 if 65 <= x < 70 else 3
    )

    out["Entry EMA20 Score"] = out.apply(
        lambda r: calc_price_vs_ema20_score(r["Price"], r["EMA20"]), axis=1
    )

    out["Entry BP Score"] = out.apply(
        lambda r: calc_breakout_pullback_score(
            r["Price"], r["EMA20"], r["52W High"], r["Vol Ratio"]
        ), axis=1
    )

    out["Entry Vol Score"] = out["Vol Ratio"].apply(
        lambda x: 10 if x >= 1.5 else 7 if x >= 1.2 else 4
    )

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

    return out.sort_values(["Final Score", "Momentum Score"], ascending=False)


# ─────────────────────────────────────────────
#  DataFrame Styling Helpers
# ─────────────────────────────────────────────

def style_dataframe(df, theme="light"):
    is_light = (theme == "light")
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


def style_intraday_dataframe(df, theme="light"):
    is_light = (theme == "light")
    c_strong_bg = "rgba(22, 163, 74, 0.14)" if is_light else "rgba(0, 255, 136, 0.14)"
    c_strong_txt = "#15803d" if is_light else "#00ff88"
    c_conf_bg = "rgba(13, 148, 136, 0.12)" if is_light else "rgba(45, 212, 191, 0.14)"
    c_conf_txt = "#0f766e" if is_light else "#2dd4bf"
    c_watch_bg = "rgba(217, 119, 6, 0.12)" if is_light else "rgba(255, 184, 0, 0.12)"
    c_watch_txt = "#b45309" if is_light else "#ffb800"
    c_notrade_bg = "rgba(220, 38, 38, 0.08)" if is_light else "rgba(255, 82, 82, 0.10)"
    c_notrade_txt = "#b91c1c" if is_light else "#ff5252"

    c_breakout_bg = "rgba(147, 51, 234, 0.12)" if is_light else "rgba(187, 134, 252, 0.15)"
    c_breakout_txt = "#7e22ce" if is_light else "#bb86fc"
    c_vwap_bg = "rgba(2, 132, 199, 0.12)" if is_light else "rgba(56, 189, 248, 0.15)"
    c_vwap_txt = "#0369a1" if is_light else "#38bdf8"

    def color_signal(val):
        if val == "STRONG BUY CANDIDATE":
            return f"background-color:{c_strong_bg};color:{c_strong_txt};font-weight:700;"
        elif val == "BUY ON CONFIRMATION":
            return f"background-color:{c_conf_bg};color:{c_conf_txt};font-weight:700;"
        elif val == "WATCH":
            return f"background-color:{c_watch_bg};color:{c_watch_txt};font-weight:600;"
        return f"background-color:{c_notrade_bg};color:{c_notrade_txt};font-weight:500;"

    def color_setup(val):
        if val == "BREAKOUT":
            return f"background-color:{c_breakout_bg};color:{c_breakout_txt};font-weight:700;"
        elif val == "VWAP MOMENTUM":
            return f"background-color:{c_vwap_bg};color:{c_vwap_txt};font-weight:600;"
        elif val == "PULLBACK / RECLAIM":
            return f"background-color:{c_conf_bg};color:{c_conf_txt};font-weight:600;"
        return "color:#64748b;" if is_light else "color:#9e9e9e;"

    def color_score(val):
        if pd.isna(val): return ""
        if val >= 85:   return f"color:{c_strong_txt};font-weight:800;"
        elif val >= 75: return f"color:{c_conf_txt};font-weight:700;"
        elif val >= 65: return f"color:{c_watch_txt};font-weight:600;"
        return "color:#64748b;" if is_light else "color:#9e9e9e;"

    styled = df.style \
        .map(color_signal, subset=["Signal"]) \
        .map(color_setup, subset=["Setup"]) \
        .map(color_score, subset=["Score"])

    format_dict = {
        "Price":        "\u20b9{:.2f}",
        "VWAP":         "\u20b9{:.2f}",
        "Stop_Loss":    "\u20b9{:.2f}",
        "Target_1":     "\u20b9{:.2f}",
        "Target_2":     "\u20b9{:.2f}",
        "Score":        "{:.0f}",
        "Daily_RSI":    "{:.1f}",
        "Hourly_RSI":   "{:.1f}",
        "M15_RSI":      "{:.1f}",
        "Volume_Ratio": "{:.2f}x",
        "RR_Ratio":     "{:.2f}:1",
        "Quantity":     "{:d}"
    }
    cols_to_format = {k: v for k, v in format_dict.items() if k in df.columns}
    styled = styled.format(cols_to_format)
    return styled


def style_options_screener_dataframe(df, theme="light"):
    is_light = (theme == "light")
    c_bull_bg   = "rgba(22, 163, 74, 0.14)" if is_light else "rgba(0, 255, 136, 0.14)"
    c_bull_txt  = "#15803d" if is_light else "#00ff88"
    c_bear_bg   = "rgba(220, 38, 38, 0.10)" if is_light else "rgba(255, 82, 82, 0.12)"
    c_bear_txt  = "#b91c1c" if is_light else "#ff5252"
    c_strang_bg = "rgba(147, 51, 234, 0.12)" if is_light else "rgba(187, 134, 252, 0.15)"
    c_strang_txt= "#7e22ce" if is_light else "#bb86fc"

    def color_bias(val):
        v = str(val).upper()
        if "BULL" in v:
            return f"background-color:{c_bull_bg};color:{c_bull_txt};font-weight:700;"
        elif "BEAR" in v:
            return f"background-color:{c_bear_bg};color:{c_bear_txt};font-weight:700;"
        return f"background-color:{c_strang_bg};color:{c_strang_txt};font-weight:700;"

    def color_rec(val):
        v = str(val).upper()
        if "BULL" in v or "CALL" in v:
            return f"background-color:{c_bull_bg};color:{c_bull_txt};font-weight:700;"
        elif "BEAR" in v or "PUT" in v:
            return f"background-color:{c_bear_bg};color:{c_bear_txt};font-weight:700;"
        elif "STRANGLE" in v:
            return f"background-color:{c_strang_bg};color:{c_strang_txt};font-weight:700;"
        return "color:#64748b;" if is_light else "color:#9e9e9e;"

    def color_verdict(val):
        v = str(val).upper()
        if "SUPPORTS TRADE" in v and "PARTIAL" not in v:
            return f"color:{c_bull_txt};font-weight:700;"
        elif "PARTIALLY" in v:
            return "color:#b45309;" if is_light else "color:#ffb800;"
        return "color:#64748b;" if is_light else "color:#9e9e9e;"

    def color_risk_status(val):
        v = str(val).upper()
        if "WITHIN" in v or "PASS" in v or "OK" in v:
            return f"background-color:{c_bull_bg};color:{c_bull_txt};font-weight:600;"
        elif "EXCEED" in v or "OVER" in v:
            return "background-color:rgba(217, 119, 6, 0.12);color:#b45309;font-weight:600;" if is_light else "background-color:rgba(255, 184, 0, 0.12);color:#ffb800;font-weight:600;"
        return "color:#64748b;" if is_light else "color:#9e9e9e;"

    styled = df.style \
        .map(color_rec, subset=["Strategy"]) \
        .map(color_verdict, subset=["Chain_Verdict"])

    if "Bias" in df.columns:
        styled = styled.map(color_bias, subset=["Bias"])

    if "Risk_Status" in df.columns:
        styled = styled.map(color_risk_status, subset=["Risk_Status"])

    format_dict = {
        "Spot":         "\u20b9{:.2f}",
        "MTF_Score":    "{:.0f}",
        "Chain_Score":  "{:.0f}",
        "PCR":          "{:.2f}",
        "ATM_IV":       "{:.1f}%",
        "Net_Premium":  "\u20b9{:.2f}",
        "Max_Loss":     "\u20b9{:.2f}",
        "Max_Profit":   "\u20b9{:.2f}",
        "Breakeven":    "\u20b9{:.2f}",
        "RR_Ratio":     "{:.2f}:1"
    }
    cols_to_format = {k: v for k, v in format_dict.items() if k in df.columns}
    styled = styled.format(cols_to_format)
    return styled


def style_generic_performance_dataframe(df, theme="light"):
    is_light = (theme == "light")
    c_green_bg  = "rgba(22, 163, 74, 0.12)" if is_light else "rgba(0, 255, 136, 0.12)"
    c_green_txt = "#15803d" if is_light else "#00ff88"
    c_red_bg    = "rgba(220, 38, 38, 0.10)" if is_light else "rgba(255, 82, 82, 0.12)"
    c_red_txt   = "#b91c1c" if is_light else "#ff5252"
    c_blue_bg   = "rgba(37, 99, 235, 0.10)" if is_light else "rgba(100, 181, 246, 0.12)"
    c_blue_txt  = "#1d4ed8" if is_light else "#64b5f6"

    def color_outcome(val):
        s_val = str(val)
        if "Target" in s_val or "Profit" in s_val or "Win" in s_val:
            return f"background-color:{c_green_bg};color:{c_green_txt};font-weight:700;"
        elif "Stop" in s_val or "Loss" in s_val or "Fail" in s_val:
            return f"background-color:{c_red_bg};color:{c_red_txt};font-weight:700;"
        else:
            return f"background-color:{c_blue_bg};color:{c_blue_txt};font-weight:600;"

    def color_return(val):
        if pd.isna(val): return ""
        try:
            val_float = float(val)
            color = c_green_txt if val_float >= 0 else c_red_txt
            return f"color:{color};font-weight:600;"
        except Exception:
            return ""

    map_cols_outcome = [c for c in ["Outcome", "Status"] if c in df.columns]
    map_cols_return = [c for c in ["Current Return %", "Max Return %", "Return %", "Max Gain %", "Estimated P&L"] if c in df.columns]
    
    st_df = df.style
    if map_cols_outcome:
        st_df = st_df.map(color_outcome, subset=map_cols_outcome)
    if map_cols_return:
        st_df = st_df.map(color_return, subset=map_cols_return)
        
    fmt_dict = {}
    price_cols = ["Entry Price", "Stop Loss", "Target 1%", "Target 2%", "Target 5%", "Current Price", "Entry Spot", "Current Spot", "Net Premium", "Max Loss", "Max Profit", "Estimated P&L"]
    pct_cols = ["Current Return %", "Max Return %", "Return %", "Max Gain %"]
    
    for c in df.columns:
        if c in price_cols:
            fmt_dict[c] = "₹{:.2f}"
        elif c in pct_cols:
            fmt_dict[c] = "{:+.2f}%"
        elif c == "Score":
            fmt_dict[c] = "{:.1f}"
            
    st_df = st_df.format(fmt_dict)
    return st_df


# ─────────────────────────────────────────────
#  Page Config
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="Nifty Momentum & Options Scanner",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─────────────────────────────────────────────
#  Theme & View State
# ─────────────────────────────────────────────

if "theme" not in st.session_state:
    st.session_state.theme = "light"

if "app_view" not in st.session_state:
    st.session_state.app_view = "Swing Momentum"

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

.block-container, [data-testid="stMainBlockContainer"], .main .block-container {{
    max-width: 1060px !important;
    margin: 0 auto !important;
    padding-top: 1.2rem !important;
    padding-bottom: 3rem !important;
    padding-left: 1.5rem !important;
    padding-right: 1.5rem !important;
}}

.top-nav {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.8rem;
    gap: 1rem;
}}

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

[data-testid="stSidebar"] {{ display:none !important; }}
[data-testid="collapsedControl"] {{ display:none !important; }}

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

.stDownloadButton > button {{
    background:rgba(100,181,246,.07) !important; color:{T['blue']} !important;
    border:1px solid rgba(100,181,246,.28) !important; border-radius:10px !important;
    font-weight:600 !important; transition:all .2s !important;
}}
.stDownloadButton > button:hover {{ background:rgba(100,181,246,.14) !important; }}

.stProgress > div > div {{ background:linear-gradient(90deg,{T['green']},#00b4ff) !important; border-radius:40px !important; }}

[data-testid="stDataFrame"] {{ border:1px solid {T['border']} !important; border-radius:14px !important; overflow:hidden !important; }}
[data-testid="stDataFrame"] thead th {{
    background:{T['th_bg']} !important; color:{T['th_color']} !important;
    font-size:.65rem !important; font-weight:700 !important; text-transform:uppercase !important;
    letter-spacing:.9px !important; border-bottom:1px solid {T['th_border']} !important;
}}
[data-testid="stDataFrame"] tbody td {{ font-family:'JetBrains Mono',monospace !important; font-size:.78rem !important; border-bottom:1px solid {T['df_row_border']} !important; }}

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

.rbanner {{
    background:{T['rbanner_bg']};
    border:1px solid {T['border_hero']}; border-radius:14px;
    padding:1rem 1.5rem; margin-bottom:1.4rem;
    display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:1rem;
}}
.rb-count {{ font-size:1.35rem; font-weight:800; color:{T['green']}; font-family:'JetBrains Mono',monospace; }}
.rb-label {{ font-size:.75rem; color:{T['txt2']}; margin-top:2px; }}
.rb-meta  {{ font-size:.7rem; color:{T['txt3']}; font-family:'JetBrains Mono',monospace; }}

.legend {{ display:flex; gap:2rem; flex-wrap:wrap; align-items:center;
    padding:.85rem 1.4rem; background:{T['legend_bg']};
    border:1px solid {T['legend_border']}; border-radius:12px; margin-top:1.2rem; }}
.leg-item {{ display:flex; align-items:center; gap:7px; }}
.leg-dot  {{ width:8px; height:8px; border-radius:50%; flex-shrink:0; }}
.leg-txt  {{ font-size:.72rem; color:{T['txt2']}; }}
.leg-tip  {{ margin-left:auto; font-size:.68rem; color:{T['txt3']}; font-style:italic; }}

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
[data-testid="stSlider"] label, [data-testid="stNumberInput"] label {{ font-size:.76rem !important; color:{T['txt2']} !important; }}

/* ── Radio Buttons & Mode Selector Styling ── */
div[data-testid="stRadio"] label,
div[data-testid="stRadio"] label p,
div[data-testid="stRadio"] span,
div[data-testid="stRadio"] div,
div[role="radiogroup"] label,
div[role="radiogroup"] label p,
div[role="radiogroup"] span,
div[role="radiogroup"] [data-testid="stMarkdownContainer"] p {{
    color: {T['txt']} !important;
    font-size: 0.95rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.2px !important;
}}

div[role="radiogroup"] {{
    gap: 1.5rem !important;
    align-items: center !important;
}}

div[data-testid="stRadio"] label:hover p,
div[role="radiogroup"] label:hover p {{
    color: {T['green']} !important;
    transition: color 0.2s ease;
}}

/* ── Tabs Styling ── */
button[data-baseweb="tab"] {{
    background: transparent !important;
    border: none !important;
    padding: 0.6rem 1.2rem !important;
}}
button[data-baseweb="tab"] p,
button[data-baseweb="tab"] div,
button[data-baseweb="tab"] span {{
    color: {T['txt2']} !important;
    font-size: 0.95rem !important;
    font-weight: 600 !important;
}}
button[data-baseweb="tab"][aria-selected="true"] p,
button[data-baseweb="tab"][aria-selected="true"] div,
button[data-baseweb="tab"][aria-selected="true"] span {{
    color: {T['green']} !important;
    font-weight: 700 !important;
}}
div[data-baseweb="tab-highlight"] {{
    background-color: {T['green']} !important;
}}

/* ── Widget Labels & Text ── */
label,
label p,
label span,
[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"] label,
[data-testid="stWidgetLabel"] span,
.stSelectbox label p,
.stTextInput label p,
.stTextArea label p,
.stNumberInput label p,
.stSlider label p {{
    color: {T['txt']} !important;
    font-weight: 600 !important;
}}

/* Stock Detail & Strategy Card */
.detail-card {{
    background: {T['bg_card']};
    border: 1px solid {T['border']};
    border-radius: 16px;
    padding: 1.4rem 1.6rem;
    margin-bottom: 1.4rem;
}}
.detail-title {{
    font-size: 1.35rem;
    font-weight: 800;
    color: {T['txt']};
    margin-bottom: 0.4rem;
}}

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
#  Top Nav Bar (View Selector + Theme Switcher)
# ─────────────────────────────────────────────

top_col_view, top_col_btn = st.columns([7.5, 2.5])

MODE_OPTIONS = [
    "🚀 Swing Momentum (D · W · M)",
    "⚡ Intraday MTF (Daily · 1h · 15m)",
    "📊 Performance Monitor"
]

current_mode_idx = 0
if st.session_state.app_view == "Intraday MTF":
    current_mode_idx = 1
elif st.session_state.app_view == "Performance Monitor":
    current_mode_idx = 2
elif st.session_state.app_view == "Options Strategy":
    st.session_state.app_view = "Swing Momentum"
    current_mode_idx = 0

with top_col_view:
    app_view = st.radio(
        "Scanner Mode",
        options=MODE_OPTIONS,
        index=current_mode_idx,
        horizontal=True,
        label_visibility="collapsed"
    )
    if "Swing" in app_view:
        st.session_state.app_view = "Swing Momentum"
    elif "Intraday" in app_view:
        st.session_state.app_view = "Intraday MTF"
    else:
        st.session_state.app_view = "Performance Monitor"

with top_col_btn:
    if st.button(f"{T['toggle_icon']} {T['toggle_label']}", key="theme_toggle", type="secondary", use_container_width=True):
        st.session_state.theme = "light" if st.session_state.theme == "dark" else "dark"
        st.rerun()


now_str = datetime.now().strftime("%d %b %Y, %H:%M IST")


# =============================================================================
#  VIEW 1: SWING MOMENTUM SCANNER (NIFTY 500)
# =============================================================================
if st.session_state.app_view == "Swing Momentum":

    st.markdown(f"""
    <div class="hero">
        <div class="hero-badge"><span class="pulse"></span>Live Scanner &bull; Nifty 500 Swing</div>
        <div class="hero-title">Momentum Scanner</div>
        <div class="hero-sub">Multi-Timeframe RSI &nbsp;&middot;&nbsp; EMA Trend Alignment &nbsp;&middot;&nbsp; ADX Strength &nbsp;&middot;&nbsp; Relative Power vs Nifty &nbsp;&middot;&nbsp; Entry Quality Score</div>
        <div class="hero-meta">
            <div><div class="hm-label">Universe</div><div class="hm-val">Nifty 500</div></div>
            <div><div class="hm-label">Timeframes</div><div class="hm-val">Daily &bull; Weekly &bull; Monthly</div></div>
            <div><div class="hm-label">Benchmark</div><div class="hm-val">Nifty 50 (^NSEI)</div></div>
            <div><div class="hm-label">As of</div><div class="hm-val">{now_str}</div></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    with st.expander("⚙️ Swing Scanner Controls & Filters", expanded=True):
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
        run_button = st.button("🚀 Run Full Swing Scan", use_container_width=True, type="primary")

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
                    st.session_state.swing_results = scored

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
                        <div class="rb-meta">Source: {source} &nbsp;|&nbsp; Benchmark: Nifty 50 (^NSEI)</div>
                    </div>
                    """, unsafe_allow_html=True)

                    _, col_dl = st.columns([6, 1])
                    with col_dl:
                        csv = view.to_csv(index=False).encode("utf-8")
                        st.download_button(
                            label="Export CSV",
                            data=csv,
                            file_name=f"nifty500_swing_scan_{datetime.now().strftime('%Y-%m-%d')}.csv",
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

                    # Manual Track Section
                    st.markdown("---")
                    st.markdown("#### 📌 Track Swing Recommendation")
                    track_col1, track_col2 = st.columns([3, 1])
                    with track_col1:
                        # Extract symbol names from the chart link column
                        qualified_symbols = view["Symbol"].apply(lambda link: link.split("NSE:")[-1]).tolist()
                        symbol_to_track = st.selectbox("Select Symbol to track for Swing Performance", qualified_symbols, key="swing_track_sym_select")
                    with track_col2:
                        st.markdown("<br>", unsafe_allow_html=True)
                        track_btn = st.button("📌 Track Signal", key="swing_track_btn", use_container_width=True)
                        
                    if track_btn and symbol_to_track:
                        sig_row = scored[scored["Symbol"] == symbol_to_track].iloc[0]
                        success, msg = add_tracked_signal(
                            symbol=symbol_to_track,
                            sig_type="Swing",
                            entry_price=sig_row["Price"],
                            stop_loss=sig_row["Stop Loss"],
                            target_2=sig_row["Target 2%"],
                            target_5=sig_row["Target 5%"],
                            score=sig_row["Final Score"],
                            action=sig_row["Action"]
                        )
                        if success:
                            st.success(msg)
                        else:
                            st.warning(msg)

    else:
        st.markdown(f"""
        <div class="idle">
            <div class="idle-ico">&#128200;</div>
            <div class="idle-h">Ready to Scan the Market</div>
            <div class="idle-p">
                Expand the <strong style="color:{T['txt']};">Swing Scanner Controls</strong> above,
                tune your filters, then hit <strong style="color:{T['green']};">&#128640; Run Full Swing Scan</strong>
                to identify momentum breakout setups across all 500 Nifty constituents.
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


# =============================================================================
#  VIEW 2: INTRADAY MULTI-TIMEFRAME (MTF) SCANNER
# =============================================================================
elif st.session_state.app_view == "Intraday MTF":

    st.markdown(f"""
    <div class="hero">
        <div class="hero-badge"><span class="pulse"></span>Live Intraday MTF Engine</div>
        <div class="hero-title">Intraday MTF Scanner</div>
        <div class="hero-sub">Daily Trend Alignment &nbsp;&middot;&nbsp; Hourly Confirmation &nbsp;&middot;&nbsp; 15-Minute VWAP &amp; Breakout Triggers &nbsp;&middot;&nbsp; Dynamic Position Sizing</div>
        <div class="hero-meta">
            <div><div class="hm-label">Alignment</div><div class="hm-val">Daily &rarr; 1h &rarr; 15m</div></div>
            <div><div class="hm-label">Execution</div><div class="hm-val">VWAP &bull; EMA 9/20 &bull; ATR Stop</div></div>
            <div><div class="hm-label">Targets</div><div class="hm-val">+1.0% &bull; +2.0%</div></div>
            <div><div class="hm-label">As of</div><div class="hm-val">{now_str}</div></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    tab_scan, tab_detail = st.tabs(["🔥 Intraday Scanner", "🔍 Stock Deep-Dive & Charts"])

    with tab_scan:
        with st.expander("⚙️ Intraday Scanner Controls & Risk Parameters", expanded=True):
            st.markdown('<div class="ctrl-section-title">&#128394; Stock Universe Selection</div>', unsafe_allow_html=True)
            u_mode = st.radio(
                "Universe Source",
                ["Preset Index/Sector", "Custom Symbols (Comma-separated)", "Top Candidates from Swing Scan"],
                horizontal=True,
                label_visibility="collapsed"
            )

            if u_mode == "Preset Index/Sector":
                preset_name = st.selectbox("Select Preset Universe", list(PRESET_UNIVERSES.keys()))
                universe_symbols = PRESET_UNIVERSES[preset_name]
                st.caption(f"Symbols ({len(universe_symbols)}): {', '.join(universe_symbols)}")
            elif u_mode == "Top Candidates from Swing Scan":
                if "swing_results" in st.session_state and not st.session_state.swing_results.empty:
                    top_swing_syms = st.session_state.swing_results["Symbol"].head(25).tolist()
                    universe_symbols = top_swing_syms
                    st.success(f"Loaded {len(universe_symbols)} high-momentum candidates from your previous Swing scan!")
                else:
                    st.warning("No Swing scan has been run in this session yet. Falling back to Nifty 50 Liquid Top.")
                    universe_symbols = PRESET_UNIVERSES["Nifty 50 Liquid Top"]
            else:
                custom_input = st.text_area(
                    "NSE Symbols (comma-separated)",
                    "NIFTY, RELIANCE, SBIN, ICICIBANK, HDFCBANK, BHARTIARTL, TCS, INFY, LT, TRENT, HAL, BEL, MCX"
                )
                universe_symbols = [s.strip().upper() for s in custom_input.split(",") if s.strip()]

            st.markdown('<div class="ctrl-section-title">&#128202; Technical Filters &amp; Thresholds</div>', unsafe_allow_html=True)
            c_r1, c_r2, c_r3, c_r4 = st.columns(4)
            with c_r1:
                intra_d_rsi = st.number_input("Daily RSI Min", min_value=40, max_value=75, value=55)
            with c_r2:
                intra_h_rsi = st.number_input("Hourly RSI Min", min_value=40, max_value=75, value=55)
            with c_r3:
                intra_m_rsi = st.number_input("15m RSI Min", min_value=40, max_value=70, value=50)
            with c_r4:
                intra_vol_mult = st.number_input("15m Volume Multiplier", min_value=0.5, max_value=4.0, value=1.5, step=0.1)

            st.markdown('<div class="ctrl-section-title">&#128176; Capital &amp; Risk Management (Position Sizing)</div>', unsafe_allow_html=True)
            c_k1, c_k2, c_k3 = st.columns(3)
            with c_k1:
                trade_capital = st.number_input("Trading Capital (₹)", min_value=5000, max_value=50000000, value=100000, step=10000)
            with c_k2:
                risk_pct = st.number_input("Risk per Trade (%)", min_value=0.1, max_value=3.0, value=0.5, step=0.1)
            with c_k3:
                atr_mult = st.number_input("Stop ATR Multiplier", min_value=0.5, max_value=3.0, value=1.5, step=0.1)

            st.markdown("<br>", unsafe_allow_html=True)
            run_intra_button = st.button("⚡ Run Intraday MTF Scan", use_container_width=True, type="primary")

        if run_intra_button:
            if not universe_symbols:
                st.error("Universe is empty. Please enter or select symbols.")
            else:
                prog_box = st.empty()
                with prog_box:
                    prog_bar = st.progress(0.0, text="Fetching Multi-Timeframe Intraday Data...")

                def update_progress(curr, total, symbol):
                    pct = curr / total
                    prog_bar.progress(pct, text=f"Analyzing {symbol} (Daily · 1h · 15m) ... ({curr}/{total})")

                results_df = scan_intraday_universe(
                    symbols=universe_symbols,
                    daily_rsi_min=intra_d_rsi,
                    hourly_rsi_min=intra_h_rsi,
                    m15_rsi_min=intra_m_rsi,
                    volume_multiplier=intra_vol_mult,
                    atr_multiplier=atr_mult,
                    progress_callback=update_progress
                )
                prog_box.empty()

                if results_df.empty:
                    st.warning("No stocks passed the intraday filters or sufficient data is unavailable for selected symbols.")
                else:
                    results_df["Quantity"] = results_df.apply(
                        lambda r: calculate_position_size(trade_capital, risk_pct, r["Price"], r["Stop_Loss"]),
                        axis=1
                    )
                    st.session_state.intraday_results = results_df

                    n_strong = int((results_df["Signal"] == "STRONG BUY CANDIDATE").sum())
                    n_conf   = int((results_df["Signal"] == "BUY ON CONFIRMATION").sum())
                    n_watch  = int((results_df["Signal"] == "WATCH").sum())
                    top_score = float(results_df["Score"].max())
                    avg_rr = float(results_df["RR_Ratio"].mean())
                    total_scanned = len(results_df)

                    st.markdown(f"""
                    <div class="kpi-grid">
                        <div class="kpi g"><div class="kpi-ico">&#9989;</div>
                            <div class="kpi-val">{n_strong}</div><div class="kpi-lbl">Strong Buy</div></div>
                        <div class="kpi a"><div class="kpi-ico">&#9889;</div>
                            <div class="kpi-val">{n_conf}</div><div class="kpi-lbl">Buy Confirmation</div></div>
                        <div class="kpi b"><div class="kpi-ico">&#128064;</div>
                            <div class="kpi-val">{n_watch}</div><div class="kpi-lbl">Watch</div></div>
                        <div class="kpi p"><div class="kpi-ico">&#127942;</div>
                            <div class="kpi-val">{top_score:.0f}</div><div class="kpi-lbl">Top Score</div></div>
                        <div class="kpi a"><div class="kpi-ico">&#9878;&#65039;</div>
                            <div class="kpi-val">{avg_rr:.1f}:1</div><div class="kpi-lbl">Avg R:R</div></div>
                        <div class="kpi g"><div class="kpi-ico">&#128269;</div>
                            <div class="kpi-val">{total_scanned}</div><div class="kpi-lbl">Total Scanned</div></div>
                    </div>
                    """, unsafe_allow_html=True)

                    st.markdown(f"""
                    <div class="rbanner">
                        <div>
                            <div class="rb-count">{len(results_df)} Candidates Evaluated</div>
                            <div class="rb-label">Ranked by Signal &amp; Intraday Score &bull; {datetime.now().strftime('%d %b %Y, %H:%M')}</div>
                        </div>
                        <div class="rb-meta">Risk: {risk_pct}% of ₹{trade_capital:,.0f} (₹{trade_capital*risk_pct/100:,.0f} per trade)</div>
                    </div>
                    """, unsafe_allow_html=True)

                    cols_display = [
                        "Rank", "Symbol", "Signal", "Setup", "Score",
                        "Price", "VWAP", "Daily_RSI", "Hourly_RSI", "M15_RSI",
                        "Volume_Ratio", "Stop_Loss", "Target_1", "Target_2",
                        "RR_Ratio", "Quantity"
                    ]

                    view_intra = results_df[cols_display].copy()

                    _, col_dl = st.columns([6, 1])
                    with col_dl:
                        csv = view_intra.to_csv(index=False).encode("utf-8")
                        st.download_button(
                            label="Export CSV",
                            data=csv,
                            file_name=f"intraday_mtf_signals_{datetime.now().strftime('%Y-%m-%d')}.csv",
                            mime="text/csv",
                            use_container_width=True
                        )

                    view_intra["Symbol"] = view_intra["Symbol"].apply(
                        lambda s: f"https://in.tradingview.com/chart/?symbol=NSE:{s}"
                    )

                    styled_intra = style_intraday_dataframe(view_intra, theme=st.session_state.theme)
                    st.dataframe(
                        styled_intra,
                        column_config={
                            "Symbol": st.column_config.LinkColumn(
                                "Symbol",
                                help="Click to open 15m chart on TradingView",
                                display_text=r"https://in\.tradingview\.com/chart/\?symbol=NSE:(.*)"
                            ),
                            "Signal": st.column_config.TextColumn("Signal", width="medium"),
                            "Setup": st.column_config.TextColumn("Setup", width="small"),
                        },
                        use_container_width=True,
                        hide_index=True
                    )

                    st.markdown(f"""
                    <div class="legend">
                        <div class="leg-item"><span class="leg-dot" style="background:{T['green']}"></span>
                            <span class="leg-txt">STRONG BUY &mdash; Hard Pass &amp; Score &ge; 85</span></div>
                        <div class="leg-item"><span class="leg-dot" style="background:#0f766e"></span>
                            <span class="leg-txt">BUY ON CONFIRMATION &mdash; Hard Pass &amp; Score &ge; 75</span></div>
                        <div class="leg-item"><span class="leg-dot" style="background:{T['amber']}"></span>
                            <span class="leg-txt">WATCH &mdash; Score &ge; 65</span></div>
                        <div class="leg-item"><span class="leg-dot" style="background:{T['purple']}"></span>
                            <span class="leg-txt">Setups: BREAKOUT &bull; VWAP MOMENTUM &bull; PULLBACK / RECLAIM</span></div>
                        <div class="leg-tip">Click any symbol to open TradingView live chart &rarr;</div>
                    </div>
                    """, unsafe_allow_html=True)

                    # Manual Track Section for Active Scan
                    st.markdown("---")
                    st.markdown("#### 📌 Track Intraday Recommendation")
                    track_col1, track_col2 = st.columns([3, 1])
                    with track_col1:
                        qualified_symbols = view_intra["Symbol"].apply(lambda link: link.split("NSE:")[-1]).tolist()
                        symbol_to_track = st.selectbox("Select Symbol to track for Intraday Performance", qualified_symbols, key="intra_active_track_sym_select")
                    with track_col2:
                        st.markdown("<br>", unsafe_allow_html=True)
                        track_btn = st.button("📌 Track Signal", key="intra_active_track_btn", use_container_width=True)
                        
                    if track_btn and symbol_to_track:
                        sig_row = results_df[results_df["Symbol"] == symbol_to_track].iloc[0]
                        success, msg = add_tracked_signal(
                            symbol=symbol_to_track,
                            sig_type="Intraday",
                            entry_price=sig_row["Price"],
                            stop_loss=sig_row["Stop_Loss"],
                            target_1=sig_row["Target_1"],
                            target_2=sig_row["Target_2"],
                            score=sig_row["Score"],
                            action=sig_row["Signal"]
                        )
                        if success:
                            st.success(msg)
                        else:
                            st.warning(msg)

        elif "intraday_results" in st.session_state and not st.session_state.intraday_results.empty:
            res_saved = st.session_state.intraday_results
            st.info("Displaying previously scanned Intraday results. Hit 'Run Intraday MTF Scan' to refresh.")
            cols_display = [
                "Rank", "Symbol", "Signal", "Setup", "Score",
                "Price", "VWAP", "Daily_RSI", "Hourly_RSI", "M15_RSI",
                "Volume_Ratio", "Stop_Loss", "Target_1", "Target_2",
                "RR_Ratio", "Quantity"
            ]
            view_saved = res_saved[cols_display].copy()
            view_saved["Symbol"] = view_saved["Symbol"].apply(
                lambda s: f"https://in.tradingview.com/chart/?symbol=NSE:{s}"
            )
            styled_saved = style_intraday_dataframe(view_saved, theme=st.session_state.theme)
            st.dataframe(
                styled_saved,
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

            # Manual Track Section for Saved Results
            st.markdown("---")
            st.markdown("#### 📌 Track Intraday Recommendation")
            track_col1, track_col2 = st.columns([3, 1])
            with track_col1:
                qualified_symbols = view_saved["Symbol"].apply(lambda link: link.split("NSE:")[-1]).tolist()
                symbol_to_track = st.selectbox("Select Symbol to track for Intraday Performance", qualified_symbols, key="intra_saved_track_sym_select")
            with track_col2:
                st.markdown("<br>", unsafe_allow_html=True)
                track_btn = st.button("📌 Track Signal", key="intra_saved_track_btn", use_container_width=True)
                
            if track_btn and symbol_to_track:
                sig_row = res_saved[res_saved["Symbol"] == symbol_to_track].iloc[0]
                success, msg = add_tracked_signal(
                    symbol=symbol_to_track,
                    sig_type="Intraday",
                    entry_price=sig_row["Price"],
                    stop_loss=sig_row["Stop_Loss"],
                    target_1=sig_row["Target_1"],
                    target_2=sig_row["Target_2"],
                    score=sig_row["Score"],
                    action=sig_row["Signal"]
                )
                if success:
                    st.success(msg)
                else:
                    st.warning(msg)
        else:
            st.markdown(f"""
            <div class="idle">
                <div class="idle-ico">&#9889;</div>
                <div class="idle-h">Intraday MTF Engine Ready</div>
                <div class="idle-p">
                    Select your preferred stock universe (Presets, Custom, or Swing shortlist),
                    tune intraday parameters, and click <strong style="color:{T['green']};">&#9889; Run Intraday MTF Scan</strong>
                    to identify real-time 15m breakout &amp; VWAP momentum triggers.
                </div>
                <div class="idle-steps">
                    <div class="step">
                        <div class="step-n">01</div><div class="step-t">Pick Universe</div>
                        <div class="step-d">Nifty 50, F&amp;O Beta, or custom list</div>
                    </div>
                    <div class="step">
                        <div class="step-n">02</div><div class="step-t">MTF Align</div>
                        <div class="step-d">Daily + Hourly + 15-Minute sync</div>
                    </div>
                    <div class="step">
                        <div class="step-n">03</div><div class="step-t">VWAP Triggers</div>
                        <div class="step-d">Breakout &amp; volume expansion</div>
                    </div>
                    <div class="step">
                        <div class="step-n">04</div><div class="step-t">Risk Sizing</div>
                        <div class="step-d">Auto ATR stop &amp; position size</div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

    # ── Intraday Stock Deep-Dive Tab ──
    with tab_detail:
        available_syms = universe_symbols if 'universe_symbols' in locals() and universe_symbols else PRESET_UNIVERSES["Nifty 50 Liquid Top"]
        selected_stock = st.selectbox("Select Stock for Deep-Dive Analysis", available_syms)

        col_d_act, col_d_opt = st.columns([2, 2])
        with col_d_act:
            analyze_btn = st.button("📊 Analyze Stock Details", type="primary", use_container_width=True)

        if analyze_btn or selected_stock:
            with st.spinner(f"Fetching real-time multi-timeframe data for {selected_stock}..."):
                d_df, h_df, m_df = download_intraday_timeframes(selected_stock)

            if min(len(d_df), len(h_df), len(m_df)) < 30:
                st.error(f"Insufficient historical or intraday data available for {selected_stock}.NS")
            else:
                stock_sig = evaluate_stock_intraday(
                    selected_stock,
                    daily_rsi_min=intra_d_rsi if 'intra_d_rsi' in locals() else 55,
                    hourly_rsi_min=intra_h_rsi if 'intra_h_rsi' in locals() else 55,
                    m15_rsi_min=intra_m_rsi if 'intra_m_rsi' in locals() else 50,
                    volume_multiplier=intra_vol_mult if 'intra_vol_mult' in locals() else 1.5,
                    atr_multiplier=atr_mult if 'atr_mult' in locals() else 1.5,
                    d_df=d_df, h_df=h_df, m_df=m_df
                )

                if stock_sig:
                    mc1, mc2, mc3, mc4, mc5 = st.columns(5)
                    mc1.metric("Intraday Score", f"{stock_sig['Score']:.0f}/100")
                    mc2.metric("Signal", stock_sig["Signal"])
                    mc3.metric("Setup", stock_sig["Setup"])
                    mc4.metric("Current Price", f"₹{stock_sig['Price']:.2f}")
                    mc5.metric("Intraday VWAP", f"₹{stock_sig['VWAP']:.2f}")

                    rc1, rc2, rc3, rc4 = st.columns(4)
                    rc1.metric("Daily RSI", f"{stock_sig['Daily_RSI']:.1f}", "Trend: " + ("Bullish" if stock_sig["Daily_Trend"] else "Neutral"))
                    rc2.metric("Hourly RSI", f"{stock_sig['Hourly_RSI']:.1f}", "Trend: " + ("Bullish" if stock_sig["Hourly_Trend"] else "Neutral"))
                    rc3.metric("15m RSI", f"{stock_sig['M15_RSI']:.1f}", "Trend: " + ("Bullish" if stock_sig["M15_Trend"] else "Neutral"))
                    rc4.metric("15m Vol Ratio", f"{stock_sig['Volume_Ratio']:.2f}x")

                    c_cap = trade_capital if 'trade_capital' in locals() else 100000
                    c_risk = risk_pct if 'risk_pct' in locals() else 0.5
                    pos_qty = calculate_position_size(c_cap, c_risk, stock_sig["Price"], stock_sig["Stop_Loss"])
                    max_loss = pos_qty * (stock_sig["Price"] - stock_sig["Stop_Loss"])
                    total_exposure = pos_qty * stock_sig["Price"]

                    st.markdown(f"""
                    <div class="detail-card">
                        <div class="detail-title">🛡️ Risk &amp; Execution Plan &mdash; {selected_stock}</div>
                        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(130px, 1fr)); gap:1rem; margin-top:0.8rem;">
                            <div><div class="hm-label">Stop Loss</div><div class="hm-val" style="color:{T['red']};">₹{stock_sig['Stop_Loss']:.2f}</div></div>
                            <div><div class="hm-label">Target 1 (+1%)</div><div class="hm-val" style="color:{T['green']};">₹{stock_sig['Target_1']:.2f}</div></div>
                            <div><div class="hm-label">Target 2 (+2%)</div><div class="hm-val" style="color:{T['green']};">₹{stock_sig['Target_2']:.2f}</div></div>
                            <div><div class="hm-label">R:R Ratio</div><div class="hm-val">{stock_sig['RR_Ratio']:.2f}:1</div></div>
                            <div><div class="hm-label">Suggested Qty</div><div class="hm-val" style="color:{T['blue']}; font-size:1.1rem;">{pos_qty} shares</div></div>
                            <div><div class="hm-label">Capital at Risk</div><div class="hm-val">₹{max_loss:,.2f}</div></div>
                            <div><div class="hm-label">Total Trade Value</div><div class="hm-val">₹{total_exposure:,.2f}</div></div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    col_track, _ = st.columns([2, 2])
                    with col_track:
                        track_intra_btn = st.button(f"📌 Track {selected_stock} for Intraday Performance", key="track_intra_signal_btn", use_container_width=True, type="secondary")
                    
                    if track_intra_btn:
                        success, msg = add_tracked_signal(
                            symbol=selected_stock,
                            sig_type="Intraday",
                            entry_price=stock_sig["Price"],
                            stop_loss=stock_sig["Stop_Loss"],
                            target_1=stock_sig["Target_1"],
                            target_2=stock_sig["Target_2"],
                            score=stock_sig["Score"],
                            action=stock_sig["Signal"]
                        )
                        if success:
                            st.success(msg)
                        else:
                            st.warning(msg)

                    st.markdown(f"#### 📈 15-Minute Price Action vs VWAP ({selected_stock})")
                    m_recent = m_df.tail(75).copy()
                    m_recent["VWAP"] = intraday_vwap(m_recent)
                    m_recent["EMA9"] = intraday_ema(m_recent["Close"], 9)
                    m_recent["EMA20"] = intraday_ema(m_recent["Close"], 20)

                    chart_data = m_recent[["Close", "VWAP", "EMA9", "EMA20"]]
                    st.line_chart(chart_data)

                    st.markdown(f"[🔗 Open Full Interactive Chart on TradingView](https://in.tradingview.com/chart/?symbol=NSE:{selected_stock})")


# =============================================================================
#  VIEW 3: OPTIONS CHAIN STRATEGY LAYER
# =============================================================================
elif st.session_state.app_view == "Options Strategy":

    st.markdown(f"""
    <div class="hero">
        <div class="hero-badge"><span class="pulse"></span>Live Options Strategy Engine</div>
        <div class="hero-title">Options Chain Strategy</div>
        <div class="hero-sub">Multi-Timeframe Gated Options &nbsp;&middot;&nbsp; Put-Call Ratio &amp; OI Analytics &nbsp;&middot;&nbsp; Spreads &amp; Strangles &nbsp;&middot;&nbsp; Payoff Simulation</div>
        <div class="hero-meta">
            <div><div class="hm-label">Architecture</div><div class="hm-val">MTF &rarr; Chain Gate &rarr; Payoff</div></div>
            <div><div class="hm-label">Strategies</div><div class="hm-val">Bull Call &bull; Bear Put &bull; Strangle</div></div>
            <div><div class="hm-label">Risk Gate</div><div class="hm-val">Max Loss &le; Risk Budget</div></div>
            <div><div class="hm-label">As of</div><div class="hm-val">{now_str}</div></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    tab_opt_screen, tab_opt_chain = st.tabs([
        "⚡ Options Strategy Screener",
        "📊 Option Chain Matrix Table"
    ])

    # ── TAB 1: Options Strategy Screener ──
    with tab_opt_screen:
        st.markdown("#### ⚡ Real-Time Multi-Asset Options Strategy Screener")
        st.caption("Screens F&O constituents against MTF Momentum + Option Chain Quality gates.")

        st.markdown('<div class="ctrl-section-title">&#128394; Options Universe Selection</div>', unsafe_allow_html=True)
        opt_u_mode = st.radio(
            "Options Universe Mode",
            ["Preset Index/Sector", "Top Candidates from Intraday Scan", "Top Candidates from Swing Scan", "Custom Symbols"],
            horizontal=True,
            label_visibility="collapsed",
            key="opt_screener_u_mode"
        )

        # Options-specific preset universes (stocks + indices)
        OPT_PRESET_UNIVERSES = {
            "NSE Indices (NIFTY / BANKNIFTY / FINNIFTY)": ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"],
            "Nifty 50 Liquid Top": [
                "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "ITC", "BHARTIARTL",
                "LT", "SBIN", "AXISBANK", "KOTAKBANK", "HINDUNILVR", "M&M", "TATAMOTORS",
                "BAJFINANCE", "MARUTI", "SUNPHARMA", "NTPC", "POWERGRID", "TITAN"
            ],
            **{k: v for k, v in PRESET_UNIVERSES.items() if k != "Nifty 50 Liquid Top"},
        }

        if opt_u_mode == "Preset Index/Sector":
            opt_preset_name = st.selectbox(
                "Select Preset Universe",
                list(OPT_PRESET_UNIVERSES.keys()),
                index=0,
                key="opt_screener_preset_choice"
            )
            screen_universe = OPT_PRESET_UNIVERSES[opt_preset_name]
            st.caption(f"Symbols ({len(screen_universe)}): {', '.join(screen_universe)}")
        elif opt_u_mode == "Top Candidates from Intraday Scan":
            if "intraday_results" in st.session_state and not st.session_state.intraday_results.empty:
                top_intra_syms = st.session_state.intraday_results["Symbol"].head(20).tolist()
                screen_universe = top_intra_syms
                st.success(f"Loaded {len(screen_universe)} candidates from your previous Intraday scan!")
            else:
                st.warning("No Intraday scan results in this session yet. Falling back to Nifty 50 Liquid Top (20 Stocks).")
                screen_universe = PRESET_UNIVERSES["Nifty 50 Liquid Top"]
        elif opt_u_mode == "Top Candidates from Swing Scan":
            if "swing_results" in st.session_state and not st.session_state.swing_results.empty:
                top_swing_syms = st.session_state.swing_results["Symbol"].head(20).tolist()
                screen_universe = top_swing_syms
                st.success(f"Loaded {len(screen_universe)} candidates from your previous Swing scan!")
            else:
                st.warning("No Swing scan results in this session yet. Falling back to Nifty 50 Liquid Top (20 Stocks).")
                screen_universe = PRESET_UNIVERSES["Nifty 50 Liquid Top"]
        else:
            custom_opt_input = st.text_area(
                "F&O Symbols (comma-separated)",
                "NIFTY, RELIANCE, HDFCBANK, ICICIBANK, INFY, TCS, BHARTIARTL, LT, SBIN, TRENT, HAL, BEL, MCX",
                key="custom_opt_universe"
            )
            screen_universe = [s.strip().upper() for s in custom_opt_input.split(",") if s.strip()]

        st.markdown('<div class="ctrl-section-title">&#128176; Screener Capital &amp; Risk Parameters</div>', unsafe_allow_html=True)
        col_s1, col_s2 = st.columns([1, 1])
        with col_s1:
            screen_capital = st.number_input("Screener Capital (₹)", value=200000, step=25000, key="scr_cap")
        with col_s2:
            screen_risk_pct = st.slider("Risk % per Trade", min_value=0.5, max_value=5.0, value=2.0, step=0.5, key="scr_risk")

        st.markdown("<br>", unsafe_allow_html=True)
        run_screener_btn = st.button("🚀 Screen Options Universe", type="primary", use_container_width=True)

        if run_screener_btn and screen_universe:
            screen_rows = []
            screen_results_map = {}
            scr_prog = st.progress(0.0, text="Evaluating Options Strategies...")

            for i, sym in enumerate(screen_universe):
                try:
                    # 1. Multi-Timeframe Technical & Momentum Evaluation
                    # Map NSE index symbols to yfinance tickers for spot price
                    _INDEX_YF_MAP = {
                        "NIFTY": "^NSEI",
                        "BANKNIFTY": "^NSEBANK",
                        "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
                        "MIDCPNIFTY": "^CNXMIDCAP",
                        "SENSEX": "^BSESN",
                    }
                    _is_index = sym in _INDEX_YF_MAP
                    d_df, h_df, m_df = download_intraday_timeframes(_INDEX_YF_MAP.get(sym, sym))
                    intra_eval = evaluate_stock_intraday(_INDEX_YF_MAP.get(sym, sym), d_df=d_df, h_df=h_df, m_df=m_df)

                    if intra_eval and intra_eval.get("Score") is not None and intra_eval.get("Price") is not None:
                        sp = float(intra_eval["Price"])
                        real_mtf_score = float(intra_eval["Score"])
                        d_rsi_val = float(intra_eval["Daily_RSI"])
                        h_rsi_val = float(intra_eval["Hourly_RSI"])
                        m_rsi_val = float(intra_eval["M15_RSI"])
                        d_tr = intra_eval["Daily_Trend"]
                        h_tr = intra_eval["Hourly_Trend"]
                        vwap_val = float(intra_eval["VWAP"])

                        if (d_rsi_val >= 50 and h_rsi_val >= 50 and sp >= vwap_val) or (d_tr and h_tr):
                            tech_dir = "BULLISH"
                        elif (d_rsi_val < 48 and h_rsi_val < 48 and sp < vwap_val) or (not d_tr and not h_tr):
                            tech_dir = "BEARISH"
                        else:
                            tech_dir = "NEUTRAL"
                    else:
                        yf_sym = _INDEX_YF_MAP.get(sym, sym)
                        raw_d = download_ticker_data(yf_sym, "60d", "1d")
                        sp = float(raw_d["Close"].iloc[-1]) if not raw_d.empty else 1000.0
                        c = raw_d["Close"]
                        e20 = float(ema(c, 20).iloc[-1])
                        e50 = float(ema(c, 50).iloc[-1]) if len(c) >= 50 else e20 * 0.98
                        r_val = float(rsi(c).iloc[-1])
                        if sp > e20 > e50 and r_val >= 50:
                            tech_dir = "BULLISH"
                            real_mtf_score = min(max(r_val * 1.25, 60.0), 95.0)
                        elif sp < e20 < e50 and r_val <= 45:
                            tech_dir = "BEARISH"
                            real_mtf_score = min(max((100 - r_val) * 1.25, 60.0), 95.0)
                        else:
                            tech_dir = "NEUTRAL"
                            real_mtf_score = 65.0

                    # 2. Option Chain Analytics & OI Bias
                    chain = fetch_or_simulate_option_chain(sym, sp)
                    lot = get_lot_size(sym)
                    ca = analyze_option_chain(chain, sp, tech_dir)
                    pcr_val = ca.get("pcr", 1.0)
                    c_side = chain[chain.option_type == "CE"]
                    p_side = chain[chain.option_type == "PE"]
                    p_chg = p_side["change_oi"].sum()
                    c_chg = c_side["change_oi"].sum()

                    if p_chg > c_chg and pcr_val >= 0.95:
                        oi_dir = "BULLISH"
                    elif c_chg > p_chg and pcr_val <= 0.90:
                        oi_dir = "BEARISH"
                    else:
                        oi_dir = "NEUTRAL"

                    # 3. Composite BIAS (MTF Momentum + OI Flow)
                    if tech_dir == "BULLISH" and oi_dir in ("BULLISH", "NEUTRAL"):
                        composite_bias = "BULLISH"
                    elif tech_dir == "BEARISH" and oi_dir in ("BEARISH", "NEUTRAL"):
                        composite_bias = "BEARISH"
                    elif oi_dir == "BULLISH" and tech_dir == "NEUTRAL":
                        composite_bias = "BULLISH"
                    elif oi_dir == "BEARISH" and tech_dir == "NEUTRAL":
                        composite_bias = "BEARISH"
                    else:
                        composite_bias = "NEUTRAL"

                    # 4. Strategy Evaluation
                    res = run_options_layer(
                        chain, sp, mtf_score=real_mtf_score, direction=composite_bias,
                        capital=screen_capital, lot_size=lot, max_risk_pct=screen_risk_pct,
                        prefer_spreads=True, enforce_risk_budget=False
                    )
                    rc = res["recommendation"]
                    po = res.get("payoff", {})
                    strat = res.get("strategy", "NO TRADE")
                    risk_ok = res.get("risk_gate_passed", False)

                    if strat != "NO TRADE" and po:
                        status_str = "✅ Within Budget" if risk_ok else f"⚠️ Exceeds Budget (Need ₹{po['max_loss']:,.0f})"
                    else:
                        status_str = "⛔ Chain Gated"

                    screen_rows.append({
                        "Symbol": sym,
                        "Expiry": ca.get("expiry", "—"),
                        "Spot": sp,
                        "Bias": composite_bias,
                        "MTF_Score": real_mtf_score,
                        "Chain_Score": ca.get("chain_score", 0),
                        "Chain_Verdict": ca.get("verdict", "NO TRADE"),
                        "Strategy": strat,
                        "Risk_Status": status_str,
                        "PCR": ca.get("pcr", np.nan),
                        "ATM_IV": ca.get("avg_atm_iv", np.nan),
                        "Net_Premium": po.get("net_premium", np.nan) if po else np.nan,
                        "Max_Loss": po.get("max_loss", np.nan) if po else np.nan,
                        "Max_Profit": po.get("max_profit", np.nan) if po else np.nan,
                        "Breakeven": po.get("breakeven", np.nan) if po else np.nan,
                        "RR_Ratio": po.get("risk_reward", np.nan) if po else np.nan,
                    })

                    screen_results_map[sym] = {
                        "sym": sym, "sp": sp, "bias": composite_bias,
                        "mtf_score": real_mtf_score, "ca": ca, "res": res,
                        "lot": lot, "capital": screen_capital, "risk_pct": screen_risk_pct
                    }
                except Exception:
                    pass
                scr_prog.progress((i + 1) / len(screen_universe), text=f"Screening {sym}...")

            scr_prog.empty()

            if screen_rows:
                st.session_state.options_screen_rows = screen_rows
                st.session_state.options_screen_map = screen_results_map

        # Render Screener Table & In-Page Strategy Inspector
        if "options_screen_rows" in st.session_state and st.session_state.options_screen_rows:
            s_rows = st.session_state.options_screen_rows
            s_map = st.session_state.options_screen_map

            scr_df = pd.DataFrame(s_rows)

            # ── Render results table with row-click selection ──
            st.caption("👆 Click any row to open that stock's Strategy Deep-Dive below.")
            tbl_selection = st.dataframe(
                style_options_screener_dataframe(scr_df.copy(), theme=st.session_state.theme),
                use_container_width=True,
                hide_index=True,
                selection_mode="single-row",
                on_select="rerun",
                key="scr_table_selection"
            )

            # Sync clicked row → inspector
            all_screened_syms = [r["Symbol"] for r in s_rows]
            selected_rows = tbl_selection.selection.get("rows", []) if tbl_selection and hasattr(tbl_selection, "selection") else []
            if selected_rows:
                clicked_sym = all_screened_syms[selected_rows[0]]
                st.session_state.chosen_inspect_sym_box = clicked_sym

            # Initialise default selection
            if "chosen_inspect_sym_box" not in st.session_state or st.session_state.chosen_inspect_sym_box not in all_screened_syms:
                st.session_state.chosen_inspect_sym_box = all_screened_syms[0]

            # ── In-Page Strategy Inspector & Payoff Viewer ──
            st.markdown("---")
            st.markdown("### 🔎 Strategy Deep-Dive & Payoff Inspector")
            st.caption("Click any row in the table above — or use the dropdown — to inspect strategy, legs, payoff diagram and chain diagnostics.")

            insp_col1, insp_col2 = st.columns([2, 2])
            with insp_col1:
                chosen_inspect_sym = st.selectbox(
                    "🔍 Selected Stock",
                    all_screened_syms,
                    index=all_screened_syms.index(st.session_state.chosen_inspect_sym_box),
                    key="chosen_inspect_sym_box"
                )
            with insp_col2:
                # Indices use a different TradingView symbol format
                _TV_INDEX_MAP = {
                    "NIFTY": "NSE:NIFTY50", "BANKNIFTY": "NSE:BANKNIFTY",
                    "FINNIFTY": "NSE:FINNIFTY", "MIDCPNIFTY": "NSE:MIDCPNIFTY",
                }
                tv_sym = _TV_INDEX_MAP.get(chosen_inspect_sym, f"NSE:{chosen_inspect_sym}")
                tv_link = f"https://in.tradingview.com/chart/?symbol={tv_sym}"
                st.markdown(f"<br><a href='{tv_link}' target='_blank' style='color:#38bdf8;font-size:0.9rem;'>🔗 Open {chosen_inspect_sym} on TradingView →</a>", unsafe_allow_html=True)

            if chosen_inspect_sym and chosen_inspect_sym in s_map:
                item = s_map[chosen_inspect_sym]
                opt_res = item["res"]
                sp_val = item["sp"]
                ca_val = item["ca"]
                rec_val = opt_res.get("recommendation", {})
                payoff_val = opt_res.get("payoff", {})
                legs_val = opt_res.get("legs", {})
                strat_name = opt_res.get("strategy", "NO TRADE")
                lot_val = item["lot"]
                cap_val = item["capital"]
                r_pct = item["risk_pct"]
                r_budget = cap_val * (r_pct / 100.0)

                # 6 Top Metric Cards
                im1, im2, im3, im4, im5, im6 = st.columns(6)
                im1.metric("Underlying Spot", f"₹{sp_val:.2f}")
                im2.metric("Bias", item["bias"])
                im3.metric("MTF Score", f"{item['mtf_score']:.0f}/100")
                im4.metric("Chain Score", f"{ca_val.get('chain_score', 0):.0f}/100")
                im5.metric("Chain Verdict", ca_val.get("verdict", "NO TRADE"))
                im6.metric("Strategy", strat_name)

                if strat_name != "NO TRADE" and payoff_val and legs_val:
                    st_clean = strat_name.replace("_", " ")

                    if not opt_res.get("risk_gate_passed", True):
                        st.warning(f"⚠️ **Risk Budget Notice**: 1-Lot Max Loss (₹{payoff_val['max_loss']:,.2f}) exceeds your ₹{r_budget:,.2f} risk budget ({r_pct}% of ₹{cap_val:,.0f}). Set Risk % to ≥ {(payoff_val['max_loss']/cap_val*100):.1f}% or increase capital to trade.")

                    st.markdown(f"""
                    <div class="detail-card">
                        <div class="detail-title">🏆 Strategy Execution Plan &mdash; {st_clean} ({chosen_inspect_sym})</div>
                        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(130px, 1fr)); gap:1rem; margin-top:0.8rem;">
                            <div><div class="hm-label">Net Premium</div><div class="hm-val" style="color:{T['blue']};">₹{payoff_val['net_premium']:.2f}</div></div>
                            <div><div class="hm-label">Max Loss (1 Lot)</div><div class="hm-val" style="color:{T['red']};">₹{payoff_val['max_loss']:,.2f}</div></div>
                            <div><div class="hm-label">Max Profit</div><div class="hm-val" style="color:{T['green']};">{'₹' + f"{payoff_val['max_profit']:,.2f}" if payoff_val['max_profit'] != float('inf') else 'Unlimited'}</div></div>
                            <div><div class="hm-label">Breakeven</div><div class="hm-val">₹{payoff_val['breakeven']:,.2f}</div></div>
                            <div><div class="hm-label">Risk / Reward</div><div class="hm-val">{f"{payoff_val['risk_reward']:.2f}:1" if pd.notna(payoff_val['risk_reward']) else 'N/A'}</div></div>
                            <div><div class="hm-label">Lot Size</div><div class="hm-val">{lot_val} shares</div></div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    # Selected Legs Table
                    st.markdown(f"#### 📑 Strategy Legs ({st_clean})")
                    leg_rows = []
                    if "buy" in legs_val:
                        leg_rows.append({
                            "Action": "BUY (Long)",
                            "Option": f"{legs_val['buy'].strike:.0f} {legs_val['buy'].option_type}",
                            "LTP": f"₹{legs_val['buy'].ltp:.2f}",
                            "Bid / Ask": f"₹{legs_val['buy'].bid:.2f} / ₹{legs_val['buy'].ask:.2f}",
                            "IV": f"{legs_val['buy'].iv:.1f}%",
                            "OI": f"{legs_val['buy'].oi:,}",
                            "Expiry": str(legs_val['buy'].expiry)
                        })
                    if "sell" in legs_val:
                        leg_rows.append({
                            "Action": "SELL (Short)",
                            "Option": f"{legs_val['sell'].strike:.0f} {legs_val['sell'].option_type}",
                            "LTP": f"₹{legs_val['sell'].ltp:.2f}",
                            "Bid / Ask": f"₹{legs_val['sell'].bid:.2f} / ₹{legs_val['sell'].ask:.2f}",
                            "IV": f"{legs_val['sell'].iv:.1f}%",
                            "OI": f"{legs_val['sell'].oi:,}",
                            "Expiry": str(legs_val['sell'].expiry)
                        })
                    if "call" in legs_val and "put" in legs_val:
                        leg_rows.append({
                            "Action": "BUY CALL",
                            "Option": f"{legs_val['call'].strike:.0f} CE",
                            "LTP": f"₹{legs_val['call'].ltp:.2f}",
                            "Bid / Ask": f"₹{legs_val['call'].bid:.2f} / ₹{legs_val['call'].ask:.2f}",
                            "IV": f"{legs_val['call'].iv:.1f}%",
                            "OI": f"{legs_val['call'].oi:,}",
                            "Expiry": str(legs_val['call'].expiry)
                        })
                        leg_rows.append({
                            "Action": "BUY PUT",
                            "Option": f"{legs_val['put'].strike:.0f} PE",
                            "LTP": f"₹{legs_val['put'].ltp:.2f}",
                            "Bid / Ask": f"₹{legs_val['put'].bid:.2f} / ₹{legs_val['put'].ask:.2f}",
                            "IV": f"{legs_val['put'].iv:.1f}%",
                            "OI": f"{legs_val['put'].oi:,}",
                            "Expiry": str(legs_val['put'].expiry)
                        })

                    st.dataframe(pd.DataFrame(leg_rows), use_container_width=True, hide_index=True)

                    # Payoff Curve Diagram
                    st.markdown(f"#### 📊 Interactive Payoff Diagram at Expiry ({chosen_inspect_sym})")
                    curve = generate_payoff_curve(strat_name, legs_val, sp_val, lot_size=lot_val)
                    if not curve.empty:
                        st.line_chart(curve.set_index("Spot_at_Expiry")[["PnL"]])
                else:
                    st.info(f"Strategy Gated for {chosen_inspect_sym}: {ca_val.get('verdict', 'Option Chain requirements not met')}")

                # Diagnostics checklist
                with st.expander(f"🔍 Option Chain Diagnostics Checklist &mdash; {chosen_inspect_sym}", expanded=False):
                    for r in ca_val.get("reasons", []):
                        st.markdown(f"- ✅ {r}")

    # ── TAB 2: Option Chain Matrix Table ──
    with tab_opt_chain:
        matrix_sym_choices = PRESET_UNIVERSES["Nifty 50 Liquid Top"] + ["NIFTY", "BANKNIFTY"]
        mat_col1, mat_col2 = st.columns([3, 1])
        with mat_col1:
            matrix_symbol = st.selectbox("Select Underlying for Option Chain Matrix", matrix_sym_choices, index=0, key="opt_matrix_symbol_choice")
        with mat_col2:
            st.markdown("<br>", unsafe_allow_html=True)
            load_matrix_btn = st.button("📊 Refresh Matrix", type="secondary", use_container_width=True)

        with st.spinner(f"Loading Option Chain Matrix for {matrix_symbol}..."):
            raw_mat_d = download_ticker_data(matrix_symbol, "5d", "1d")
            sp_mat = float(raw_mat_d["Close"].iloc[-1]) if not raw_mat_d.empty else 1300.0
            mat_chain_df = fetch_or_simulate_option_chain(matrix_symbol, sp_mat)

        if not mat_chain_df.empty:
            chain_disp = mat_chain_df.copy()
            c_side = chain_disp[chain_disp.option_type == "CE"].set_index("strike")
            p_side = chain_disp[chain_disp.option_type == "PE"].set_index("strike")

            combined_matrix = pd.DataFrame({
                "Call OI": c_side["oi"],
                "Call Chg OI": c_side["change_oi"],
                "Call Vol": c_side["volume"],
                "Call IV": c_side["iv"],
                "Call LTP": c_side["ltp"],
                "Put LTP": p_side["ltp"],
                "Put IV": p_side["iv"],
                "Put Vol": p_side["volume"],
                "Put Chg OI": p_side["change_oi"],
                "Put OI": p_side["oi"],
            }).dropna(subset=["Call LTP", "Put LTP"]).sort_index()

            st.markdown(f"**Spot Price**: ₹{sp_mat:.2f} &bull; **ATM Strike**: ₹{round(sp_mat / (50 if sp_mat > 2000 else 20)) * (50 if sp_mat > 2000 else 20):.0f}")

            st.dataframe(
                combined_matrix.style.format({
                    "Call LTP": "₹{:.2f}", "Put LTP": "₹{:.2f}",
                    "Call IV": "{:.1f}%", "Put IV": "{:.1f}%",
                    "Call OI": "{:,.0f}", "Put OI": "{:,.0f}",
                    "Call Vol": "{:,.0f}", "Put Vol": "{:,.0f}",
                    "Call Chg OI": "{:+,.0f}", "Put Chg OI": "{:+,.0f}"
                }),
                use_container_width=True
            )


# =============================================================================
#  VIEW 4: PERFORMANCE MONITOR
# =============================================================================
elif st.session_state.app_view == "Performance Monitor":

    st.markdown(f"""
    <div class="hero">
        <div class="hero-badge"><span class="pulse"></span>System Analytics</div>
        <div class="hero-title">Signal Performance Tracker</div>
        <div class="hero-sub">Track recommendation performance, win rates, hit counts, and outcomes.</div>
        <div class="hero-meta">
            <div><div class="hm-label">Tracked Timeframe</div><div class="hm-val">Last 7 Trading Days</div></div>
            <div><div class="hm-label">Screener Cache</div><div class="hm-val">Local Parquet &amp; JSON</div></div>
            <div><div class="hm-label">Metrics Engine</div><div class="hm-val">Auto-Evaluator</div></div>
            <div><div class="hm-label">As of</div><div class="hm-val">{now_str}</div></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    perf_tab_swing, perf_tab_intra_opt, perf_tab_manual = st.tabs([
        "🚀 Swing Signals (Auto)",
        "⚡ Intraday & Options (Auto)",
        "📌 Tracked Watchlist (Manual)"
    ])

    # ── TAB 1: Swing Signals Performance ──
    with perf_tab_swing:
        st.markdown("#### 🚀 Swing Signals Performance Report")
        st.caption("Evaluates signals generated over the last 7 trading days and tracks their outcomes.")

        run_backfill_btn = st.button("🚀 Run Swing Signal Backfill & Performance Check", type="primary", use_container_width=True)

        if run_backfill_btn:
            status_placeholder = st.empty()
            with status_placeholder.container():
                st.info("Loading Nifty 500 price data and running performance evaluator...")

            try:
                symbols, _ = get_nifty500_symbols()
                benchmark = get_benchmark()
                data_map = download_prices(symbols)
                
                # Fetch cached/new signals for last 7 trading days
                signals = backfill_swing_signals(data_map, benchmark, days=7)
                
                if not signals:
                    status_placeholder.warning("No Swing buy/watch recommendations generated in the last 7 trading days.")
                else:
                    df_perf = evaluate_swing_performance(signals, data_map)
                    status_placeholder.empty()

                    # Metrics calculations
                    total = len(df_perf)
                    t5_hits = len(df_perf[df_perf["Outcome"] == "Hit Target 5%"])
                    t2_hits = len(df_perf[df_perf["Outcome"] == "Hit Target 2%"])
                    stopped = len(df_perf[df_perf["Outcome"] == "Stopped Out"])
                    active = len(df_perf[df_perf["Outcome"] == "Active"])
                    
                    completed_trades = t5_hits + t2_hits + stopped
                    win_rate = ((t5_hits + t2_hits) / completed_trades * 100.0) if completed_trades > 0 else 0.0
                    avg_ret = df_perf["Current Return %"].mean()
                    max_ret = df_perf["Max Return %"].max()

                    # KPI Cards
                    m1, m2, m3, m4, m5 = st.columns(5)
                    m1.metric("Total Hits", f"{total}")
                    m2.metric("Win Rate (Closed)", f"{win_rate:.1f}%")
                    m3.metric("Avg Return", f"{avg_ret:+.2f}%")
                    m4.metric("Max Profit Hit", f"{max_ret:+.2f}%" if total > 0 else "0.00%")
                    m5.metric("Active Signals", f"{active}")

                    # Charts Section
                    st.markdown("### 📊 Analytics & Distribution")
                    chart_col1, chart_col2 = st.columns(2)
                    
                    with chart_col1:
                        st.markdown("##### Hits per Day (Past Week)")
                        daily_counts = df_perf.groupby("Signal Date").size().reset_index(name="Hits")
                        st.bar_chart(daily_counts.set_index("Signal Date"))
                        
                    with chart_col2:
                        st.markdown("##### Outcome Distribution")
                        outcome_counts = df_perf.groupby("Outcome").size().reset_index(name="Count")
                        st.bar_chart(outcome_counts.set_index("Outcome"))

                    # Styled dataframe
                    st.markdown("### 📑 Detailed Signal & Execution History")
                    st.dataframe(
                        style_generic_performance_dataframe(df_perf.copy(), theme=st.session_state.theme),
                        use_container_width=True,
                        hide_index=True
                    )

                    # Dated CSV download
                    csv_data = df_perf.to_csv(index=False).encode('utf-8')
                    date_now = datetime.now().strftime("%Y%m%d_%H%M")
                    st.download_button(
                        label="📥 Download Performance Report CSV",
                        data=csv_data,
                        file_name=f"swing_performance_{date_now}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )

            except Exception as e:
                status_placeholder.error(f"Error evaluating swing performance: {e}")
                st.exception(e)

    # ── TAB 2: Intraday & Options Performance ──
    with perf_tab_intra_opt:
        st.markdown("#### ⚡ Intraday & Options Performance Report")
        st.caption("Retrieves real-time 15m details over the past 5 trading days to track intraday setups and option spreads outcomes.")

        run_intra_perf_btn = st.button("⚡ Run Intraday & Options Performance Evaluation", type="primary", use_container_width=True)

        if run_intra_perf_btn:
            status_p = st.empty()
            with status_p.container():
                st.info("Loading 15-minute price history and simulating trades...")

            try:
                # Use standard High Momentum presets for evaluation
                universe = PRESET_UNIVERSES["High Momentum & Beta (F&O)"][:10] # Evaluates top 10 liquid symbols to prevent rate limits
                
                df_intra = backfill_and_evaluate_intraday(universe, days=5)
                
                if df_intra.empty:
                    status_p.warning("No Intraday buy/confirmation triggers found in the past 5 trading days for the screened universe.")
                else:
                    # Evaluate options strategy performance based on the same signals
                    df_options = evaluate_options_performance(
                        [{"Symbol": r["Symbol"], "Signal Date": r["Signal Time"][:10], "Entry Price": r["Entry Price"], "Outcome": r["Outcome"], "Action": "BUY"} for _, r in df_intra.iterrows()],
                        download_prices(universe)
                    )
                    status_p.empty()

                    # 1. Intraday Section
                    st.markdown("### ⚡ Intraday 15m Signal Analytics")
                    i_total = len(df_intra)
                    i_t1 = len(df_intra[df_intra["Outcome"] == "Hit Target 1%"])
                    i_t2 = len(df_intra[df_intra["Outcome"] == "Hit Target 2%"])
                    i_stopped = len(df_intra[df_intra["Outcome"] == "Stopped Out"])
                    i_active = len(df_intra[df_intra["Outcome"] == "Active"])
                    
                    i_closed = i_t1 + i_t2 + i_stopped
                    i_win_rate = ((i_t1 + i_t2) / i_closed * 100.0) if i_closed > 0 else 0.0
                    i_avg_ret = df_intra["Return %"].mean()

                    im1, im2, im3, im4 = st.columns(4)
                    im1.metric("Intraday Triggers", f"{i_total}")
                    im2.metric("Intraday Win Rate", f"{i_win_rate:.1f}%")
                    im3.metric("Avg Return per Trade", f"{i_avg_ret:+.2f}%")
                    im4.metric("Stopped Out", f"{i_stopped}")

                    st.dataframe(
                        style_generic_performance_dataframe(df_intra.copy(), theme=st.session_state.theme),
                        use_container_width=True,
                        hide_index=True
                    )

                    # 2. Options Section
                    if not df_options.empty:
                        st.markdown("---")
                        st.markdown("### 🎯 Gated Options Strategy Performance")
                        st.caption("Simulates performance of recommended debit spreads (Bull Call / Bear Put) on the trigger assets.")

                        opt_pnl = df_options["Estimated P&L"].sum()
                        opt_win = len(df_options[df_options["Status"].str.contains("Target")])
                        opt_loss = len(df_options[df_options["Status"].str.contains("Stop")])
                        opt_total = len(df_options)
                        opt_win_rate = (opt_win / (opt_win + opt_loss) * 100.0) if (opt_win + opt_loss) > 0 else 0.0

                        om1, om2, om3, om4 = st.columns(4)
                        om1.metric("Recommended Spreads", f"{opt_total}")
                        om1.caption("Gated by MTF + Chain Score")
                        om2.metric("Estimated Total P&L", f"₹{opt_pnl:+,.2f}", delta_color="normal")
                        om3.metric("Options Win Rate", f"{opt_win_rate:.1f}%")
                        om4.metric("Outcome Split (W/L)", f"{opt_win}W / {opt_loss}L")

                        st.dataframe(
                            style_generic_performance_dataframe(df_options.copy(), theme=st.session_state.theme),
                            use_container_width=True,
                            hide_index=True
                        )

                        # Combined CSV Download
                        combined_csv = df_intra.to_csv(index=False)
                        st.download_button(
                            label="📥 Download Intraday Performance Report",
                            data=combined_csv.encode('utf-8'),
                            file_name=f"intraday_performance_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                            mime="text/csv",
                            use_container_width=True
                        )
            except Exception as e:
                status_p.error(f"Error evaluating intraday & options performance: {e}")
                st.exception(e)

    # ── TAB 3: Tracked Watchlist (Manual) ──
    with perf_tab_manual:
        st.markdown("#### 📌 Manually Tracked Watchlist")
        st.caption("Displays the performance of signals you have manually selected and saved for tracking.")

        tracked_signals = load_tracked_signals()
        if not tracked_signals:
            st.info("No manually tracked signals in your watchlist. Save signals from Swing Results or Intraday Deep-Dive to track them here!")
        else:
            run_manual_perf_btn = st.button("🔄 Refresh Watchlist Performance", type="primary", use_container_width=True)
            
            # Auto-run on load or when clicked
            with st.spinner("Evaluating live watchlist performance..."):
                df_tracked = evaluate_tracked_signals_performance()
                
            if not df_tracked.empty:
                # Summary metrics
                t_total = len(df_tracked)
                t_wins = len(df_tracked[df_tracked["Outcome"].str.contains("Target")])
                t_loss = len(df_tracked[df_tracked["Outcome"].str.contains("Stop")])
                t_active = len(df_tracked[df_tracked["Outcome"] == "Active"])
                
                t_closed = t_wins + t_loss
                t_win_rate = (t_wins / t_closed * 100.0) if t_closed > 0 else 0.0
                t_avg_ret = df_tracked["Return %"].mean()
                
                tm1, tm2, tm3, tm4 = st.columns(4)
                tm1.metric("Tracked Signals", f"{t_total}")
                tm2.metric("Win Rate", f"{t_win_rate:.1f}%")
                tm3.metric("Avg Return", f"{t_avg_ret:+.2f}%")
                tm4.metric("Active Trades", f"{t_active}")
                
                st.markdown("### 📑 Live Watchlist Details")
                st.dataframe(
                    style_generic_performance_dataframe(df_tracked.copy(), theme=st.session_state.theme),
                    use_container_width=True,
                    hide_index=True
                )
                
                # Delete tracked signal section
                st.markdown("---")
                st.markdown("#### ❌ Untrack a Signal")
                del_col1, del_col2 = st.columns([3, 1])
                with del_col1:
                    tracked_options = [f"{s['symbol']} ({s['type']} - {s['signal_date']})" for s in tracked_signals]
                    sig_to_del = st.selectbox("Select signal to remove from tracking", tracked_options, key="del_tracked_sig_select")
                with del_col2:
                    st.markdown("<br>", unsafe_allow_html=True)
                    del_btn = st.button("❌ Remove Signal", key="del_tracked_sig_btn", use_container_width=True)
                    
                if del_btn and sig_to_del:
                    # Find index to delete
                    idx_to_del = tracked_options.index(sig_to_del)
                    removed_sig = tracked_signals.pop(idx_to_del)
                    save_tracked_signals(tracked_signals)
                    st.success(f"Removed {removed_sig['symbol']} ({removed_sig['type']}) from your watchlist.")
                    st.rerun()

