"""
Intraday Multi-Timeframe (MTF) Scanner Engine
Daily -> Hourly (1h) -> 15-Minute Momentum & Breakout Analysis
"""

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime

# ─────────────────────────────────────────────
# Universe Presets for Intraday Trading
# ─────────────────────────────────────────────

PRESET_UNIVERSES = {
    "Nifty 50 Liquid Top": [
        "NIFTY", "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "ITC", "BHARTIARTL",
        "LT", "SBIN", "AXISBANK", "KOTAKBANK", "HINDUNILVR", "M&M", "TATAMOTORS",
        "BAJFINANCE", "MARUTI", "SUNPHARMA", "NTPC", "POWERGRID", "TITAN"
    ],
    "High Momentum & Beta (F&O)": [
        "TRENT", "BEL", "HAL", "DIXON", "POLYCAB", "PERSISTENT", "COFORGE",
        "BSE", "CDSL", "MCX", "ZOMATO", "TATAPOWER", "CHAMBLFERT", "VEDL",
        "FEDERALBNK", "CANBK", "PNB", "ASHOKLEY", "TVSMOTOR", "HINDALCO"
    ],
    "Nifty Bank & Financials": [
        "HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK",
        "FEDERALBNK", "IDFCFIRSTB", "AUBANK", "BANDHANBNK", "BAJFINANCE",
        "BAJAJFINSV", "CHOLAFIN", "MUTHOOTFIN", "SHRIRAMFIN"
    ],
    "Nifty IT & Tech": [
        "TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM", "PERSISTENT",
        "COFORGE", "MPHASIS", "KPITTECH", "TATAELXSI", "LTTS"
    ],
    "Nifty Auto & Metals": [
        "TATAMOTORS", "M&M", "MARUTI", "BAJAJ-AUTO", "HEROMOTOCO", "EICHERMOT",
        "TVSMOTOR", "TATASTEEL", "JSWSTEEL", "HINDALCO", "JINDALSTEL", "VEDL", "NMDC"
    ]
}


# ─────────────────────────────────────────────
# Technical Indicators
# ─────────────────────────────────────────────

def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    """Calculate Relative Strength Index (Wilder's EMA smoothing)."""
    d = s.diff()
    gain = d.clip(lower=0)
    loss = -d.clip(upper=0)
    ag = gain.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    al = loss.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    rs = ag / al.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def ema(s: pd.Series, n: int) -> pd.Series:
    """Exponential Moving Average."""
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Average True Range (Wilder's smoothing)."""
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False, min_periods=n).mean()


def vwap(df: pd.DataFrame) -> pd.Series:
    """Intraday Volume-Weighted Average Price resetting each trading session."""
    tp = (df["High"] + df["Low"] + df["Close"]) / 3.0
    day = df.index.date
    cum_vol = df["Volume"].groupby(day).cumsum().replace(0, np.nan)
    cum_tp_vol = (tp * df["Volume"]).groupby(day).cumsum()
    return cum_tp_vol / cum_vol


def volume_ratio(df: pd.DataFrame, n: int = 20) -> pd.Series:
    """Ratio of current volume against rolling n-period average volume."""
    vol_mean = df["Volume"].rolling(n).mean().replace(0, np.nan)
    return df["Volume"] / vol_mean


def prepare_df(df: pd.DataFrame) -> pd.DataFrame:
    """Clean and standardize OHLCV dataframe."""
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    needed = ["Open", "High", "Low", "Close", "Volume"]
    cols = [c for c in needed if c in df.columns]
    if len(cols) < 5:
        return pd.DataFrame()
    return df[cols].dropna().sort_index()


# ─────────────────────────────────────────────
# Risk & Position Sizing
# ─────────────────────────────────────────────

def calculate_position_size(capital: float, risk_percent: float, entry: float, stop: float) -> int:
    """
    Calculate position sizing in number of shares based on fixed fractional risk:
    Quantity = (Capital * Risk%) / (Entry - Stop Loss)
    """
    if entry <= 0 or stop <= 0 or entry <= stop or capital <= 0 or risk_percent <= 0:
        return 0
    risk_rupees = capital * (risk_percent / 100.0)
    risk_per_share = entry - stop
    return int(risk_rupees / risk_per_share) if risk_per_share > 0 else 0


# ─────────────────────────────────────────────
# Data Fetching
# ─────────────────────────────────────────────

