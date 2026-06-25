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


def calc_sentiment_line(hist_df: pd.DataFrame) -> list[dict]:
    """计算复合情绪线 — 综合RSI/MACD/均价偏离/量比/动量的标准化得分(0-100)"""
    if hist_df.empty or len(hist_df) < 20:
        return []

    close = hist_df["收盘"].astype(float)
    high = hist_df["最高"].astype(float)
    low = hist_df["最低"].astype(float)
    volume = hist_df["成交量"].astype(float)

    dates = hist_df.index if hasattr(hist_df.index[0], "strftime") else range(len(close))

    # RSI情绪 (0-100, 50为中性)
    rsi = calc_rsi(close)
    rsi_score = rsi.fillna(50)  # 直接用作情绪分量

    # MACD情绪 (MACD柱标准化)
    macd = calc_macd(close)
    macd_hist = macd["hist"]
    macd_max = macd_hist.abs().rolling(60).max().fillna(macd_hist.abs().max())
    macd_score = 50 + (macd_hist / macd_max.replace(0, 1)) * 40  # 映射到10-90

    # 价格偏离MA20情绪 (偏离越大->极端情绪)
    ma20 = close.rolling(20).mean()
    deviation = (close - ma20) / ma20.replace(0, 1) * 100
    dev_score = 50 - deviation * 5  # 正向偏离->看空, 负向偏离->看多(均值回归)
    dev_score = dev_score.clip(5, 95)

    # 量比情绪 (放量上涨=看多, 放量下跌=看空)
    vol_ma5 = volume.rolling(5).mean()
    vol_ratio = volume / vol_ma5.replace(0, 1)
    price_dir = close.diff().apply(lambda x: 1 if x > 0 else -1 if x < 0 else 0)
    vol_score = 50 + vol_ratio.fillna(1) * price_dir.rolling(3).mean().fillna(0) * 15
    vol_score = vol_score.clip(5, 95)

    # 动量情绪 (5日涨跌幅)
    momentum = close.pct_change(5).fillna(0) * 100
    mom_score = 50 + momentum * 3  # +5%涨幅->65分, -5%->35分
    mom_score = mom_score.clip(5, 95)

    # 复合情绪 = 加权平均
    composite = (
        rsi_score * 0.25 +
        macd_score * 0.25 +
        dev_score * 0.20 +
        vol_score * 0.15 +
        mom_score * 0.15
    )

    # 情绪标签
    def label(v):
        if v >= 75: return "极度乐观"
        if v >= 60: return "偏多"
        if v >= 45: return "中性偏多"
        if v >= 35: return "中性偏空"
        if v >= 20: return "偏空"
        return "极度悲观"

    points = []
    for i in range(len(composite)):
        if pd.isna(composite.iloc[i]):
            continue
        dt = dates[i]
        date_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)
        points.append({
            "date": date_str,
            "composite": round(float(composite.iloc[i]), 1),
            "rsi": round(float(rsi_score.iloc[i]), 1) if not pd.isna(rsi_score.iloc[i]) else 50,
            "macd": round(float(macd_score.iloc[i]), 1) if not pd.isna(macd_score.iloc[i]) else 50,
            "label": label(composite.iloc[i]),
            "price": round(float(close.iloc[i]), 2),
        })

    return points


def calc_support_resistance(hist_df: pd.DataFrame) -> dict:
    """计算关键支撑位和阻力位"""
    if hist_df.empty or len(hist_df) < 20:
        return {}

    close = hist_df["收盘"].astype(float)
    high = hist_df["最高"].astype(float)
    low = hist_df["最低"].astype(float)
    price = close.iloc[-1]

    # 移动均线支撑/阻力
    mas = {}
    for p in [5, 10, 20, 60, 120, 250]:
        if len(close) >= p:
            mas[f"ma{p}"] = round(close.iloc[-p:].mean(), 2)

    # 布林带上下轨
    boll = calc_boll(close)
    boll_upper = round(boll["upper"].iloc[-1], 2)
    boll_mid = round(boll["mid"].iloc[-1], 2)
    boll_lower = round(boll["lower"].iloc[-1], 2)

    # 近期高低点
    recent_20_high = round(high.iloc[-20:].max(), 2)
    recent_20_low = round(low.iloc[-20:].min(), 2)
    recent_60_high = round(high.iloc[-60:].max(), 2) if len(high) >= 60 else recent_20_high
    recent_60_low = round(low.iloc[-60:].min(), 2) if len(low) >= 60 else recent_20_low

    # 收集所有支撑和阻力候选
    support_candidates = []
    resistance_candidates = []

    for label, val in mas.items():
        if val < price:
            support_candidates.append((val, label.upper()))
        else:
            resistance_candidates.append((val, label.upper()))

    support_candidates.append((boll_lower, "布林下轨"))
    resistance_candidates.append((boll_upper, "布林上轨"))
    support_candidates.append((recent_20_low, "20日低点"))
    resistance_candidates.append((recent_20_high, "20日高点"))

    if len(high) >= 60:
        support_candidates.append((recent_60_low, "60日低点"))
        resistance_candidates.append((recent_60_high, "60日高点"))

    # 排序：支撑位从高到低（离现价最近的在前面），阻力位从低到高
    support_candidates.sort(key=lambda x: -x[0])
    resistance_candidates.sort(key=lambda x: x[0])

    # 取最近的3个
    supports = [{"price": p, "label": l} for p, l in support_candidates[:3] if p < price]
    resistances = [{"price": p, "label": l} for p, l in resistance_candidates[:3] if p > price]

    return {
        "price": round(price, 2),
        "supports": supports,
        "resistances": resistances,
        "boll_upper": boll_upper,
        "boll_mid": boll_mid,
        "boll_lower": boll_lower,
    }


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
