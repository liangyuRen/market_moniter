"""技术指标计算"""
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def calc_ma(series: pd.Series, periods: list[int]) -> dict[int, pd.Series]:
    """计算多条移动平均线"""
    result = {}
    for p in periods:
        result[p] = series.rolling(window=p).mean()
    return result


def calc_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """MACD指标"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = 2 * (dif - dea)
    return {"dif": dif, "dea": dea, "hist": hist}


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI相对强弱指标"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def calc_kdj(high: pd.Series, low: pd.Series, close: pd.Series,
             n: int = 9, m1: int = 3, m2: int = 3) -> dict:
    """KDJ随机指标"""
    lowest_low = low.rolling(window=n).min()
    highest_high = high.rolling(window=n).max()
    rsv = ((close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)) * 100
    rsv = rsv.fillna(50)
    k = rsv.ewm(alpha=1 / m1, adjust=False).mean()
    d = k.ewm(alpha=1 / m2, adjust=False).mean()
    j = 3 * k - 2 * d
    return {"k": k, "d": d, "j": j}


def calc_boll(close: pd.Series, period: int = 20, std_mult: float = 2.0) -> dict:
    """布林带"""
    mid = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return {"mid": mid, "upper": upper, "lower": lower}


def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """平均真实波幅ATR"""
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def calc_volume_ratio(latest_volume: float, volume_series: pd.Series, ma_period: int = 5) -> float:
    """量比 = 当日成交量 / 过去N日均量"""
    if len(volume_series) < ma_period:
        return 1.0
    avg_vol = volume_series.iloc[-ma_period:].mean()
    if avg_vol == 0:
        return 1.0
    return latest_volume / avg_vol


def check_macd_golden_cross(hist: pd.Series, lookback: int = 3) -> bool:
    """检测MACD金叉（DIF上穿DEA）"""
    if len(hist) < lookback + 1:
        return False
    recent = hist.iloc[-(lookback + 1):]
    # 金叉：柱状图由负转正
    return recent.iloc[-2] <= 0 and recent.iloc[-1] > 0


def check_macd_dead_cross(hist: pd.Series, lookback: int = 3) -> bool:
    """检测MACD死叉（DIF下穿DEA）"""
    if len(hist) < lookback + 1:
        return False
    recent = hist.iloc[-(lookback + 1):]
    return recent.iloc[-2] >= 0 and recent.iloc[-1] < 0


def check_ma_breakout(price: float, close_series: pd.Series, ma_period: int) -> bool:
    """检测价格突破MA均线"""
    if len(close_series) < ma_period:
        return False
    ma_value = close_series.iloc[-ma_period:].mean()
    if ma_value == 0:
        return False
    prev_close = close_series.iloc[-2]
    # 今天收盘上穿均线
    return prev_close <= ma_value and price > ma_value


def check_rsi_extreme(rsi_value: float, oversold: float = 30, overbought: float = 70) -> str:
    """RSI极端区域判断"""
    if rsi_value <= oversold:
        return "oversold"
    elif rsi_value >= overbought:
        return "overbought"
    return "normal"


def calc_technical_summary(hist_df: pd.DataFrame) -> dict:
    """从历史K线计算全部技术指标摘要"""
    if hist_df.empty or len(hist_df) < 20:
        return {}

    close = hist_df["收盘"].astype(float)
    high = hist_df["最高"].astype(float)
    low = hist_df["最低"].astype(float)
    volume = hist_df["成交量"].astype(float)
    latest_price = close.iloc[-1]
    latest_volume = volume.iloc[-1]

    # MA
    mas = {}
    for p in [5, 10, 20, 60, 120]:
        if len(close) >= p:
            mas[f"ma{p}"] = round(close.iloc[-p:].mean(), 4)

    # MACD
    macd = calc_macd(close)
    latest_hist = macd["hist"].iloc[-1]

    # RSI(14)
    rsi = calc_rsi(close)
    latest_rsi = round(rsi.iloc[-1], 2)

    # KDJ
    kdj = calc_kdj(high, low, close)
    latest_k = round(kdj["k"].iloc[-1], 2)
    latest_d = round(kdj["d"].iloc[-1], 2)
    latest_j = round(kdj["j"].iloc[-1], 2)

    # 布林带
    boll = calc_boll(close)
    boll_pos = ""
    if latest_price >= boll["upper"].iloc[-1]:
        boll_pos = "above_upper"
    elif latest_price <= boll["lower"].iloc[-1]:
        boll_pos = "below_lower"
    elif latest_price <= boll["mid"].iloc[-1]:
        boll_pos = "below_mid"
    else:
        boll_pos = "above_mid"

    # 量比
    vol_ratio = calc_volume_ratio(latest_volume, volume)

    # 信号
    signals = []
    if check_macd_golden_cross(macd["hist"]):
        signals.append("macd_golden_cross")
    if check_macd_dead_cross(macd["hist"]):
        signals.append("macd_dead_cross")
    rsi_state = check_rsi_extreme(latest_rsi)
    if rsi_state == "oversold":
        signals.append("rsi_oversold")
    elif rsi_state == "overbought":
        signals.append("rsi_overbought")
    if latest_j < 0:
        signals.append("kdj_oversold")
    if latest_j > 100:
        signals.append("kdj_overbought")

    return {
        "price": round(latest_price, 4),
        "mas": mas,
        "macd_hist": round(latest_hist, 4),
        "rsi14": latest_rsi,
        "kdj_k": latest_k,
        "kdj_d": latest_d,
        "kdj_j": latest_j,
        "boll_position": boll_pos,
        "volume_ratio": round(vol_ratio, 2),
        "signals": signals,
    }