def download_ticker_data(symbol: str, period: str, interval: str) -> pd.DataFrame:
    """Download OHLCV data for an NSE symbol from yfinance."""
    clean_sym = symbol.strip().upper().replace("&", "-").replace(" ", "")
    if clean_sym.startswith("^") or clean_sym.endswith(".NS"):
        ticker = clean_sym
    else:
        ticker = f"{clean_sym}.NS"
    try:
        raw = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False
        )
        return prepare_df(raw)
    except Exception:
        return pd.DataFrame()


def download_intraday_timeframes(symbol: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Fetch Daily (2y), Hourly (60d), and 15-Minute (30d) data for multi-timeframe analysis.
    """
    daily_df = download_ticker_data(symbol, period="2y", interval="1d")
    hourly_df = download_ticker_data(symbol, period="60d", interval="1h")
    m15_df = download_ticker_data(symbol, period="30d", interval="15m")
    return daily_df, hourly_df, m15_df


# ─────────────────────────────────────────────
# Scoring & Signal Logic
# ─────────────────────────────────────────────

def score_intraday_signal(
    dr: float, hr: float, mr: float,
    dt: bool, ht: bool, mt: bool,
    avw: bool, vr: float, br: bool
) -> float:
    """
    Composite scoring system for Intraday MTF (0-100 pts):
      - Daily RSI (max 30 pts) + Daily Trend (8 pts) = 38 pts
      - Hourly RSI (max 20 pts) + Hourly Trend (5 pts) = 25 pts
      - 15m RSI (max 20 pts) + VWAP Support (5 pts) + Breakout (5 pts) + Volume Surge (max 10 pts) + 15m Trend (5 pts) = 45 pts
    """
    s = 0.0
    # Daily RSI
    s += 30 if dr >= 70 else 27 if dr >= 60 else 22 if dr >= 55 else 0
    # Daily Trend (Close > EMA20 > EMA50)
    s += 8 if dt else 0
    # Hourly RSI
    s += 20 if hr >= 65 else 17 if hr >= 60 else 14 if hr >= 55 else 0
    # Hourly Trend (Close > EMA20 > EMA50)
    s += 5 if ht else 0
    # 15m RSI
    s += 20 if mr >= 60 else 17 if mr >= 55 else 13 if mr >= 50 else 0
    # Price > VWAP
    s += 5 if avw else 0
    # 20-bar 15m Breakout
    s += 5 if br else 0
    # 15m Volume Expansion
    s += 10 if vr >= 2.0 else 8 if vr >= 1.5 else 5 if vr >= 1.2 else 0
    # 15m Trend (Price > EMA9 > EMA20)
    s += 5 if mt else 0

    return min(s, 100.0)


def evaluate_stock_intraday(
    symbol: str,
    daily_rsi_min: float = 55.0,
    hourly_rsi_min: float = 55.0,
    m15_rsi_min: float = 50.0,
    volume_multiplier: float = 1.5,
    atr_multiplier: float = 1.5,
    d_df: pd.DataFrame = None,
    h_df: pd.DataFrame = None,
    m_df: pd.DataFrame = None
) -> dict | None:
    """
    Evaluate a single stock across Daily, Hourly, and 15m timeframes.
    Returns metrics dict or None if data insufficient.
    """
    if d_df is None or h_df is None or m_df is None:
        d_df, h_df, m_df = download_intraday_timeframes(symbol)

    if min(len(d_df), len(h_df), len(m_df)) < 50:
        return None

    # Daily Metrics
    d_close = d_df["Close"]
    dr = float(rsi(d_close).iloc[-1])
    d20 = float(ema(d_close, 20).iloc[-1])
    d50 = float(ema(d_close, 50).iloc[-1])
    d_curr = float(d_close.iloc[-1])
    dt = bool(d_curr > d20 > d50)

    # Hourly Metrics
    h_close = h_df["Close"]
    hr = float(rsi(h_close).iloc[-1])
    h20 = float(ema(h_close, 20).iloc[-1])
    h50 = float(ema(h_close, 50).iloc[-1])
    h_curr = float(h_close.iloc[-1])
    ht = bool(h_curr > h20 > h50)

    # 15-Minute Metrics
    m_close = m_df["Close"]
    mr = float(rsi(m_close).iloc[-1])
    m9 = float(ema(m_close, 9).iloc[-1])
    m20 = float(ema(m_close, 20).iloc[-1])
    price = float(m_close.iloc[-1])
    vw_series = vwap(m_df)
    vw = float(vw_series.iloc[-1]) if not vw_series.empty and not pd.isna(vw_series.iloc[-1]) else price
    vr_series = volume_ratio(m_df, 20)
    vr = float(vr_series.iloc[-1]) if not vr_series.empty and not pd.isna(vr_series.iloc[-1]) else 1.0

    mt = bool(price > m9 > m20)
    avw = bool(price >= vw)

    # Prior 20-bar high (excluding current bar)
    prior_high = float(m_df["High"].iloc[-21:-1].max()) if len(m_df) >= 21 else float(m_df["High"].max())
    breakout = bool(price > prior_high)

    atrv = float(atr(m_df, 14).iloc[-1]) if len(m_df) >= 14 else float(price * 0.005)

    score = score_intraday_signal(dr, hr, mr, dt, ht, mt, avw, vr, breakout)

    # Hard Alignment Gate
    hard = (
        dr >= daily_rsi_min and
        hr >= hourly_rsi_min and
        mr >= m15_rsi_min and
        dt and ht and avw
    )

    # Signal Classification
    if hard and score >= 85:
        signal = "STRONG BUY CANDIDATE"
    elif hard and score >= 75:
        signal = "BUY ON CONFIRMATION"
    elif score >= 65:
        signal = "WATCH"
    else:
        signal = "NO TRADE"

    # Setup Identification
    if breakout and avw and vr >= volume_multiplier:
        setup = "BREAKOUT"
    elif avw and mt and mr >= m15_rsi_min:
        setup = "VWAP MOMENTUM"
    elif avw and mr >= m15_rsi_min:
        setup = "PULLBACK / RECLAIM"
    else:
        setup = "WAIT"

    stop_loss = round(price - atr_multiplier * atrv, 2)
    target_1 = round(price * 1.01, 2)  # +1%
    target_2 = round(price * 1.02, 2)  # +2%
    risk_amt = max(price - stop_loss, 0.01)
    rr_ratio = round((target_2 - price) / risk_amt, 2)

    return {
        "Symbol": symbol,
        "Score": round(score, 1),
        "Signal": signal,
        "Setup": setup,
        "Price": round(price, 2),
        "VWAP": round(vw, 2),
        "Daily_RSI": round(dr, 1),
        "Hourly_RSI": round(hr, 1),
        "M15_RSI": round(mr, 1),
        "Volume_Ratio": round(vr, 2),
        "Stop_Loss": stop_loss,
        "Target_1": target_1,
        "Target_2": target_2,
        "RR_Ratio": rr_ratio,
        "Daily_Trend": dt,
        "Hourly_Trend": ht,
        "M15_Trend": mt,
        "ATR": round(atrv, 2),
        "Breakout": breakout,
        "Hard_Filter": hard
    }


def scan_intraday_universe(
    symbols: list[str],
    daily_rsi_min: float = 55.0,
    hourly_rsi_min: float = 55.0,
    m15_rsi_min: float = 50.0,
    volume_multiplier: float = 1.5,
    atr_multiplier: float = 1.5,
    progress_callback=None
) -> pd.DataFrame:
    """
    Scan a list of stock symbols for Intraday MTF momentum opportunities.
    """
    rows = []
    total = len(symbols)
    for idx, s in enumerate(symbols):
        sym_clean = s.strip().upper()
        if not sym_clean:
            continue
        try:
            res = evaluate_stock_intraday(
                sym_clean,
                daily_rsi_min=daily_rsi_min,
                hourly_rsi_min=hourly_rsi_min,
                m15_rsi_min=m15_rsi_min,
                volume_multiplier=volume_multiplier,
                atr_multiplier=atr_multiplier
            )
            if res:
                rows.append(res)
        except Exception:
            pass

        if progress_callback:
            progress_callback(idx + 1, total, sym_clean)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    order = {"STRONG BUY CANDIDATE": 0, "BUY ON CONFIRMATION": 1, "WATCH": 2, "NO TRADE": 3}
    df["_order"] = df["Signal"].map(order).fillna(4)
    df = df.sort_values(["_order", "Score"], ascending=[True, False]).drop(columns=["_order"])
    df.insert(0, "Rank", range(1, len(df) + 1))
    return df

