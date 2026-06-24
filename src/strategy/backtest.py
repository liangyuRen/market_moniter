"""
量化策略回测引擎 — MACD/MA/RSI/Boll/KDJ 信号回测
"""
import json
import logging
from datetime import datetime, date
from typing import Callable

import numpy as np
import pandas as pd

from src.collector.market_data import fetch_stock_history
from src.analyzer.technical import calc_macd, calc_rsi, calc_kdj, calc_boll, calc_ma, calc_atr
from src.storage.database import get_conn

logger = logging.getLogger(__name__)


# ====== 策略定义 ======

def signal_macd_cross(df: pd.DataFrame) -> pd.Series:
    """MACD金叉买入(1)/死叉卖出(-1)/持有(0)"""
    close = df["收盘"].astype(float)
    macd = calc_macd(close)
    signals = pd.Series(0, index=df.index)
    dif = macd["dif"]
    dea = macd["dea"]
    for i in range(1, len(dif)):
        if dif.iloc[i-1] <= dea.iloc[i-1] and dif.iloc[i] > dea.iloc[i]:
            signals.iloc[i] = 1
        elif dif.iloc[i-1] >= dea.iloc[i-1] and dif.iloc[i] < dea.iloc[i]:
            signals.iloc[i] = -1
    return signals


def signal_ma_cross(df: pd.DataFrame, fast: int = 5, slow: int = 20) -> pd.Series:
    """均线金叉买入/死叉卖出"""
    close = df["收盘"].astype(float)
    ma_fast = close.rolling(fast).mean()
    ma_slow = close.rolling(slow).mean()
    signals = pd.Series(0, index=df.index)
    for i in range(slow, len(close)):
        if ma_fast.iloc[i-1] <= ma_slow.iloc[i-1] and ma_fast.iloc[i] > ma_slow.iloc[i]:
            signals.iloc[i] = 1
        elif ma_fast.iloc[i-1] >= ma_slow.iloc[i-1] and ma_fast.iloc[i] < ma_slow.iloc[i]:
            signals.iloc[i] = -1
    return signals


def signal_rsi_reversal(df: pd.DataFrame, period: int = 14, oversold: int = 30, overbought: int = 70) -> pd.Series:
    """RSI超卖反弹买入/超买回落卖出"""
    close = df["收盘"].astype(float)
    rsi = calc_rsi(close, period)
    signals = pd.Series(0, index=df.index)
    for i in range(period + 1, len(rsi)):
        if rsi.iloc[i-1] < oversold and rsi.iloc[i] >= oversold:
            signals.iloc[i] = 1
        elif rsi.iloc[i-1] > overbought and rsi.iloc[i] <= overbought:
            signals.iloc[i] = -1
    return signals


def signal_boll_break(df: pd.DataFrame, period: int = 20, std: float = 2.0) -> pd.Series:
    """布林带下轨反弹买入/上轨回落卖出"""
    close = df["收盘"].astype(float)
    boll = calc_boll(close, period, std)
    signals = pd.Series(0, index=df.index)
    for i in range(period + 1, len(close)):
        if close.iloc[i-1] <= boll["lower"].iloc[i-1] and close.iloc[i] > boll["lower"].iloc[i]:
            signals.iloc[i] = 1
        elif close.iloc[i-1] >= boll["upper"].iloc[i-1] and close.iloc[i] < boll["upper"].iloc[i]:
            signals.iloc[i] = -1
    return signals


def signal_volume_break(df: pd.DataFrame, vol_mult: float = 2.0, price_up: float = 1.0) -> pd.Series:
    """放量上涨买入/缩量下跌卖出"""
    close = df["收盘"].astype(float)
    volume = df["成交量"].astype(float)
    vol_ma = volume.rolling(20).mean()
    signals = pd.Series(0, index=df.index)
    for i in range(21, len(close)):
        chg = (close.iloc[i] - close.iloc[i-1]) / close.iloc[i-1] * 100
        vol_ratio = volume.iloc[i] / vol_ma.iloc[i] if vol_ma.iloc[i] > 0 else 1
        if vol_ratio > vol_mult and chg > price_up:
            signals.iloc[i] = 1
        elif vol_ratio < 0.5 and chg < -price_up:
            signals.iloc[i] = -1
    return signals


STRATEGIES = {
    "macd_cross": {"name": "MACD金叉死叉", "func": signal_macd_cross, "params": {}},
    "ma_cross": {"name": "均线交叉(5/20)", "func": signal_ma_cross, "params": {"fast": 5, "slow": 20}},
    "ma_cross_10_60": {"name": "均线交叉(10/60)", "func": signal_ma_cross, "params": {"fast": 10, "slow": 60}},
    "rsi_reversal": {"name": "RSI超买超卖", "func": signal_rsi_reversal, "params": {"period": 14, "oversold": 30, "overbought": 70}},
    "boll_break": {"name": "布林带突破", "func": signal_boll_break, "params": {"period": 20, "std": 2.0}},
    "volume_break": {"name": "放量突破", "func": signal_volume_break, "params": {"vol_mult": 2.0, "price_up": 1.0}},
}


# ====== 回测引擎 ======

def run_backtest(code: str, strategy_id: str, days: int = 500,
                 init_capital: float = 100000, commission: float = 0.0003) -> dict:
    """
    单只股票单策略回测
    commission: 手续费率 (默认万三)
    """
    if strategy_id not in STRATEGIES:
        return {"error": f"未知策略: {strategy_id}"}

    strategy = STRATEGIES[strategy_id]
    market = "SH" if code.startswith(("6", "688")) else "SZ"
    hist = fetch_stock_history(code, market, days=days)

    if hist.empty or len(hist) < 60:
        return {"error": "历史数据不足"}

    # 计算信号
    try:
        signals = strategy["func"](hist, **strategy["params"])
    except Exception as e:
        return {"error": f"信号计算失败: {e}"}

    # 模拟交易
    close = hist["收盘"].astype(float)
    trades, equity_curve = _simulate_trades(
        signals, close, init_capital, commission
    )

    # 统计指标
    stats = _calc_stats(trades, equity_curve, close)
    stats["strategy"] = strategy_id
    stats["strategy_name"] = strategy["name"]
    stats["code"] = code
    stats["backtest_date"] = date.today().isoformat()
    stats["trades_json"] = json.dumps(trades, ensure_ascii=False, default=str)

    # 存到数据库
    _save_backtest_result(code, strategy_id, stats, trades)

    return stats


def _simulate_trades(signals: pd.Series, close: pd.Series,
                     capital: float, commission: float) -> tuple:
    """模拟交易：信号→买卖→权益曲线"""
    trades = []
    position = 0  # 持仓股数
    cash = capital
    equity = []
    buy_price = 0

    for i in range(len(signals)):
        price = close.iloc[i]
        sig = signals.iloc[i]

        if sig == 1 and position == 0:  # 买入
            position = int(cash * 0.95 / price)  # 95%仓位
            if position > 0:
                cost = position * price * (1 + commission)
                cash -= cost
                buy_price = price
                trades.append({
                    "date": str(close.index[i]),
                    "action": "buy", "price": round(price, 2),
                    "shares": position, "amount": round(cost, 2),
                })

        elif sig == -1 and position > 0:  # 卖出
            revenue = position * price * (1 - commission)
            cash += revenue
            return_pct = round((price - buy_price) / buy_price * 100, 2) if buy_price > 0 else 0
            trades.append({
                "date": str(close.index[i]),
                "action": "sell", "price": round(price, 2),
                "shares": position, "amount": round(revenue, 2),
                "return_pct": return_pct,
            })
            position = 0
            buy_price = 0

        # 权益 = 现金 + 持仓市值
        total = cash + position * price
        equity.append(round(total, 2))

    # 最后如果还持仓，按最后价格平仓
    if position > 0:
        final_price = close.iloc[-1]
        revenue = position * final_price * (1 - commission)
        cash += revenue
        return_pct = round((final_price - buy_price) / buy_price * 100, 2) if buy_price > 0 else 0
        trades.append({
            "date": str(close.index[-1]),
            "action": "sell_final", "price": round(final_price, 2),
            "shares": position, "amount": round(revenue, 2),
            "return_pct": return_pct,
        })

    return trades, equity


def _calc_stats(trades: list, equity: list, close: pd.Series) -> dict:
    """计算回测统计指标"""
    if not trades:
        return {"total_return": 0, "win_rate": 0, "max_drawdown": 0, "sharpe": 0}

    sell_trades = [t for t in trades if t["action"] in ("sell", "sell_final")]
    buy_trades = [t for t in trades if t["action"] == "buy"]

    # 总收益率
    total_return = 0
    for t in sell_trades:
        total_return += t.get("return_pct", 0)

    # 胜率
    wins = [t for t in sell_trades if t.get("return_pct", 0) > 0]
    win_rate = round(len(wins) / len(sell_trades) * 100, 2) if sell_trades else 0

    # 最大回撤
    max_dd = 0
    if equity:
        peak = equity[0]
        for v in equity:
            if v > peak:
                peak = v
            dd = (peak - v) / peak * 100
            if dd > max_dd:
                max_dd = dd

    # 平均每笔收益
    avg_return = round(sum(t.get("return_pct", 0) for t in sell_trades) / len(sell_trades), 2) if sell_trades else 0

    # 买入持有收益 (benchmark)
    if len(close) > 1:
        buy_hold = round((close.iloc[-1] - close.iloc[0]) / close.iloc[0] * 100, 2)
    else:
        buy_hold = 0

    return {
        "total_trades": len(buy_trades),
        "total_return": round(total_return, 2),
        "win_rate": win_rate,
        "max_drawdown": round(max_dd, 2),
        "avg_return": avg_return,
        "buy_hold_return": buy_hold,
        "sharpe": 0,
        "equity_curve": equity[-50:] if len(equity) > 50 else equity,  # 最后50点
    }


def _save_backtest_result(code: str, strategy_id: str, stats: dict, trades: list):
    """保存回测结果到数据库"""
    conn = get_conn()
    today = date.today().isoformat()
    conn.execute("""
        INSERT OR REPLACE INTO backtest_result
            (code, strategy, backtest_date, total_return, win_rate, max_drawdown,
             avg_return, total_trades, buy_hold_return, trades_json, equity_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        code, strategy_id, today,
        stats.get("total_return", 0),
        stats.get("win_rate", 0),
        stats.get("max_drawdown", 0),
        stats.get("avg_return", 0),
        stats.get("total_trades", 0),
        stats.get("buy_hold_return", 0),
        json.dumps(trades, ensure_ascii=False, default=str),
        json.dumps(stats.get("equity_curve", []), ensure_ascii=False),
    ))
    conn.commit()


def batch_backtest(codes: list[str], strategies: list[str] = None,
                   days: int = 500) -> list[dict]:
    """批量回测"""
    if strategies is None:
        strategies = ["macd_cross", "ma_cross", "rsi_reversal"]
    results = []
    for code in codes:
        for sid in strategies:
            try:
                r = run_backtest(code, sid, days)
                if "error" not in r:
                    results.append(r)
            except Exception as e:
                logger.error(f"回测失败 {code} {sid}: {e}")
    return results


def get_backtest_results(code: str = None, strategy: str = None) -> list[dict]:
    """查询回测结果"""
    conn = get_conn()
    sql = "SELECT * FROM backtest_result WHERE 1=1"
    params = []
    if code:
        sql += " AND code = ?"
        params.append(code)
    if strategy:
        sql += " AND strategy = ?"
        params.append(strategy)
    sql += " ORDER BY backtest_date DESC, total_return DESC"
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
